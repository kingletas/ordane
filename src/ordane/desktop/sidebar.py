"""The navigation rail: search, the one high-value action, and where things are.

Everything here used to be behind a hamburger, which is where an application
puts the things it does not expect anybody to use. A control plane console is
opened to do one of about eight things, and this is the eight of them.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..core.config import CONFIG_NAME  # noqa: E402
from ..presentation.language import OWN_CHECKS, PLANE  # noqa: E402
from . import widgets as w  # noqa: E402
from .shortcuts import for_action  # noqa: E402

WIDTH = 312

# Icon, label, action, and whether the row is the one worth highlighting.
ENTRIES = (
    (
        "This control plane",
        (
            ("object-select-symbolic", f"Run {OWN_CHECKS}…", "win.checks"),
            ("media-playlist-repeat-symbolic", "Choose what runs…", "win.refs"),
            ("preferences-system-symbolic", "Manage environments…", "win.environments"),
            ("starred-symbolic", "Set up objectives…", "win.objectives"),
            ("text-x-generic-symbolic", f"Open {CONFIG_NAME}", "win.configure"),
            ("folder-symbolic", "Open the repository folder", "win.folder"),
            ("document-open-symbolic", "Open another control plane…", "win.open"),
            ("network-workgroup-symbolic", "Open from a git URL…", "win.clone"),
            ("network-server-symbolic", "Point at the shared stores…", "win.stores"),
            ("document-save-symbolic", "Export the history…", "win.export"),
        ),
    ),
    (
        "Resources",
        (
            ("emblem-important-symbolic", f"Check this {PLANE}", "win.checkup"),
            ("preferences-desktop-keyboard-symbolic", "Keyboard shortcuts", "win.shortcuts"),
            ("help-browser-symbolic", "User guide", "win.guide"),
            ("help-about-symbolic", "About Ordane", "win.about"),
            ("emblem-system-symbolic", "Preferences", "win.preferences"),
        ),
    ),
)


class Sidebar(Gtk.Box):
    """Built once; only the connection card at the foot of it changes."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=0)
        self.set_size_request(WIDTH, -1)
        self.add_css_class("console-sidebar")

        body = w.box(spacing=8)
        for side in ("top", "start", "end"):
            getattr(body, f"set_margin_{side}")(12)

        refresh = _action_row("view-refresh-symbolic", "Re-read the repository", "win.refresh")
        refresh.add_css_class("quick")
        body.append(refresh)

        for title, rows in ENTRIES:
            body.append(_section(title))
            for icon, text, action in rows:
                body.append(_action_row(icon, text, action))

        scroller = Gtk.ScrolledWindow(child=body, vexpand=True)
        scroller.set_policy(Gtk.PolicyType.NEVER, Gtk.PolicyType.AUTOMATIC)
        self.append(scroller)

        self._connection = ConnectionCard()
        self.append(self._connection)

    def show_state(self, **state) -> None:
        self._connection.render(**state)


def _section(title: str) -> Gtk.Widget:
    label = w.label(title.upper(), "sidebar-section")
    label.set_margin_top(14)
    label.set_margin_bottom(2)
    return label


def _action_row(icon: str, text: str, action: str) -> Gtk.Widget:
    """One navigation row: icon, label, and the key that also does it."""
    row = w.box(Gtk.Orientation.HORIZONTAL, 10)
    image = Gtk.Image.new_from_icon_name(icon)
    image.set_valign(Gtk.Align.CENTER)
    row.append(image)
    label = w.label(text)
    label.set_hexpand(True)
    label.set_ellipsize(3)
    row.append(label)

    key = for_action(action)
    if key is not None:
        row.append(w.label(key.pretty, "sidebar-accelerator"))

    button = Gtk.Button(child=row)
    button.add_css_class("flat")
    button.add_css_class("sidebar-row")
    button.set_action_name(action)
    button.set_tooltip_text(text)
    return button


class ConnectionCard(Gtk.Box):
    """Which control plane this window is driving, and whether it is readable."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        self.add_css_class("connection-card")
        for side in ("top", "bottom", "start", "end"):
            getattr(self, f"set_margin_{side}")(12)

        top = w.box(Gtk.Orientation.HORIZONTAL, 8)
        self._dot = w.dot("ok")
        top.append(self._dot)
        self._state = w.label("", "connection-state")
        top.append(self._state)
        self.append(top)

        self._name = w.label("", "connection-name")
        self._name.set_ellipsize(3)
        self.append(self._name)
        self._freshness = w.label("", "metric-detail")
        self.append(self._freshness)
        self._checkout = w.label("", "metric-detail")
        self._checkout.set_ellipsize(3)
        self.append(self._checkout)
        # Who the runs are recorded as. A history several people read has to
        # say whose run it was, and this is where that starts.
        self._actor = w.label("", "metric-detail")
        self._actor.set_ellipsize(3)
        self.append(self._actor)

        details = Gtk.Button(label="Check the setup")
        details.add_css_class("pill")
        details.set_margin_top(8)
        details.set_action_name("win.checkup")
        details.set_tooltip_text("Everything checkable without launching anything")
        self.append(details)

    def render(self, *, repo, readable: bool, freshness: str, checkout, actor, plane) -> None:
        self._dot.remove_css_class("ok")
        self._dot.remove_css_class("bad")
        self._dot.add_css_class("ok" if readable else "bad")
        self._state.set_text("Connected" if readable else "Cannot be read")
        self._name.set_text(plane.name)
        self.set_tooltip_text(f"{repo}\n{plane.where_from}")
        self._freshness.set_text(freshness)
        self._checkout.set_text(checkout.summary or "not a git checkout")
        self._actor.set_text(actor.summary)
        if actor.is_root:
            self._actor.add_css_class("tint-bad")
