"""Paste something into a choice list that does not hold it yet.

The patch somebody needs is often the one that is not on disk, and sending them
to a terminal to write the file is what makes a console a viewer.
"""

from __future__ import annotations

from collections.abc import Callable

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ..core import choices as choices_module  # noqa: E402
from . import widgets as w  # noqa: E402


class PasteDialog(Adw.Dialog):
    """Collects a name and a body, and writes one file where the list is read from."""

    def __init__(
        self,
        *,
        source: choices_module.Source,
        repo,
        on_added: Callable[[str], None],
    ) -> None:
        super().__init__(title=f"New {source.noun}", content_width=680, content_height=560)
        self._source = source
        self._repo = repo
        self._on_added = on_added

        self._error = Adw.Banner(revealed=False)
        self._error.add_css_class("error")

        self._name = Gtk.Entry(valign=Gtk.Align.CENTER, hexpand=True, width_chars=24)
        self._name.set_placeholder_text(
            f"MDVA-00000{self._source.suffix}".removesuffix(self._source.suffix)
        )

        self._body = Gtk.TextView(monospace=True, top_margin=8, bottom_margin=8)
        self._body.set_left_margin(8)
        self._body.set_right_margin(8)
        self._body.set_wrap_mode(Gtk.WrapMode.NONE)

        self.set_child(self._build())
        self._name.grab_focus()

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)

        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)

        save = Gtk.Button(label="Add")
        save.add_css_class("suggested-action")
        save.connect("clicked", self._on_save)
        header.pack_end(save)
        toolbar.add_top_bar(header)

        body = w.box(spacing=12)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(16)

        body.append(self._error)
        body.append(
            w.label(
                f"Paste it below and give it a name. It is written to {self._where()}, "
                "and nothing already there is overwritten.",
                "metric-detail",
                wrap=True,
            )
        )

        row = Adw.ActionRow(title="Name")
        row.add_suffix(self._name)
        row.set_activatable_widget(self._name)
        group = Adw.PreferencesGroup()
        group.add(row)
        body.append(group)

        holder = Gtk.ScrolledWindow(vexpand=True)
        holder.add_css_class("card")
        holder.set_child(self._body)
        body.append(holder)

        toolbar.set_content(body)
        return toolbar

    def _where(self) -> str:
        """The directory as somebody would refer to it, not as the disk holds it."""
        directory = self._source.directory
        try:
            directory = directory.relative_to(self._repo)
        except (TypeError, ValueError):
            pass
        return f"{directory}/<name>{self._source.suffix}"

    def _on_save(self, _button) -> None:
        self._error.set_revealed(False)
        buffer = self._body.get_buffer()
        text = buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)
        try:
            path = choices_module.add(self._source, self._name.get_text(), text)
        except choices_module.AddError as exc:
            self._error.set_title(str(exc))
            self._error.set_revealed(True)
            return
        except OSError as exc:
            self._error.set_title(f"It could not be written: {exc.strerror or exc}")
            self._error.set_revealed(True)
            return
        name = path.name.removesuffix(self._source.suffix) if self._source.suffix else path.name
        self.close()
        self._on_added(name)
