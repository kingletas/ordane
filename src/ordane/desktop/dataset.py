"""Writing the run history out, in whichever shape the store on the other end reads.

The console does not connect to anything and is not going to: a projection is
data, and handing somebody a file is the version of this that cannot break
because a server was down.
"""

from __future__ import annotations

from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gio, GLib, Gtk  # noqa: E402

from ..insight import dataset, export  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402

SUFFIX = {"jsonl": "jsonl", "csv": "csv", "influx": "lp", "cypher": "cypher"}


class ExportDialog(Adw.Dialog):
    """Which shape, how much of it, and what it will contain: before it is written."""

    def __init__(self, *, runs, everything, plane: str, on_written) -> None:
        super().__init__(title="Export the history", content_width=600)
        self._runs = runs
        self._everything = everything
        self._plane = plane
        self._on_written = on_written

        self._format = Adw.ComboRow(
            title="Shape",
            model=Gtk.StringList.new([export.WHAT_EACH_IS[k].capitalize() for k in export.FORMATS]),
        )
        self._format.set_subtitle_lines(2)
        self._format.connect("notify::selected", lambda *_: self._describe())

        self._scope = Adw.SwitchRow(
            title="Every control plane",
            subtitle=f"Off, this is {plane} alone",
        )
        self._scope.connect("notify::active", lambda *_: self._describe())

        self._summary = w.label("", "metric-detail", wrap=True)
        self.set_child(self._build())
        self._describe()

    def _build(self) -> Gtk.Widget:
        toolbar = Adw.ToolbarView()
        header = Adw.HeaderBar(show_end_title_buttons=False, show_start_title_buttons=False)
        cancel = Gtk.Button(label="Cancel")
        cancel.connect("clicked", lambda *_: self.close())
        header.pack_start(cancel)
        save = Gtk.Button(label="Save…")
        save.add_css_class("suggested-action")
        save.connect("clicked", lambda *_: self._choose_file())
        header.pack_end(save)
        toolbar.add_top_bar(header)

        body = w.box(spacing=16)
        for side in ("top", "bottom", "start", "end"):
            getattr(body, f"set_margin_{side}")(16)
        body.append(
            w.label(
                "The history, written for another store to read. Nothing is sent anywhere: "
                "this writes a file.",
                "tint-muted",
                wrap=True,
            )
        )
        group = Adw.PreferencesGroup()
        group.add(self._format)
        group.add(self._scope)
        body.append(group)

        strip = w.box(spacing=4)
        strip.add_css_class("command-strip")
        strip.append(w.label("WILL CONTAIN", "metric-label"))
        strip.append(self._summary)
        body.append(strip)

        toolbar.set_content(w.sheet(body))
        return toolbar

    def _kind(self) -> str:
        return export.FORMATS[self._format.get_selected()]

    def _chosen_runs(self) -> list:
        return self._everything if self._scope.get_active() else self._runs

    def _describe(self) -> None:
        runs = self._chosen_runs()
        model = dataset.graph(runs)
        self._summary.set_text(
            f"{plural(len(dataset.facts(runs)), 'finished run')}, "
            f"{plural(len(dataset.series(runs)), 'measurement')}, "
            f"{plural(len(model.nodes), 'node')} and {plural(len(model.edges), 'edge')}."
        )

    def _choose_file(self) -> None:
        dialog = Gtk.FileDialog(title="Where to write it")
        dialog.set_initial_name(f"ordane-history.{SUFFIX[self._kind()]}")
        dialog.save(self.get_root(), None, self._write)

    def _write(self, dialog, result) -> None:
        try:
            chosen = dialog.save_finish(result)
        except GLib.Error:
            return
        if chosen is None or chosen.get_path() is None:
            return
        path = Path(chosen.get_path())
        runs = self._chosen_runs()
        try:
            path.write_text(export.render(runs, self._kind()), encoding="utf-8")
        except OSError as exc:
            self._on_written(f"Could not write {path.name}: {exc.strerror}")
            return
        self.close()
        self._on_written(f"Wrote {plural(len(runs), 'run')} to {path.name}")


def file_dialog_supported() -> bool:
    """Whether this GTK has the save dialog. Nothing here is worth a crash."""
    return hasattr(Gtk, "FileDialog") and hasattr(Gio, "File")
