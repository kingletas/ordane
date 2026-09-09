"""The navigation rail: places only, and the repository at the foot of it.

What used to be here was a File menu wearing a sidebar's clothes — fourteen
rows, nine of them ending in `…` because they opened dialogs — while the real
navigation sat in the title bar. Two navigation systems, neither complete.

The rows below are places. Everything that used to be here and is not a place
is a method on the repository, and lives in two places instead: the menu on the
repository card, and the command palette.
"""

from __future__ import annotations

from dataclasses import dataclass

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..core.config import CONFIG_NAME  # noqa: E402
from . import widgets as w  # noqa: E402
from .glyphs import Glyph  # noqa: E402
from .shortcuts import for_action  # noqa: E402

WIDTH = 236

OVERVIEW = "overview"
ACTIONS = "actions"
RUNS = "runs"
ENVIRONMENTS = "environments"
ESTATE = "estate"
DELIVERY = "delivery"

# The places, and the divider that separates what you do from what is managed.
SEPARATOR = "—"
PLACES = (OVERVIEW, ACTIONS, RUNS, SEPARATOR, ENVIRONMENTS, ESTATE, DELIVERY)

NAMES = {
    OVERVIEW: "Overview",
    ACTIONS: "Actions",
    RUNS: "Runs",
    ENVIRONMENTS: "Environments",
    ESTATE: "Estate",
    DELIVERY: "Delivery",
}

MANAGED_NOTE = "What Ordane manages"


@dataclass(frozen=True)
class Tallies:
    """The small right-hand figures. Empty is drawn as nothing, never as zero."""

    actions: str = ""
    environments: str = ""
    estate: str = ""
    running: bool = False


def repository_menu() -> Gio.Menu:
    """Every method on the repository, in one place instead of nine rail rows."""
    menu = Gio.Menu()

    reading = Gio.Menu()
    reading.append("Re-read the repository", "win.refresh")
    reading.append(f"Open {CONFIG_NAME}", "win.configure")
    reading.append("Show the repository folder", "win.folder")
    menu.append_section(None, reading)

    driving = Gio.Menu()
    driving.append("Choose what runs…", "win.refs")
    driving.append("Manage environments…", "win.environments")
    driving.append("Set up objectives…", "win.objectives")
    driving.append("Run this repository's own checks…", "win.checks")
    driving.append("Check that this repository is set up correctly", "win.checkup")
    menu.append_section(None, driving)

    keeping = Gio.Menu()
    keeping.append("Export the history…", "win.export")
    keeping.append("Point at the shared stores…", "win.stores")
    menu.append_section(None, keeping)

    switching = Gio.Menu()
    switching.append("Open another repository…", "win.open")
    switching.append("Clone from a git URL…", "win.clone")
    menu.append_section(None, switching)
    return menu


class Rail(Gtk.Box):
    """Built once; the tallies and the repository card are what change."""

    def __init__(self, on_go) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(WIDTH, -1)
        self.add_css_class("rail")
        self._on_go = on_go
        self._buttons: dict[str, Gtk.Widget] = {}
        self._tallies: dict[str, Gtk.Label] = {}
        self._current = OVERVIEW

        self.append(_brand())

        places = w.box(spacing=1)
        places.set_margin_start(10)
        places.set_margin_end(10)
        for key in PLACES:
            if key == SEPARATOR:
                places.append(_separator())
                places.append(_managed_note())
                continue
            places.append(self._place(key))
        self.append(places)

        self.append(w.spacer(vertical=True))
        self.append(self._foot())
        self.set_current(OVERVIEW)

    # --- the rows ---

    def _place(self, key: str) -> Gtk.Widget:
        line = w.row(10)
        line.append(Glyph(key))
        name = w.label(NAMES[key])
        name.set_hexpand(True)
        name.set_ellipsize(3)
        line.append(name)

        tally = w.label("", "place-tally", "mono", xalign=1.0)
        line.append(tally)
        self._tallies[key] = tally

        button = Gtk.Button(child=line)
        button.add_css_class("place")
        button.add_css_class("flat")
        key_binding = for_action(f"win.page::{key}")
        button.set_tooltip_text(
            f"{NAMES[key]} ({key_binding.pretty})" if key_binding else NAMES[key]
        )
        button.connect("clicked", lambda _b, name=key: self._on_go(name))
        self._buttons[key] = button
        return button

    def _foot(self) -> Gtk.Widget:
        holder = w.box(spacing=0)
        holder.set_margin_start(10)
        holder.set_margin_end(10)
        holder.set_margin_bottom(12)

        inside = w.box(spacing=0)
        top = w.row(7)
        top.append(Glyph("repository", 13))
        self._name = w.label("", "repo-name", "mono")
        self._name.set_ellipsize(3)
        self._name.set_hexpand(True)
        top.append(self._name)
        top.append(Gtk.Image.new_from_icon_name("pan-end-symbolic"))
        inside.append(top)

        self._chips = w.row(6)
        self._chips.set_margin_top(7)
        inside.append(self._chips)

        self._when = w.label("", "repo-when")
        self._when.set_margin_top(7)
        inside.append(self._when)

        self._card = Gtk.MenuButton(child=inside, menu_model=repository_menu())
        self._card.add_css_class("repo-card")
        self._card.add_css_class("flat")
        self._card.set_tooltip_text("Everything this console can do to the repository")
        holder.append(self._card)

        hint = w.row(4)
        hint.set_margin_top(10)
        hint.set_margin_start(3)
        hint.add_css_class("kbd-hint")
        hint.append(w.keycap("Ctrl"))
        hint.append(w.keycap("K"))
        hint.append(w.label("for everything else"))
        holder.append(hint)
        return holder

    # --- what the window tells it ---

    def set_current(self, key: str) -> None:
        self._current = key
        for name, button in self._buttons.items():
            chosen = name == key
            if chosen:
                button.add_css_class("current")
            else:
                button.remove_css_class("current")
            glyph = button.get_child().get_first_child()
            glyph.queue_draw()

    def set_tallies(self, tallies: Tallies) -> None:
        self._tallies[ACTIONS].set_text(tallies.actions)
        self._tallies[ENVIRONMENTS].set_text(tallies.environments)
        self._tallies[ESTATE].set_text(tallies.estate)
        # A live run is a dot rather than a count: the number of running things
        # is one, and what matters is that there is one.
        self._tallies[RUNS].set_text("●" if tallies.running else "")
        if tallies.running:
            self._tallies[RUNS].add_css_class("tint-ok")
        else:
            self._tallies[RUNS].remove_css_class("tint-ok")

    def set_menu(self, menu: Gio.Menu) -> None:
        self._card.set_menu_model(menu)

    def show_state(self, *, repo, readable: bool, freshness: str, checkout, actor, plane) -> None:
        """Which repository this window drives, and what state it was read in."""
        self._name.set_text(plane.name)
        w.clear(self._chips)
        if checkout.branch:
            self._chips.append(_chip(checkout.branch))
            self._chips.append(_chip("dirty" if checkout.dirty else "clean", checkout.dirty))
        else:
            self._chips.append(_chip("not a git checkout"))
        if readable:
            self._chips.append(_chip(CONFIG_NAME))
        self._when.set_text(freshness if readable else "cannot be read")
        self._card.set_tooltip_text(
            f"{repo}\n{plane.where_from}\n"
            f"{checkout.summary or 'not a git checkout'}\n{actor.summary}"
        )


def _chip(text: str, dirty: bool = False) -> Gtk.Widget:
    chip = w.label(text, "gitchip", "mono")
    if text == "clean":
        chip.add_css_class("clean")
    if dirty:
        chip.add_css_class("dirty")
    chip.set_valign(Gtk.Align.CENTER)
    return chip


def _brand() -> Gtk.Widget:
    line = w.row(9)
    line.add_css_class("brand")
    line.set_margin_start(16)
    line.set_margin_end(16)
    line.set_margin_top(2)
    line.set_margin_bottom(16)
    line.append(Glyph("brand", 19))
    line.append(w.label("Ordane", "brand-name"))
    line.append(w.spacer())
    line.append(w.label(__version__, "brand-version", "mono"))
    return line


def _separator() -> Gtk.Widget:
    line = w.divider()
    line.add_css_class("rail-sep")
    line.set_margin_top(13)
    line.set_margin_bottom(13)
    line.set_margin_start(6)
    line.set_margin_end(6)
    return line


def _managed_note() -> Gtk.Widget:
    note = w.label(MANAGED_NOTE, "rail-note")
    note.set_margin_start(6)
    note.set_margin_bottom(7)
    return note
