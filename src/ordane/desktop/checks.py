"""What a control plane checks about itself, and how those checks went.

The suite runs in the container the repository declared: read-only, no
network, as this user. **It is not a run against a host**, so it is shown here
rather than in the run view: a check that passed is evidence about the
repository, not about the fleet.
"""

from __future__ import annotations

import threading
from pathlib import Path

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..core import validation  # noqa: E402
from ..presentation.language import OWN_CHECKS  # noqa: E402
from ..presentation.text import plural, took  # noqa: E402
from ..record.store import now  # noqa: E402
from . import widgets as w  # noqa: E402

STATE_BADGE = {"passed": "ok", "failed": "high", "skipped": "medium"}


class ChecksDialog(Adw.Dialog):
    """One row per check, filled in as each finishes."""

    def __init__(self, *, repo: Path, suite: validation.Suite, on_done=None) -> None:
        super().__init__(
            title=OWN_CHECKS[0].upper() + OWN_CHECKS[1:],
            content_width=720,
            content_height=620,
        )
        self._repo = repo
        self._suite = suite
        self._on_done = on_done or (lambda _report: None)
        self._rows: dict[str, Adw.ExpanderRow] = {}
        self._badges: dict[str, Gtk.Widget] = {}
        self._running = False
        self._started = ""

        # A plain banner is accent-coloured, and an accent can be red: which
        # made `3 of 3 passed` look like a failure. The banner is for failure
        # only; the summary is a line that carries its own tint.
        self._banner = Adw.Banner(revealed=False)
        self._banner.add_css_class("error")
        self._summary = w.label("", "metric-detail", wrap=True)
        self._group = Adw.PreferencesGroup()
        self._body = w.box(spacing=16)
        self._body.set_margin_top(8)
        for side in ("bottom", "start", "end"):
            getattr(self._body, f"set_margin_{side}")(16)
        self._body.append(self._summary)
        self._body.append(self._group)

        self._run = Gtk.Button(label="Run the checks")
        self._run.add_css_class("suggested-action")
        self._run.connect("clicked", lambda *_: self.start())
        header = Adw.HeaderBar()
        header.pack_end(self._run)

        toolbar = Adw.ToolbarView()
        toolbar.add_top_bar(header)
        toolbar.add_top_bar(self._banner)
        toolbar.set_content(w.sheet(self._body))
        self.set_child(toolbar)
        self._describe()

    # --- what it shows before anything has run ---

    def _describe(self) -> None:
        why = validation.available(self._suite)
        if why:
            self._run.set_sensitive(False)
            self._body.remove(self._group)
            self._body.append(
                w.empty(
                    "Nothing to check yet",
                    f"{why}\n\nDeclare a `validation` block in the configuration: an image, and "
                    "the checks to run in it.",
                    "emblem-important-symbolic",
                )
            )
            return
        self._group.set_title(f"{plural(len(self._suite.checks), 'check')} in {self._suite.image}")
        self._group.set_description(
            "Read-only, no network, and as you rather than root. A check that needs to write "
            "to the repository or reach a host is not a check."
        )
        for check in self._suite.checks:
            row = Adw.ExpanderRow(title=check.name, subtitle=check.display)
            row.set_subtitle_lines(2)
            row.set_enable_expansion(False)
            self._rows[check.name] = row
            self._mark(check.name, "NOT RUN", "low")
            self._group.add(row)

    # --- running them ---

    def start(self) -> None:
        if self._running or validation.available(self._suite):
            return
        self._running = True
        self._started = now()
        self._run.set_sensitive(False)
        self._say("Running…", failed=False)
        for name in self._rows:
            self._mark(name, "WAITING", "low")
        threading.Thread(target=self._work, daemon=True, name="checks").start()

    def _work(self) -> None:
        report = validation.run(
            self._repo, self._suite, on_result=lambda one: GLib.idle_add(self._landed, one)
        )
        GLib.idle_add(self._finished, report)

    def _landed(self, result) -> bool:
        row = self._rows.get(result.check.name)
        if row is None:
            return False
        self._mark(result.check.name, result.state.upper(), STATE_BADGE.get(result.state, "low"))
        row.set_subtitle(f"{result.check.display} · {took(result.seconds) or 'under a second'}")
        if result.output:
            # Only what failed opens itself: a passing check's output is
            # evidence somebody may want and never something to read now.
            row.set_enable_expansion(True)
            row.set_expanded(not result.ok)
            row.add_row(_output(result.output))
        return False

    def _finished(self, report) -> bool:
        self._running = False
        self._run.set_sensitive(True)
        self._run.set_label("Run them again")
        self._say(report.summary, failed=not report.ok)
        self._on_done(report)
        return False

    def connect_done(self, handler) -> None:
        """Set after construction, where the caller needs the dialog to say when it began."""
        self._on_done = handler

    @property
    def started(self) -> str:
        """When the suite began, rather than when its record was written."""
        return self._started

    def _mark(self, name: str, text: str, kind: str) -> None:
        """One badge per row, replaced rather than added to."""
        row = self._rows.get(name)
        if row is None:
            return
        standing = self._badges.pop(name, None)
        if standing is not None:
            row.remove(standing)
        badge = w.badge(text, kind)
        badge.set_valign(Gtk.Align.CENTER)
        row.add_suffix(badge)
        self._badges[name] = badge

    def _say(self, text: str, *, failed: bool) -> None:
        self._summary.set_text(text)
        for tint in ("tint-ok", "tint-bad"):
            self._summary.remove_css_class(tint)
        self._summary.add_css_class("tint-bad" if failed else "tint-ok")
        self._banner.set_title(text)
        self._banner.set_revealed(failed)


def _output(text: str) -> Gtk.Widget:
    """What the check printed, in the same face the run output uses."""
    view = Gtk.TextView(
        editable=False, cursor_visible=False, monospace=True, wrap_mode=Gtk.WrapMode.WORD_CHAR
    )
    view.get_buffer().set_text(text)
    view.add_css_class("console-output")
    holder = Gtk.ScrolledWindow(child=view, max_content_height=260, propagate_natural_height=True)
    holder.set_margin_top(6)
    holder.set_margin_bottom(6)
    return holder
