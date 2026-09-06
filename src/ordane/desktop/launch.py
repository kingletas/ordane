"""The launch dialog: a typed form, the exact command, and a confirmation that bites."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core import command as command_module  # noqa: E402
from ..core import composition as composition_module  # noqa: E402
from ..core import inventory as inventory_module  # noqa: E402
from ..core.catalog import Target  # noqa: E402
from ..presentation import language  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402

# What the preview says while the form is not yet answerable. It is deliberately
# not a command: printing one with a placeholder in it invites somebody to copy
# a line that would not run.
NOT_YET = "— fill the form in and the exact command appears here"

NO_ENVIRONMENT = "No environment may be launched against, so nothing can run from here."


class LaunchDialog(Adw.Dialog):
    """Collects the parameters for one target, validating before it hands them over."""

    def __init__(self, *, target: Target, catalog, config, repo, on_launch) -> None:
        super().__init__(title=f"Run {target.name}", content_width=580)
        self._target = target
        self._catalog = catalog
        self._config = config
        self._repo = repo
        self._on_launch = on_launch
        self._fields: dict[str, Gtk.Widget] = {}
        self._confirm_entry: Gtk.Entry | None = None
        self._confirm_row: Adw.ActionRow | None = None

        # What the chosen environment is actually made of, asked on a thread.
        self._reach = w.label("", "metric-detail", wrap=True)
        self._inventories: dict[str, object] = {}
        self._preview = w.label("", "numeric", wrap=True)
        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")

        self.set_child(self._build())
        self._refresh_preview()
        self._bind_launch_key()

    # --- construction ---

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        self._run_button = Gtk.Button(label="Run")
        self._run_button.add_css_class(
            "destructive-action" if self._target.danger == "high" else "suggested-action"
        )
        self._run_button.connect("clicked", self._on_run_clicked)
        self._run_button.set_sensitive(self._can_run())
        if not self._can_run():
            self._run_button.set_tooltip_text(NO_ENVIRONMENT)
        header.pack_end(self._run_button)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(16)

        body.append(self._error)
        body.append(w.label(self._target.description, "tint-muted", wrap=True))

        note = language.danger_note(self._target.danger)
        if self._target.danger != "low":
            banner = Adw.Banner(title=note, revealed=True)
            if self._target.danger == "high":
                banner.add_css_class("error")
            body.append(banner)

        if not self._can_run():
            body.append(Adw.Banner(title=NO_ENVIRONMENT, revealed=True))

        body.append(self._form())

        body.append(self._command_strip())

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _bind_launch_key(self) -> None:
        """Ctrl+Return launches, so a form filled from the keyboard can be
        finished from the keyboard. Plain Return does not: this dialog runs
        things, and a stray Return in an entry must not be one of them."""
        trigger = Gtk.ShortcutTrigger.parse_string("<Control>Return")
        action = Gtk.CallbackAction.new(lambda *_a: bool(self._on_run_clicked(None)) or True)
        self.add_shortcut(Gtk.Shortcut.new(trigger, action))

    def _command_strip(self) -> Gtk.Widget:
        """The exact command, and a button that copies it.

        The label is not selectable on purpose: see the note in the run view.
        """
        strip = w.box(Gtk.Orientation.HORIZONTAL, 10)
        strip.add_css_class("command-strip")
        inner = w.box(spacing=4, hexpand=True)
        inner.append(w.label("WILL RUN", "metric-label"))
        inner.append(self._preview)
        strip.append(inner)

        copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
        copy.add_css_class("flat")
        copy.set_tooltip_text("Copy: run it in a terminal instead")
        copy.connect("clicked", lambda *_: w.copy_to_clipboard(self._preview.get_text()))
        strip.append(copy)
        return strip

    def _can_run(self) -> bool:
        """A target with its own environment needs no list; everything else does."""
        return bool(self._target.fixed_environment or self._catalog.launchable_environments)

    def _form(self) -> Gtk.Widget:
        group = Adw.PreferencesGroup()
        shows_reach = False
        self._book = self._config.runbook_for(self._target.name)

        if self._target.fixed_environment:
            row = Adw.ActionRow(
                title="Environment",
                subtitle=f"{self._target.fixed_environment}: this target names its own",
            )
            row.add_prefix(Gtk.Image.new_from_icon_name("changes-prevent-symbolic"))
            group.add(row)
        else:
            names = [e.name for e in self._catalog.launchable_environments]
            if names:
                combo = Adw.ComboRow(title="Environment", model=Gtk.StringList.new(names))
                combo.set_subtitle("Where this runs")
                combo.connect("notify::selected", lambda *_: self._refresh_preview())
                self._fields["environment"] = combo
                group.add(combo)
                shows_reach = True
            else:
                # No StringList placeholder here: a fake row would be read back as a
                # value and would appear in the command preview as if it were one.
                row = Adw.ActionRow(
                    title="Environment", subtitle="None has been chosen for this console yet"
                )
                row.add_prefix(Gtk.Image.new_from_icon_name("changes-prevent-symbolic"))
                group.add(row)

        for name, param in self._target.params.items():
            group.add(self._param_row(name, param))

        if self._target.dry_run:
            switch = Adw.SwitchRow(
                title="Dry run", subtitle="Adds --check, so Ansible reports without changing"
            )
            switch.connect("notify::active", lambda *_: self._refresh_preview())
            self._fields["dry_run"] = switch
            group.add(switch)

        group.add(self._more())
        for row in self._runbook_rows():
            group.add(row)

        if self._config.confirm_mode(self._target.name) == "type-environment-name":
            group.add(self._confirmation())

        if not shows_reach:
            return group
        # Under the chooser rather than in it: what an environment is made of
        # is a sentence, and a row subtitle is one line.
        holder = w.box(spacing=4)
        holder.append(group)
        self._reach.set_margin_start(14)
        holder.append(self._reach)
        return holder

    def _runbook_rows(self) -> list[Gtk.Widget]:
        """Who owns this, what runs around it, and what it would reach for on failure."""
        book = self._book
        rows: list[Gtk.Widget] = []
        if book.owner or book.reviewed:
            who = Adw.ActionRow(title="Owned by", subtitle=book.owner or "nobody named")
            if book.reviewed:
                who.set_subtitle(f"{book.owner or 'nobody named'} · reviewed {book.reviewed}")
            if book.stale():
                who.add_suffix(w.badge("STALE", "medium"))
            rows.append(who)
        made_of = self._composition()
        if made_of is not None:
            rows.append(made_of)

        leaned = self._config.used_by(self._target.name)
        if leaned:
            rows.append(
                Adw.ActionRow(
                    title=f"{plural(len(leaned), 'runbook')} lean on this one",
                    subtitle=" · ".join(one.sentence for one in leaned[:4]),
                )
            )

        around = [
            f"{kind}: {name}"
            for kind, name in (
                ("checks first", book.precheck),
                ("proves it worked", book.postcheck),
                ("recovery", book.recovery),
            )
            if name
        ]
        if around:
            rows.append(Adw.ActionRow(title="Runs around it", subtitle=" · ".join(around)))
        return rows

    def _composition(self) -> Gtk.Widget | None:
        """What the playbook behind this target pulls in, and what it decides later.

        Ansible already composes; this reads the composition that is in the
        file rather than offering a second way to build one.
        """
        playbook = self._book.playbook or self._target.source
        made_of = composition_module.read(self._repo, playbook)
        if not made_of.known:
            return None
        row = Adw.ExpanderRow(
            title=f"Made of {plural(len(made_of.pieces), 'part')}",
            subtitle=f"from {playbook}",
        )
        for piece in made_of.pieces:
            when = "before the run" if piece.static else "while the run goes"
            inner = Adw.ActionRow(
                title=piece.name + (f" ×{piece.times}" if piece.times > 1 else ""),
                subtitle=f"{piece.kind} · chosen {when}",
            )
            if not piece.static:
                inner.add_suffix(w.badge("RUN TIME", "medium"))
            row.add_row(inner)
        return row

    def _more(self) -> Gtk.Widget:
        """The four options Ansible has and this form never offered.

        Folded away, because the common case is none of them, and open, they
        are four more things to read before a deploy.
        """
        more = Adw.ExpanderRow(
            title="Run options", subtitle="Diff, a host limit, tags, and how much it prints"
        )

        diff = Adw.SwitchRow(
            title="Show the difference",
            subtitle="Adds --diff, so a change is printed rather than counted",
        )
        diff.connect("notify::active", lambda *_: self._refresh_preview())
        self._fields["diff"] = diff
        more.add_row(diff)

        limit = Adw.EntryRow(title="Only these hosts")
        limit.connect("changed", lambda *_: self._refresh_preview())
        self._fields["limit"] = limit
        more.add_row(limit)

        tags = Adw.EntryRow(title="Only these tags")
        tags.connect("changed", lambda *_: self._refresh_preview())
        self._fields["tags"] = tags
        more.add_row(tags)

        loud = Adw.ComboRow(
            title="How much it prints",
            model=Gtk.StringList.new(["Normal", "-v", "-vv", "-vvv", "-vvvv"]),
        )
        loud.connect("notify::selected", lambda *_: self._refresh_preview())
        self._fields["verbosity"] = loud
        more.add_row(loud)
        return more

    def _options(self) -> command_module.Options:
        loud = self._fields.get("verbosity")
        return command_module.Options(
            diff=self._switched("diff"),
            limit=self._typed("limit"),
            tags=self._typed("tags"),
            verbosity=loud.get_selected() if isinstance(loud, Adw.ComboRow) else 0,
        )

    def _switched(self, name: str) -> bool:
        row = self._fields.get(name)
        return bool(isinstance(row, Adw.SwitchRow) and row.get_active())

    def _typed(self, name: str) -> str:
        row = self._fields.get(name)
        return row.get_text().strip() if isinstance(row, Adw.EntryRow) else ""

    def _confirmation(self) -> Gtk.Widget:
        """Typing the environment name is the last gate, so it says which name and why."""
        self._confirm_entry = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=22)
        where = self._environment() or "the environment"
        self._confirm_entry.set_placeholder_text(where)
        row = Adw.ActionRow(
            title="Confirm",
            subtitle=f"Type “{where}” to prove this is the one you meant.",
        )
        row.set_subtitle_lines(2)
        row.add_suffix(self._confirm_entry)
        row.set_activatable_widget(self._confirm_entry)
        self._confirm_row = row
        return row

    def _param_row(self, name: str, param) -> Gtk.Widget:
        """A parameter row that always shows what the value is for.

        The help used to live in a tooltip, which is a place a keyboard never
        reaches and a first-time reader never finds.
        """
        choices = command_module.choices_for(param, self._catalog, self._repo)
        title = _title(name)

        if choices and not param.allow_other:
            explanation = param.help or f"One of {len(choices)} permitted values"
            row = Adw.ComboRow(title=title, model=Gtk.StringList.new(["—", *choices]))
            row.set_subtitle(_subtitle(param.required, explanation))
            row.set_subtitle_lines(3)
            row.connect("notify::selected", lambda *_: self._refresh_preview())
            self._fields[name] = row
            return row

        entry = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=22)
        entry.set_placeholder_text(choices[0] if choices else name)
        if param.secret:
            # Not shown while it is typed, and masked everywhere it is written.
            entry.set_visibility(False)
            entry.set_input_purpose(Gtk.InputPurpose.PASSWORD)
        entry.connect("changed", lambda *_: self._refresh_preview())
        row = Adw.ActionRow(
            title=title,
            subtitle=_subtitle(
                param.required,
                param.help
                or (
                    "Kept out of the preview, the history and the output."
                    if param.secret
                    else "Free text. It is checked before it is used."
                ),
            ),
        )
        row.set_subtitle_lines(3)
        row.add_suffix(entry)
        row.set_activatable_widget(entry)
        self._fields[name] = entry
        return row

    # --- reading the form ---

    # --- what the environment is made of ---

    def _read_inventory(self) -> None:
        """Asks Ansible once per environment, on a thread, and remembers the answer.

        The question is what this will touch, and it is worth answering before the run:
        a deploy that builds on one host and activates on several has never shown which
        builder that is.
        """
        name = self._environment()
        if not name:
            self._reach.set_text("")
            return
        known = self._inventories.get(name)
        if known is not None:
            self._say_reach(known)
            return
        environment = self._catalog.environment(name)
        if environment is None or not environment.inventory:
            self._reach.set_text("")
            return
        self._reach.set_text("Reading the inventory…")
        threading.Thread(
            target=self._ask_inventory,
            args=(name, environment.inventory),
            daemon=True,
            name=f"inventory-{name}",
        ).start()

    def _ask_inventory(self, name: str, path: str) -> None:
        answer = inventory_module.read(self._repo, path)
        GLib.idle_add(self._inventory_read, name, answer)

    def _inventory_read(self, name: str, answer) -> bool:
        self._inventories[name] = answer
        if self._environment() == name:
            self._say_reach(answer)
        return False

    def _say_reach(self, answer) -> None:
        if not answer.known:
            # Not a failure of the run: this console simply could not look.
            self._reach.set_text(answer.error)
            return
        builder = answer.group("builder")
        parts = [f"{plural(len(answer.hosts), 'host')}"]
        if builder is not None and builder.one_host:
            parts.append(f"builds on {builder.one_host}")
        elif builder is not None:
            parts.append(f"builds on {plural(len(builder.hosts), 'host')}")
        named = [g.name for g in answer.groups if g.name != "builder"]
        if named:
            parts.append(", ".join(named[:6]))
        # Predicted, and said so: this is what the inventory holds, not what
        # Ansible will decide to touch once a `when:` has been evaluated. Where
        # the playbook also chooses part of itself at run time, the prediction
        # is weaker still and says which parts.
        said = "Predicted reach: " + " · ".join(parts)
        made_of = composition_module.read(self._repo, self._book.playbook or self._target.source)
        if made_of.caveat:
            said = f"{said}\n{made_of.caveat}"
        self._reach.set_text(said)

    def _environment(self) -> str:
        if self._target.fixed_environment:
            return self._target.fixed_environment
        combo = self._fields.get("environment")
        if not isinstance(combo, Adw.ComboRow):
            return ""
        item = combo.get_selected_item()
        return item.get_string() if item is not None else ""

    def _params(self) -> dict[str, str]:
        values: dict[str, str] = {}
        for name in self._target.params:
            widget = self._fields.get(name)
            if isinstance(widget, Adw.ComboRow):
                item = widget.get_selected_item()
                text = item.get_string() if item is not None else ""
                if text and text != "—":
                    values[name] = text
            elif isinstance(widget, Gtk.Entry):
                text = widget.get_text().strip()
                if text:
                    values[name] = text
        return values

    def _dry_run(self) -> bool:
        return self._switched("dry_run")

    # --- behaviour ---

    def _refresh_preview(self) -> None:
        self._read_inventory()
        environment = self._environment()
        if self._confirm_entry is not None and environment:
            self._confirm_entry.set_placeholder_text(environment)
            self._confirm_row.set_subtitle(
                f"Type “{environment}” to prove this is the one you meant."
            )
        if not environment:
            self._preview.set_text(NOT_YET)
            return
        try:
            built = command_module.for_target(
                target=self._target,
                environment=environment,
                params=self._params(),
                config=self._config,
                dry_run=self._dry_run(),
                catalog=self._catalog,
                options=self._options(),
            )
            # The declared settings are shown as the assignments they are, so
            # what the preview says is what a person could paste at a prompt.
            declared = self._config.ansible.display
            shown = f"{declared} {built.safe_display}" if declared else built.safe_display
            self._preview.set_text(shown)
        except command_module.ValidationError:
            self._preview.set_text(NOT_YET)

    def _fail(self, message: str) -> None:
        self._error.set_title(message)
        self._error.set_revealed(True)

    def _on_run_clicked(self, _button) -> None:
        self._error.set_revealed(False)
        environment = self._environment()

        if self._confirm_entry is not None:
            typed = self._confirm_entry.get_text().strip()
            if typed != environment:
                self._fail(f"Type “{environment}” to confirm this run.")
                return
        try:
            environment = command_module.validate_environment(self._catalog, environment)
            params = command_module.validate_params(
                self._target, self._params(), self._catalog, self._repo
            )
        except command_module.ValidationError as exc:
            self._fail(str(exc))
            return

        try:
            options = self._options().validated()
        except command_module.ValidationError as exc:
            self._fail(str(exc))
            return
        launch, target, dry_run = self._on_launch, self._target, self._dry_run()
        self.close()
        # The window changes page as soon as the run starts, and doing that
        # inside the click handler moves focus out of a dialog that is still
        # being taken apart. One turn of the loop is enough for it to finish.
        GLib.idle_add(lambda: bool(launch(target, environment, params, dry_run, options)) and False)


def _subtitle(required: bool, explanation: str) -> str:
    """`Required: the built release to cut over to`, or just the explanation."""
    return f"Required: {explanation}" if required else explanation


def _title(name: str) -> str:
    """`release` reads as Release name; the identifier is in the command below."""
    return name.replace("_", " ").replace("-", " ").capitalize()
