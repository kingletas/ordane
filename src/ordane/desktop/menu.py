"""The primary menu, the shortcuts sheet and the about dialog.

The menu is grouped by what somebody opened it to do rather than by which part
of the code owns each row, and every accelerator in it is drawn from the
shortcut table, so a menu row cannot name a key the window does not bind.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from .. import __version__  # noqa: E402
from ..core.config import CONFIG_NAME
from ..presentation.language import OWN_CHECKS, PLANE  # noqa: E402
from . import widgets as w  # noqa: E402
from .app_id import APP_ID  # noqa: E402
from .shortcuts import KEYS, by_group  # noqa: E402

PROJECT = "https://github.com/kingletas/ordane"


def primary_menu(others: list[Path] | None = None) -> Gio.Menu:
    """Four sections: what you are looking at, what drives it, which one, and help."""
    menu = Gio.Menu()

    looking = Gio.Menu()
    looking.append("Find a target", "win.find")
    looking.append("Re-read the repository", "win.refresh")
    menu.append_section(None, looking)

    driving = Gio.Menu()
    driving.append(f"Run {OWN_CHECKS}…", "win.checks")
    driving.append("Choose what runs…", "win.refs")
    driving.append("Manage environments…", "win.environments")
    driving.append("Set up objectives…", "win.objectives")
    driving.append("Point at the shared stores…", "win.stores")
    driving.append("Export the history…", "win.export")
    driving.append(f"Open {CONFIG_NAME}", "win.configure")
    driving.append("Open the repository folder", "win.folder")
    menu.append_section(f"This {PLANE}", driving)

    switching = Gio.Menu()
    switching.append("Open another control plane…", "win.open")
    switching.append("Open from a git URL…", "win.clone")
    for path in others or []:
        # The name alone: the full path is the row's tooltip in the chooser,
        # and a menu of absolute paths is unreadable.
        item = Gio.MenuItem.new(path.name, None)
        item.set_action_and_target_value("win.open-recent", GLib.Variant.new_string(str(path)))
        switching.append_item(item)
    menu.append_section("Another one" if others else None, switching)

    helping = Gio.Menu()
    helping.append(f"Check this {PLANE}", "win.checkup")
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


def about_dialog(repo) -> Adw.AboutDialog:
    """What this is, in two sentences, plus where the repository it drives lives."""
    dialog = Adw.AboutDialog(
        application_name="Ordane",
        application_icon=APP_ID,
        developer_name="Luis Tineo",
        version=__version__,
        website=PROJECT,
        issue_url=f"{PROJECT}/issues",
        license_type=Gtk.License.MIT_X11,
        comments=(
            "A console for an Ansible control plane, with or without a Makefile.\n\n"
            "It replaces nothing. Where there is a Makefile it reads what `make help` "
            "already prints and runs make for you; where there is not, the playbooks "
            "are the catalogue and it runs ansible-playbook directly. Either way it "
            "shows the command first, streams the output, and keeps the record.\n\n"
            f"Driving: {repo}"
        ),
    )
    dialog.set_copyright("© 2026 Luis Tineo")
    return dialog
