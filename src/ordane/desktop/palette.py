"""Ctrl+K: everything this console can do, in one list you can type into.

An operator tool needs a command surface. Without one, every verb has to be
hunted for in a menu, which is why the rail had grown into a list of dialogs.

Each of the nine entries the rail used to carry is here, under `This
repository`, alongside the places and every action that can be launched.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402
from .glyphs import Glyph  # noqa: E402

RUN = "Run"
REPOSITORY = "This repository"
SWITCH = "Switch"
GO = "Go to"
GROUPS = (RUN, REPOSITORY, SWITCH, GO)

# How many entries the list draws. Past this a person is typing, not scrolling.
SHOWN = 40

# How many runnable actions the list offers before anything is typed. Every one
# of them is still reachable — by typing its name — and a palette whose first
# group fills the whole panel hides the other three.
RUN_SHOWN = 3

WIDTH = 560


@dataclass(frozen=True)
class Entry:
    """One thing the console can be asked to do."""

    group: str
    title: str
    run: object
    key: str = ""
    icon: str = ""
    glyph: str = ""
    terms: str = ""

    def matches(self, needle: str) -> bool:
        if not needle:
            return True
        haystack = f"{self.title} {self.terms} {self.group}".lower()
        return all(word in haystack for word in needle.lower().split())


@dataclass
class Palette:
    """Not a widget: the list of entries, so a test can read it without a window."""

    entries: list[Entry] = field(default_factory=list)

    def ranked(self, needle: str) -> list[Entry]:
        kept = [entry for entry in self.entries if entry.matches(needle)]
        if not needle:
            runnable = [entry for entry in kept if entry.group == RUN][:RUN_SHOWN]
            kept = runnable + [entry for entry in kept if entry.group != RUN]
        return kept[:SHOWN]


class PaletteDialog(Adw.Dialog):
    """The palette itself: type, arrow, enter."""

    def __init__(self, entries: list[Entry], on_run) -> None:
        super().__init__(content_width=WIDTH)
        self.add_css_class("palette")
        self.set_presentation_mode(Adw.DialogPresentationMode.FLOATING)
        self._palette = Palette(entries)
        self._on_run = on_run
        self._rows: list[tuple[Entry, Gtk.Widget]] = []
        self._at = 0

        body = w.box(spacing=0)
        self._entry = Gtk.SearchEntry(
            placeholder_text="Go somewhere, run an action, or change the repository"
        )
        self._entry.add_css_class("palette-entry")
        self._entry.connect("search-changed", lambda *_: self._fill())
        self._entry.connect("activate", lambda *_: self._activate())
        body.append(self._entry)

        self._list = w.box(spacing=0)
        scroller = Gtk.ScrolledWindow(
            child=self._list,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=560,
        )
        body.append(scroller)

        foot = w.row(16)
        foot.add_css_class("pfoot")
        for hint in ("↑↓ to move", "↵ to run", "Esc to close"):
            foot.append(w.label(hint))
        body.append(foot)
        self.set_child(body)

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._on_key)
        self.add_controller(keys)
        self._fill()

    # --- what it draws ---

    def _fill(self) -> None:
        w.clear(self._list)
        self._rows = []
        needle = self._entry.get_text().strip()
        found = self._palette.ranked(needle)
        if not found:
            nothing = w.label(f"Nothing here is called “{needle}”", "pgroup-title")
            nothing.set_margin_top(12)
            nothing.set_margin_bottom(12)
            self._list.append(nothing)
            return
        for group in GROUPS:
            inside = [entry for entry in found if entry.group == group]
            if not inside:
                continue
            self._list.append(w.label(group, "pgroup-title"))
            for entry in inside:
                widget = self._row(entry)
                self._list.append(widget)
                self._rows.append((entry, widget))
        self._at = 0
        self._highlight()

    def _row(self, entry: Entry) -> Gtk.Widget:
        line = w.row(11)
        line.add_css_class("pitem")
        if entry.glyph:
            line.append(Glyph(entry.glyph))
        elif entry.icon:
            line.append(Gtk.Image.new_from_icon_name(entry.icon))
        title = w.label(entry.title)
        title.set_hexpand(True)
        title.set_ellipsize(3)
        line.append(title)
        if entry.key:
            line.append(w.label(entry.key, "pitem-key", "mono"))

        click = Gtk.GestureClick()
        click.connect("released", lambda *_, one=entry: self._run(one))
        line.add_controller(click)
        return line

    def _highlight(self) -> None:
        for index, (_entry, widget) in enumerate(self._rows):
            if index == self._at:
                widget.add_css_class("on")
            else:
                widget.remove_css_class("on")

    # --- what it does ---

    def _on_key(self, _controller, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Down:
            self._step(1)
            return True
        if keyval == Gdk.KEY_Up:
            self._step(-1)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            self._activate()
            return True
        return False

    def _step(self, by: int) -> None:
        if not self._rows:
            return
        self._at = (self._at + by) % len(self._rows)
        self._highlight()

    def _activate(self) -> None:
        if self._rows:
            self._run(self._rows[self._at][0])

    def _run(self, entry: Entry) -> None:
        # Closed first: an entry that opens a dialog would otherwise open it
        # behind this one, and there is nothing to say the palette is still up.
        self.close()
        self._on_run(entry)
