"""The primary menu and the shortcuts sheet.

Every accelerator in either is drawn from the shortcut table, so a row cannot
name a key the window does not bind.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from . import widgets as w  # noqa: E402
from .shortcuts import KEYS, by_group  # noqa: E402

PROJECT = "https://github.com/kingletas/ordane"


def primary_menu(others: list[Path] | None = None) -> Gio.Menu:
    """What is neither a place nor a method on the repository.

    The places are in the rail, and everything the repository can be asked to
    do is on its own card and in the command palette. What is left is the
    application: how it behaves, how to drive it, and what it is.
    """
    menu = Gio.Menu()

    looking = Gio.Menu()
    looking.append("Search or run a command", "win.palette")
    looking.append("Find an action", "win.find")
    menu.append_section(None, looking)

    switching = Gio.Menu()
    switching.append("Open another control plane…", "win.open")
    switching.append("Clone from a git URL…", "win.clone")
    for path in others or []:
        # The name alone: the full path is the row's tooltip in the chooser,
        # and a menu of absolute paths is unreadable.
        item = Gio.MenuItem.new(path.name, None)
        item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(str(path)))
        switching.append_item(item)
    menu.append_section("Another one" if others else None, switching)

    helping = Gio.Menu()
    helping.append("Preferences", "win.preferences")
    helping.append("Keyboard shortcuts", "win.shortcuts")
    helping.append("User guide", "win.guide")
    helping.append("About Ordane", "win.about")
    menu.append_section(None, helping)
    return menu


def install_accelerators(application: Gtk.Application) -> None:
    """Binds the table to the application, which is also what puts keys in the menu."""
    for key in KEYS:
        application.set_accels_for_action(key.action, [key.accelerator])


class ShortcutsDialog(Adw.Dialog):
    """The same table the window binds, drawn."""

    def __init__(self) -> None:
        super().__init__(title="Keyboard shortcuts", content_width=460)
        body = w.box(spacing=18)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)
        for name, keys in by_group():
            group = Adw.PreferencesGroup(title=name)
            for key in keys:
                row = Adw.ActionRow(title=key.label)
                row.add_suffix(w.keycap(key.pretty))
                group.add(row)
            body.append(group)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(w.sheet(body))
        self.set_child(toolbar)
