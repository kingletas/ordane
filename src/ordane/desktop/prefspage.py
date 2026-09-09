"""Preferences: a place rather than a dialog, and every row is wired to something.

Nothing here is stored and never read. A switch that looks like a setting and
changes nothing is worse than no switch at all, so what this console cannot yet
do is not offered — it is named in the note at the foot, where a person can see
that it is missing rather than that it is broken.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from . import geometry  # noqa: E402
from . import widgets as w  # noqa: E402
from .shortcuts import KEYS  # noqa: E402

NOT_YET = (
    "Confirming before a change, stopping a run at the first failed host, and pruning "
    "old history are not settings yet, because none of the three is built. They are "
    "listed here rather than shown as switches that would do nothing."
)


class PrefsPage(Gtk.Box):
    """Four groups, drawn once. Every control applies as it is changed."""

    def __init__(self, *, state_dir, on_theme, on_density, on_switch, on_navigation) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._state_dir = state_dir
        self._on_theme = on_theme
        self._on_density = on_density
        self._on_switch = on_switch
        self._on_navigation = on_navigation
        self._body = w.box(spacing=26)
        self.append(w.scrolled(w.clamp(self._body, maximum=720)))
        self._built = False

    def render(self) -> None:
        if self._built:
            return
        self._built = True

        self._body.append(
            _group(
                "Starting up",
                [
                    self._switch(
                        "reread-on-focus",
                        "Re-read the repository when this window is focused",
                        "Picks up commits you made in an editor without pressing anything.",
                    ),
                    self._switch(
                        "reopen-last",
                        "Reopen the last repository",
                        "Otherwise `ordane` with no argument prints the ones it "
                        "remembers and stops.",
                    ),
                ],
            )
        )

        self._body.append(
            _group(
                "Appearance",
                [
                    self._theme(),
                    self._density(),
                    self._switch(
                        "reduce-motion",
                        "Reduce motion",
                        "Turns off the lead-time line drawing itself in and the live "
                        "run's cells filling.",
                    ),
                ],
            )
        )

        self._body.append(
            _group(
                "Where things live",
                [self._navigation()],
                note="A narrow window folds the rail away and keeps the menu whatever "
                "is chosen here, because places with nowhere to be reached is not a "
                "preference.",
            )
        )

        self._body.append(
            _group(
                "Keyboard",
                [
                    _row(
                        "Shortcuts",
                        f"{len(KEYS)} keys, and everything else is on Ctrl+K.",
                        w.button("Show all shortcuts", "quiet", small=True, action="win.shortcuts"),
                    )
                ],
            )
        )

        self._body.append(w.label(NOT_YET, "actrow-note", wrap=True))

    # --- the rows ---

    def _switch(self, key: str, name: str, note: str) -> Gtk.Widget:
        toggle = Gtk.Switch(valign=Gtk.Align.CENTER)
        toggle.set_active(geometry.switch(self._state_dir, key))
        toggle.connect("state-set", lambda _s, on, one=key: self._flip(one, on))
        return _row(name, note, toggle)

    def _flip(self, key: str, on: bool) -> bool:
        geometry.save_switch(self._state_dir, key, on)
        self._on_switch(key, on)
        return False

    def _theme(self) -> Gtk.Widget:
        chosen = geometry.theme(self._state_dir)
        swatches = w.row(7)
        swatches.set_valign(Gtk.Align.CENTER)
        for key, name, meaning in geometry.THEMES:
            button = Gtk.Button()
            button.add_css_class("swatch")
            button.add_css_class(f"swatch-{key}")
            if key == chosen:
                button.add_css_class("chosen")
            button.set_tooltip_text(f"{name}: {meaning}")
            button.connect(
                "clicked", lambda _b, one=key, all_of=swatches: self._pick_theme(one, all_of)
            )
            swatches.append(button)
        return _row("Theme", "Follows the system by default.", swatches)

    def _pick_theme(self, key: str, swatches: Gtk.Widget) -> None:
        geometry.save_theme(self._state_dir, key)
        self._on_theme(key)
        child = swatches.get_first_child()
        for one, _name, _meaning in geometry.THEMES:
            if child is None:
                break
            child.remove_css_class("chosen")
            if one == key:
                child.add_css_class("chosen")
            child = child.get_next_sibling()

    def _density(self) -> Gtk.Widget:
        chosen = geometry.density(self._state_dir)
        seg = w.row(2)
        seg.add_css_class("seg")
        seg.set_size_request(210, -1)
        seg.set_valign(Gtk.Align.CENTER)
        for key, name, _meaning in geometry.DENSITIES:
            button = Gtk.Button(label=name, hexpand=True)
            button.add_css_class("flat")
            if key == chosen:
                button.add_css_class("chosen")
            button.connect(
                "clicked", lambda _b, one=key, all_of=seg: self._pick_density(one, all_of)
            )
            seg.append(button)
        return _row(
            "Density",
            "Comfortable gives rows more air; compact fits more hosts on screen.",
            seg,
        )

    def _pick_density(self, key: str, seg: Gtk.Widget) -> None:
        geometry.save_density(self._state_dir, key)
        self._on_density(key)
        child = seg.get_first_child()
        for one, _name, _meaning in geometry.DENSITIES:
            if child is None:
                break
            child.remove_css_class("chosen")
            if one == key:
                child.add_css_class("chosen")
            child = child.get_next_sibling()

    def _navigation(self) -> Gtk.Widget:
        chosen = geometry.navigation(self._state_dir)
        seg = w.row(2)
        seg.add_css_class("seg")
        seg.set_size_request(260, -1)
        seg.set_valign(Gtk.Align.CENTER)
        for key, name, meaning in geometry.NAVIGATION:
            button = Gtk.Button(label=name, hexpand=True)
            button.add_css_class("flat")
            button.set_tooltip_text(meaning)
            if key == chosen:
                button.add_css_class("chosen")
            button.connect(
                "clicked", lambda _b, one=key, all_of=seg: self._pick_navigation(one, all_of)
            )
            seg.append(button)
        return _row("The rail and the menu", "Keep either, or both.", seg)

    def _pick_navigation(self, key: str, seg: Gtk.Widget) -> None:
        self._on_navigation(key)
        child = seg.get_first_child()
        for one, _name, _meaning in geometry.NAVIGATION:
            if child is None:
                break
            child.remove_css_class("chosen")
            if one == key:
                child.add_css_class("chosen")
            child = child.get_next_sibling()


def _group(title: str, rows: list[Gtk.Widget], note: str = "") -> Gtk.Widget:
    holder = w.box(spacing=9)
    holder.append(w.label(title, "prefgroup-title"))
    card = w.card()
    for index, one in enumerate(rows):
        if index == len(rows) - 1:
            one.add_css_class("last")
        card.append(one)
    holder.append(card)
    if note:
        holder.append(w.label(note, "actrow-note", wrap=True))
    return holder


def _row(name: str, note: str, control: Gtk.Widget) -> Gtk.Widget:
    line = w.row(16)
    line.add_css_class("prefrow")
    text = w.box(spacing=1, hexpand=True)
    text.set_valign(Gtk.Align.CENTER)
    text.append(w.label(name, "pref-name", wrap=True))
    text.append(w.label(note, "pref-note", wrap=True))
    line.append(text)
    control.set_valign(Gtk.Align.CENTER)
    line.append(control)
    return line
