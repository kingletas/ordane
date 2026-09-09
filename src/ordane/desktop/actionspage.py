"""Actions: what this repository defines, and the composer that launches one.

The list on the left is what `make help` or the playbooks said, with the
environments each action can reach. The composer on the right shows the
confirmation sentence above a button that names its own outcome — nothing
happens until it is pressed, and it says what it will do.

The full launch form, with a repository's own parameters, choice lists and dry
run, is still the launch dialog: the composer is the short way to the two
things every run needs, and `Set it up in full…` is the way to the rest.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import exposure, search  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402

COMPOSER_WIDTH = 360

# How much of a description a row asks for before it ellipsises.
NOTE_CHARS = 64

# The column of action names is measured from the names actually in it, within
# these bounds. A fixed width takes room the descriptions need and gives it to
# whitespace beside three short names.
NAME_CHARS = 20
NAME_MIN_CHARS = 7

# How many actions the composer offers as a segmented row before it becomes a
# list somebody scrolls. Past this the left-hand list is the way in.
SEGMENTED = 4


class ActionsPage(Gtk.Box):
    """The catalogue and the composer, side by side."""

    def __init__(self, *, on_launch, on_open_full, on_search) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self._on_launch = on_launch
        self._on_open_full = on_open_full
        self._on_search = on_search
        self._action = ""
        self._environment = ""
        self._preview = False
        self._catalog = None
        self._config = None
        self._hosts: dict[str, tuple[str, ...]] = {}
        self._reach: dict[str, str] = {}
        self._same_reach = True
        self._name_chars = NAME_MIN_CHARS
        self._signature: tuple | None = None

        self._left = w.box(spacing=12, hexpand=True)
        self.append(self._left)
        # Clamped rather than merely sized: a natural width larger than this
        # takes room from the list beside it, which then ellipsises every
        # description it holds.
        self._composer = w.box(spacing=0)
        self._composer.set_size_request(COMPOSER_WIDTH, -1)
        self.append(Adw.Clamp(maximum_size=COMPOSER_WIDTH, child=self._composer))

    def render(self, *, catalog, config, needle: str, hosts, group: str = "") -> None:
        signature = (
            tuple((t.name, t.danger, t.group) for t in catalog.targets),
            tuple((e.name, e.usable, e.allowed) for e in catalog.environments),
            needle,
            self._action,
            self._environment,
            self._preview,
            group,
            tuple(sorted((k, len(v)) for k, v in hosts.items())),
        )
        if signature == self._signature:
            return
        self._signature = signature
        self._catalog = catalog
        self._config = config
        self._hosts = hosts
        self._draw_list(catalog, config, needle, group)
        self._draw_composer(catalog)

    # --- the catalogue ---

    def _draw_list(self, catalog, config, needle: str, group: str) -> None:
        w.clear(self._left)
        # Which environments each action can reach, and whether that says
        # anything. On a control plane where every action reaches every
        # environment, a column repeating the same four names on all
        # thirty-seven rows is noise wearing the shape of information — and it
        # takes the room the descriptions need. Print only what deviates.
        self._reach = {one.name: _reach_of(one, catalog) for one in catalog.targets}
        self._same_reach = len(set(self._reach.values())) < 2
        matches = search.rank(catalog.targets, needle)
        if needle and not matches:
            self._left.append(
                w.empty(
                    f"Nothing here is called “{needle}”",
                    "The search covers an action's name and the description beside it.",
                    "system-search-symbolic",
                )
            )
            return

        if needle:
            self._left.append(
                w.band(f"{plural(len(matches), 'match')} for “{needle}”", "best match first")
            )
            self._fit_names(m.target.name for m in matches)
            card = w.card()
            card.set_hexpand(True)
            for index, match in enumerate(matches):
                card.append(
                    self._action_row(
                        match.target,
                        catalog,
                        detail=f"{match.target.description} · {match.reason}",
                        last=index == len(matches) - 1,
                    )
                )
            self._left.append(card)
            return

        source = catalog.discovery.target_source if catalog.discovery else "the repository"
        self._left.append(w.band("Defined in", self._where_from(source, catalog)))
        grouped: dict[str, list] = {}
        for match in matches:
            grouped.setdefault(match.target.group, []).append(match.target)
        names = config.sort_groups(grouped)
        chosen = group if group in names else (names[0] if names else "")

        if len(names) > 1:
            self._left.append(_group_bar(names, grouped, chosen, self._on_search))
        targets = grouped.get(chosen, [])
        self._fit_names(t.name for t in targets)
        card = w.card()
        card.set_hexpand(True)
        for index, target in enumerate(targets):
            card.append(self._action_row(target, catalog, last=index == len(targets) - 1))
        self._left.append(card)

        hidden = len(catalog.targets) - sum(len(v) for v in grouped.values())
        if hidden > 0:
            self._left.append(
                w.label(
                    f"{plural(hidden, 'action')} are defined and hidden by this "
                    "repository's own configuration.",
                    "actrow-note",
                    wrap=True,
                )
            )

    def _where_from(self, source: str, catalog) -> str:
        """The band's own line: where the actions came from, and what they reach."""
        said = source.replace("`", "")
        reach = next(iter(set(self._reach.values())), "")
        if self._same_reach and reach:
            said = f"{said} · every one reaches {reach}"
        return said

    def _fit_names(self, names) -> None:
        """Size the name column to the names in it, within its bounds."""
        longest = max((len(one) for one in names), default=0)
        self._name_chars = max(min(longest, NAME_CHARS), NAME_MIN_CHARS)

    def _action_row(self, target, catalog, detail: str = "", last: bool = False) -> Gtk.Widget:
        line = w.row(14)
        line.add_css_class("actionrow")
        if last:
            line.add_css_class("last")

        name = w.label(target.name, "action-name", "mono")
        name.set_width_chars(self._name_chars)
        name.set_max_width_chars(self._name_chars)
        name.set_xalign(0.0)
        name.set_ellipsize(3)
        if len(target.name) > self._name_chars:
            name.set_tooltip_text(target.name)
        line.append(name)

        # One line that ellipsises. A wrapping label takes two full lines as its
        # minimum, which pushed the page's own minimum past any window it opened
        # in; the whole description is the row's tooltip instead.
        said = detail or target.description
        note = w.label(said, "action-note")
        note.set_hexpand(True)
        note.set_ellipsize(3)
        note.set_max_width_chars(NOTE_CHARS)
        line.append(note)

        chip = w.danger_chip(target.danger)
        if chip is not None:
            line.append(chip)
        book = self._config.runbook_for(target.name) if self._config else None
        if book is not None and book.stale():
            stale = w.badge("Stale runbook", "medium")
            stale.set_tooltip_text(
                f"Last reviewed {book.reviewed}. Nobody has looked at this runbook in a year."
            )
            line.append(stale)

        # Only where this action reaches somewhere different from the rest.
        if not self._same_reach:
            tags = w.row(5)
            tags.set_valign(Gtk.Align.CENTER)
            for environment in catalog.environments:
                if target.fixed_environment and environment.name != target.fixed_environment:
                    continue
                chip = w.tag(
                    environment.name, off=not environment.allowed or not environment.usable
                )
                chip.set_tooltip_text(
                    f"{target.name} can run against {environment.name}"
                    if environment.allowed and environment.usable
                    else f"{environment.name} cannot be launched against yet"
                )
                tags.append(chip)
            line.append(tags)

        button = Gtk.Button(child=line)
        button.add_css_class("flat")
        button.add_css_class("actionrow")
        if last:
            button.add_css_class("last")
        line.remove_css_class("actionrow")
        line.remove_css_class("last")
        button.set_tooltip_text(f"{target.name}: {said}")
        button.connect("clicked", lambda *_, one=target: self._choose_action(one.name))
        w.attach_context_menu(
            button,
            [
                (f"Set up {target.name} in full…", lambda one=target: self._on_open_full(one)),
                (
                    "Copy the command",
                    lambda one=target: w.copy_to_clipboard(f"make {one.name}"),
                ),
            ],
        )
        return button

    # --- the composer ---

    def _draw_composer(self, catalog) -> None:
        w.clear(self._composer)
        launchable = catalog.launchable_environments
        card = w.card(spacing=0)
        card.add_css_class("composer")
        card.append(w.label("Run an action", "composer-title"))
        card.append(
            w.label(
                "Nothing happens until you press the button, and the button says what it will do.",
                "actrow-note",
                wrap=True,
            )
        )

        if not launchable:
            card.append(_read_only())
            self._composer.append(card)
            return

        names = [target.name for target in catalog.targets]
        if self._action not in names:
            self._action = names[0] if names else ""
        allowed = [environment.name for environment in launchable]
        if self._environment not in allowed:
            self._environment = allowed[0]

        card.append(
            _field(
                "Action",
                _chooser(names, self._action, self._choose_action, ceiling=SEGMENTED),
            )
        )
        card.append(
            _field(
                "Environment",
                _chooser(
                    allowed,
                    self._environment,
                    self._choose_environment,
                    ceiling=SEGMENTED,
                    disabled=[one.name for one in catalog.environments if one not in launchable],
                ),
            )
        )

        hosts = self._hosts.get(self._environment, ())
        if hosts:
            card.append(
                _field(
                    f"Hosts — all {len(hosts)} in {self._environment}",
                    _host_list(hosts),
                )
            )

        target = catalog.target(self._action)
        if target is not None and target.dry_run:
            card.append(
                _field(
                    "Mode",
                    _chooser(
                        ["Apply changes", "Preview only"],
                        "Preview only" if self._preview else "Apply changes",
                        self._choose_mode,
                        ceiling=2,
                    ),
                )
            )

        card.append(_willdo(target, self._environment, hosts, self._preview))
        # An action that insists on a value cannot run from one button, so the
        # button says what it will actually do: open the form.
        if _needs_filling(target):
            go = w.button(
                f"Fill in {self._action}…",
                "go",
                lambda: self._on_open_full(catalog.target(self._action)),
            )
        else:
            # Red where the run is aimed at production, whatever the action is.
            level = exposure.level_for(
                self._environment, target.danger if target is not None else "low"
            )
            go = w.button(
                f"Run {self._action} on {self._environment}",
                "danger" if level == "high" and not self._preview else "go",
                lambda: self._on_launch(self._action, self._environment, self._preview),
            )
        go.set_hexpand(True)
        card.append(go)

        if not _needs_filling(target):
            full = w.linkish(
                "Set it up in full…",
                lambda: self._on_open_full(catalog.target(self._action)),
            )
            full.set_halign(Gtk.Align.CENTER)
            full.set_margin_top(6)
            full.set_tooltip_text("Parameters, choice lists, and everything this action declares")
            card.append(full)
        self._composer.append(card)

    def _choose_action(self, name: str) -> None:
        self._action = name
        self._signature = None
        if self._catalog is not None:
            self._draw_composer(self._catalog)

    def _choose_environment(self, name: str) -> None:
        self._environment = name
        self._signature = None
        if self._catalog is not None:
            self._draw_composer(self._catalog)

    def _choose_mode(self, name: str) -> None:
        self._preview = name == "Preview only"
        self._signature = None
        if self._catalog is not None:
            self._draw_composer(self._catalog)


def _field(name: str, control: Gtk.Widget) -> Gtk.Widget:
    holder = w.box(spacing=5)
    holder.set_margin_top(13)
    holder.append(w.label(name, "field-label"))
    holder.append(control)
    return holder


def _chooser(names, chosen: str, on_choose, ceiling: int, disabled=None) -> Gtk.Widget:
    """A segmented row while the choices fit; a dropdown once they do not."""
    off = set(disabled or [])
    if len(names) <= ceiling:
        seg = w.row(2)
        seg.add_css_class("seg")
        for name in names:
            button = Gtk.Button(label=name, hexpand=True)
            button.add_css_class("flat")
            if name == chosen:
                button.add_css_class("chosen")
            if name in off:
                button.set_sensitive(False)
                button.set_tooltip_text(f"{name} cannot be launched against yet")
            button.connect("clicked", lambda _b, one=name: on_choose(one))
            seg.append(button)
        return seg

    model = Gtk.StringList()
    for name in names:
        model.append(name)
    drop = Gtk.DropDown(model=model)
    drop.set_selected(names.index(chosen) if chosen in names else 0)
    drop.connect(
        "notify::selected",
        lambda d, _p: on_choose(names[d.get_selected()]) if d.get_selected() >= 0 else None,
    )
    return drop


def _host_list(hosts) -> Gtk.Widget:
    """Which hosts this will reach, read from the inventory rather than guessed."""
    holder = w.box(spacing=2)
    for host in hosts[:6]:
        holder.append(w.label(host, "actrow-note", "mono"))
    if len(hosts) > 6:
        holder.append(w.label(f"and {len(hosts) - 6} more", "actrow-note"))
    return holder


def _needs_filling(target) -> bool:
    """True when this action insists on a value nobody has been asked for yet."""
    if target is None:
        return False
    return any(getattr(one, "required", False) for one in target.params.values())


def _wanted(target) -> str:
    return ", ".join(name for name, one in target.params.items() if getattr(one, "required", False))


def _willdo(target, environment: str, hosts, preview: bool) -> Gtk.Widget:
    """The confirmation sentence, above the button rather than after it."""
    reach = f"{plural(len(hosts), 'host')} in " if hosts else ""
    what = target.name if target is not None else "this action"
    if _needs_filling(target):
        return _willdo_label(
            f"{what} needs {_wanted(target)} before it can run on {environment}.", "low"
        )

    declared = target.danger if target is not None else "low"
    consequence = "This action makes no changes."
    if preview:
        consequence = "Preview only: it reports what it would change and changes nothing."
    elif declared == "high":
        consequence = "This changes what customers see."
    elif declared == "medium":
        consequence = "This changes something on the hosts it reaches."

    # Where the run is aimed says more than what it is called: the same action
    # is a keystroke against docker and a keystroke against a live store.
    warned = "" if preview else exposure.clause(environment)
    level = "low" if preview else exposure.level_for(environment, declared)
    aimed = f"Will run {what} on {reach}{environment}"
    return _willdo_label(
        f"{aimed} — {warned}. {consequence}" if warned else f"{aimed}. {consequence}", level
    )


def _willdo_label(text: str, level: str) -> Gtk.Widget:
    said = w.label(text, wrap=True)
    said.add_css_class("willdo")
    if level != "low":
        said.add_css_class(f"willdo-{level}")
    said.set_margin_top(14)
    said.set_margin_bottom(12)
    return said


def _read_only() -> Gtk.Widget:
    holder = w.box(spacing=10)
    holder.set_margin_top(14)
    holder.append(
        w.label(
            "No environment has been named, so nothing can be launched. Nothing is "
            "chosen for you, because that is a decision about production.",
            "actrow-note",
            wrap=True,
        )
    )
    button = w.button("Manage environments", "primary", action="win.environments")
    button.set_halign(Gtk.Align.START)
    holder.append(button)
    return holder


def _reach_of(target, catalog) -> str:
    """The environments one action can be launched against, as one comparable string."""
    if target.fixed_environment:
        return target.fixed_environment
    return ", ".join(sorted(one.name for one in catalog.environments))


def _group_bar(names, grouped, chosen: str, on_group) -> Gtk.Widget:
    """One group at a time: eleven actions scroll, forty do not."""
    seg = w.row(2)
    seg.add_css_class("seg")
    for name in names:
        button = Gtk.Button(label=f"{name} {len(grouped[name])}", hexpand=True)
        button.add_css_class("flat")
        if name == chosen:
            button.add_css_class("chosen")
        button.set_tooltip_text(f"{plural(len(grouped[name]), 'action')} in {name}")
        button.connect("clicked", lambda _b, one=name: on_group(one))
        seg.append(button)
    return seg
