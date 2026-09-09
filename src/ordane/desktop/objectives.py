"""Setting up the service objectives, which until now could only be typed by hand.

An objective the console cannot measure is not a bug in the objective: it is
one that has named a source nothing supplies. So this says, for each kind, what
would fill it, and refuses to let one be declared measurable when the thing
that measures it is not there.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import edit  # noqa: E402
from ..core.config import CONFIG_NAME, ConfigError  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402

# What each kind is computed from, and therefore what it needs to exist.
KINDS = (
    (
        "cutover_success",
        "Cutovers that finished without a rollback",
        "Counted from runs this console recorded against the environments below, "
        "on targets marked `cutover: true`.",
    ),
    (
        "cutover_duration",
        "Cutovers that finished inside a time limit",
        "The same runs, measured against the limit in seconds.",
    ),
    (
        "",
        "Something this console cannot measure",
        "Declared, with a sentence saying what it would take. It says what it is short "
        "of rather than a number, which is the honest state for an objective with no "
        "source.",
    ),
)

WINDOWS = ("7d", "28d", "90d", "180d", "365d")


class ObjectivesDialog(Adw.Dialog):
    """Every objective, editable, written back as the whole `slos:` block."""

    def __init__(self, *, config, catalog, repo: Path, on_saved) -> None:
        super().__init__(title="Service objectives", content_width=680)
        self._repo = repo
        self._catalog = catalog
        self._on_saved = on_saved
        self._rows: list[ObjectiveRow] = []

        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")
        self._group = Adw.PreferencesGroup()
        self.set_child(self._build(config))
        for spec in config.slos:
            self._add(spec)
        if not config.slos:
            self._add({})

    def _build(self, config) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label="Save")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(16)
        body.append(self._error)
        body.append(
            w.label(
                "An objective is a target this estate holds itself to. What the console "
                f"can measure it from is written in {CONFIG_NAME}, and this is that file.",
                "tint-muted",
                wrap=True,
            )
        )
        body.append(self._group)

        add = Gtk.Button(label="Add an objective")
        add.set_halign(Gtk.Align.START)
        add.connect("clicked", lambda *_: self._add({}))
        body.append(add)

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _add(self, spec: dict) -> None:
        row = ObjectiveRow(spec, self._catalog, self._remove)
        self._rows.append(row)
        self._group.add(row)

    def _remove(self, row) -> None:
        self._rows.remove(row)
        self._group.remove(row)

    def _on_save(self, _button) -> None:
        self._error.set_revealed(False)
        entries = []
        for row in self._rows:
            entry = row.value()
            if entry is None:
                self._error.set_title("Every objective needs a label.")
                self._error.set_revealed(True)
                return
            entries.append(entry)
        try:
            edit.write_slos(self._repo, entries)
        except (ConfigError, OSError) as exc:
            self._error.set_title(str(exc))
            self._error.set_revealed(True)
            return
        self.close()
        self._on_saved(len(entries))


class ObjectiveRow(Adw.ExpanderRow):
    """One objective: what it is called, what it is measured from, and its target."""

    def __init__(self, spec: dict, catalog, on_remove) -> None:
        super().__init__()
        self._catalog = catalog
        kind = str(spec.get("kind", "") or "")

        self._label = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=26)
        self._label.set_text(str(spec.get("label", "") or ""))
        self._label.set_placeholder_text("Cutover succeeds without rollback")
        self._label.connect("changed", lambda *_: self._retitle())
        label_row = Adw.ActionRow(title="Name")
        label_row.add_suffix(self._label)
        self.add_row(label_row)

        self._kind = Adw.ComboRow(
            title="Measured from", model=Gtk.StringList.new([name for _, name, _ in KINDS])
        )
        self._kind.set_selected(next(i for i, (k, _, _) in enumerate(KINDS) if k == kind))
        self._kind.set_subtitle_lines(3)
        self._kind.connect("notify::selected", lambda *_: self._explain())
        self.add_row(self._kind)

        self._target = _entry(spec.get("target", "95%"), "95%")
        self.add_row(_row("Target", "The share that has to meet it.", self._target))

        self._window = Adw.ComboRow(title="Over", model=Gtk.StringList.new(list(WINDOWS)))
        window = str(spec.get("window", "90d") or "90d")
        if window in WINDOWS:
            self._window.set_selected(WINDOWS.index(window))
        self.add_row(self._window)

        self._limit = _entry(spec.get("limit_seconds", ""), "2700")
        self.add_row(_row("Within, in seconds", "For a duration objective only.", self._limit))

        names = [e.name for e in catalog.environments if not e.synthetic]
        self._environments = _entry(
            ", ".join(str(e) for e in spec.get("environments", []) or []),
            ", ".join(names[:1]) or "production",
        )
        self.add_row(
            _row(
                "Environments",
                "Only runs against these count. Without this, a run against a throwaway "
                "fleet would move a service number.",
                self._environments,
            )
        )

        self._blocked = _entry(spec.get("blocked", ""), "needs a synthetic probe")
        self.add_row(
            _row(
                "What it would take",
                "Shown when there is nothing to measure it from.",
                self._blocked,
            )
        )

        remove = Gtk.Button(icon_name="user-trash-symbolic", valign=Gtk.Align.CENTER)
        remove.add_css_class("flat")
        remove.set_tooltip_text("Remove this objective")
        remove.connect("clicked", lambda *_: on_remove(self))
        self.add_suffix(remove)

        self._retitle()
        self._explain()

    def _retitle(self) -> None:
        self.set_title(self._label.get_text().strip() or "A new objective")

    def _explain(self) -> None:
        _, _, meaning = KINDS[self._kind.get_selected()]
        self._kind.set_subtitle(meaning)
        measurable = KINDS[self._kind.get_selected()][0] != ""
        self.set_subtitle(
            "" if measurable else "Says what it is short of until something measures it"
        )

    def value(self) -> dict | None:
        label = self._label.get_text().strip()
        if not label:
            return None
        kind = KINDS[self._kind.get_selected()][0]
        entry: dict = {"label": label}
        if kind:
            entry["kind"] = kind
        entry["target"] = self._target.get_text().strip() or "95%"
        item = self._window.get_selected_item()
        entry["window"] = item.get_string() if item is not None else "90d"
        if kind == "cutover_duration" and self._limit.get_text().strip():
            entry["limit_seconds"] = _number(self._limit.get_text())
        scope = [part.strip() for part in self._environments.get_text().split(",") if part.strip()]
        if scope:
            entry["environments"] = scope
        blocked = self._blocked.get_text().strip()
        if not kind and blocked:
            entry["blocked"] = blocked
        return entry


def _entry(value, placeholder: str) -> Gtk.Entry:
    entry = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=22)
    entry.set_text("" if value in (None, "") else str(value))
    entry.set_placeholder_text(placeholder)
    return entry


def _row(title: str, subtitle: str, entry: Gtk.Entry) -> Adw.ActionRow:
    row = Adw.ActionRow(title=title, subtitle=subtitle)
    row.set_subtitle_lines(3)
    row.add_suffix(entry)
    row.set_activatable_widget(entry)
    return row


def _number(text: str) -> int:
    try:
        return int(float(text))
    except ValueError:
        return 0


def saved_message(count: int) -> str:
    return f"{plural(count, 'objective')} written"
