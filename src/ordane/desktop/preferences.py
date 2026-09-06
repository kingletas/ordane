"""What this person keeps, which is a choice rather than a default to work around.

The rail and the menu hold the same nine things. Which of them a window shows
is taste: the rail is faster to read, the menu is out of the way, so it is
asked rather than decided.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from . import geometry  # noqa: E402
from . import widgets as w  # noqa: E402


class Preferences(Adw.Dialog):
    """One choice today. It applies as it is made, so there is nothing to save."""

    def __init__(self, chosen: str, on_choose) -> None:
        super().__init__(title="Preferences", content_width=560)
        self._on_choose = on_choose
        self._buttons: dict[str, Gtk.CheckButton] = {}

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(18)

        group = Adw.PreferencesGroup(
            title="Where things live",
            description="The rail and the menu hold the same rows. Keep either, or both.",
        )
        first = None
        for key, name, meaning in geometry.NAVIGATION:
            row = Adw.ActionRow(title=name, subtitle=meaning)
            row.set_subtitle_lines(2)
            button = Gtk.CheckButton(valign=Gtk.Align.CENTER)
            if first is None:
                first = button
            else:
                button.set_group(first)
            button.set_active(key == chosen)
            button.connect("toggled", lambda b, k=key: b.get_active() and self._on_choose(k))
            row.add_prefix(button)
            row.set_activatable_widget(button)
            self._buttons[key] = button
            group.add(row)
        body.append(group)
        body.append(
            w.label(
                "A narrow window folds the rail away and keeps the menu whatever is chosen "
                "here, because nine rows with nowhere to be reached is not a preference.",
                "tint-muted",
                wrap=True,
            )
        )

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(Adw.HeaderBar())
        toolbar.set_content(w.sheet(body))
        self.set_child(toolbar)
