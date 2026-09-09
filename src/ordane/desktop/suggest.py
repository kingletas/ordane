"""A field that completes as you type, for a list too long to scroll.

A dropdown of sixty-three patches is a list somebody hunts through. Typing three
characters and picking from what is left is the same choice made in a second,
and the list itself is still there for anyone who wants to look at all of it.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, Gtk  # noqa: E402

from ..core.choices import SHOWN, matches  # noqa: E402
from . import widgets as w  # noqa: E402


class Completer:
    """Attaches a filtering list to an entry, and offers a way to add to it."""

    def __init__(
        self,
        entry: Gtk.Entry,
        choices: Callable[[], list[str]],
        *,
        noun: str = "",
        on_add: Callable[[], None] | None = None,
    ) -> None:
        self._entry = entry
        self._choices = choices
        self._noun = noun
        self._on_add = on_add
        self._quiet = False

        self._list = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._list.add_css_class("boxed-list")
        self._list.connect("row-activated", self._take)

        holder = Gtk.ScrolledWindow(
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            max_content_height=300,
            propagate_natural_height=True,
        )
        holder.set_child(self._list)

        # The way to add one is pinned below the scrolling part: on a long list
        # it would otherwise be the one row nobody can see.
        self._adds = Gtk.ListBox(selection_mode=Gtk.SelectionMode.SINGLE)
        self._adds.connect("row-activated", self._take)
        self._adds.set_visible(False)
        if on_add is not None:
            self._adds.append(_add(f"Paste a new {noun}…"))
            self._adds.set_visible(True)

        stack = w.box(spacing=0)
        stack.append(holder)
        stack.append(self._adds)

        self._popover = Gtk.Popover(autohide=False, has_arrow=False, child=stack)
        self._popover.set_parent(entry)
        self._popover.set_position(Gtk.PositionType.BOTTOM)
        self._popover.set_size_request(320, -1)

        entry.connect("changed", lambda *_: None if self._quiet else self._refill())
        entry.connect("notify::has-focus", self._focus_moved)
        entry.connect("destroy", lambda *_: self._popover.unparent())

        entry._completer = self

        keys = Gtk.EventControllerKey()
        keys.connect("key-pressed", self._pressed)
        entry.add_controller(keys)

    # --- what is on the list ---

    def _refill(self) -> None:
        while (row := self._list.get_first_child()) is not None:
            self._list.remove(row)

        found = matches(self._entry.get_text(), self._choices())
        for one in found[:SHOWN]:
            self._list.append(_choice(one))
        if len(found) > SHOWN:
            self._list.append(_note(f"and {len(found) - SHOWN} more — keep typing"))
        if not found:
            typed = self._entry.get_text().strip()
            said = f"Nothing here is called “{typed}”" if typed else "Nothing yet"
            self._list.append(_note(said))

        rows = self._list.get_first_child() is not None or self._on_add is not None
        if rows and self._focused():
            self._popover.popup()
        else:
            self._popover.popdown()

    def _focused(self) -> bool:
        """Whether the focus is inside this entry.

        Not `has_focus`: the focus widget is the `GtkText` inside the entry, and
        that answer also goes false whenever the window itself is not active.
        """
        root = self._entry.get_root()
        widget = root.get_focus() if root is not None else None
        while widget is not None:
            if widget is self._entry:
                return True
            widget = widget.get_parent()
        return False

    def _focus_moved(self, entry, _param) -> None:
        if entry.has_focus():
            self._refill()
        else:
            self._popover.popdown()

    # --- picking one ---

    def _take(self, _box, row) -> None:
        if getattr(row, "adds", False):
            self._popover.popdown()
            if self._on_add is not None:
                self._on_add()
            return
        value = getattr(row, "value", "")
        if not value:
            return
        self.fill(value)

    def fill(self, value: str) -> None:
        """Puts a value in without the list reopening under it."""
        self._quiet = True
        self._entry.set_text(value)
        self._entry.set_position(-1)
        self._quiet = False
        self._popover.popdown()

    def _pressed(self, _controller, keyval, _code, _state) -> bool:
        if keyval == Gdk.KEY_Escape and self._popover.get_visible():
            self._popover.popdown()
            return True
        if keyval in (Gdk.KEY_Down, Gdk.KEY_Up):
            if not self._popover.get_visible():
                self._refill()
            self._step(1 if keyval == Gdk.KEY_Down else -1)
            return True
        if keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter) and self._popover.get_visible():
            row = (
                self._list.get_selected_row()
                or self._adds.get_selected_row()
                or self._first_choice()
            )
            if row is not None:
                self._take(self._list, row)
                return True
        return False

    def _step(self, by: int) -> None:
        rows = [row for row in _rows(self._list) if getattr(row, "value", "")]
        rows += _rows(self._adds)
        if not rows:
            return
        current = self._list.get_selected_row() or self._adds.get_selected_row()
        index = rows.index(current) + by if current in rows else (0 if by > 0 else len(rows) - 1)
        wanted = rows[max(0, min(index, len(rows) - 1))]
        self._list.select_row(wanted if wanted.get_parent() is self._list else None)
        self._adds.select_row(wanted if wanted.get_parent() is self._adds else None)

    def _first_choice(self):
        for row in _rows(self._list):
            if getattr(row, "value", ""):
                return row
        return None


def _rows(box: Gtk.ListBox) -> list:
    found, index = [], 0
    while (row := box.get_row_at_index(index)) is not None:
        found.append(row)
        index += 1
    return found


def _choice(text: str) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow()
    row.set_child(_padded(w.label(text, "", "mono")))
    row.value = text
    return row


def _padded(label: Gtk.Widget) -> Gtk.Widget:
    label.set_xalign(0.0)
    label.set_margin_start(12)
    label.set_margin_end(12)
    label.set_margin_top(6)
    label.set_margin_bottom(6)
    return label


def _note(text: str) -> Gtk.ListBoxRow:
    row = Gtk.ListBoxRow(activatable=False, selectable=False)
    row.set_child(_padded(w.label(text, "metric-detail", wrap=True)))
    return row


def _add(text: str) -> Gtk.ListBoxRow:
    row = Adw.ActionRow(title=text)
    row.add_prefix(Gtk.Image.new_from_icon_name("list-add-symbolic"))
    row.adds = True
    return row
