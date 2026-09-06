"""One run: its result first, then its output, streamed while it is alive."""

from __future__ import annotations

import threading

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gdk, GLib, Gtk, Pango  # noqa: E402

from ..insight import relaunch  # noqa: E402
from ..presentation import ansi, language  # noqa: E402
from ..presentation.text import moment, plural, since, took  # noqa: E402
from ..record import notices  # noqa: E402
from ..record import summary as summary_module  # noqa: E402
from ..record.store import Run  # noqa: E402
from . import widgets as w  # noqa: E402

# The palette the output view paints with, chosen to stay legible on both of
# libadwaita's backgrounds rather than matching a terminal exactly.
TAG_COLOURS = {
    "red": "#e0685f",
    "green": "#4f9d5c",
    "yellow": "#b3801f",
    "blue": "#4a7fc1",
    "magenta": "#a768c0",
    "cyan": "#2f8f92",
    "white": "#3a3a38",
    "black": "#7c7f88",
    "grey": "#7c7f88",
}

DARK_COLOURS = {
    "red": "#f0837c",
    "green": "#8fd48f",
    "yellow": "#ecc06c",
    "blue": "#82aae0",
    "magenta": "#d69adf",
    "cyan": "#7fd4d4",
    "white": "#e6e6e1",
    "black": "#8b8f99",
    "grey": "#8b8f99",
}

MAX_OUTPUT_CHARS = 4_000_000

# How much of the window the run's own summary may take before it scrolls
# rather than pushing the output off the bottom.
HEADER_MAX_HEIGHT = 420


class RunView(Gtk.Box):
    """Renders a stored run, and follows a live one until it ends."""

    def __init__(
        self, on_cancel, on_relaunch=None, steps_of=None, on_open=None, notice_task=None
    ) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_cancel = on_cancel
        self._on_relaunch = on_relaunch or (lambda _id, _failures=False: None)
        # What else ran as part of the same launch, and how to open one.
        self._steps_of = steps_of or (lambda _sequence: [])
        self._on_open = on_open or (lambda _id: None)
        # Which task says what a run told the outside world, from the config.
        self._notice_task = notice_task or (lambda: "")
        self._run: Run | None = None
        self._active = None
        self._follow_thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._stick = True
        self._elapsed: Gtk.Label | None = None
        self._ticker: int = 0
        # What the run is doing now, read from what it has printed. `parse`
        # only ever ran at the end, so a live run said nothing about itself.
        self._doing = w.label("", "metric-detail", wrap=True)
        self._doing.set_visible(False)

        # A run that asks for a vault password used to sit on a prompt nobody
        # could see. The value goes to the process and to no store at all.
        self._asked = Adw.PasswordEntryRow(title="Vault password")
        self._asked.connect("entry-activated", lambda *_: self._answer())
        send = Gtk.Button(label="Send", valign=Gtk.Align.CENTER)
        send.add_css_class("suggested-action")
        send.connect("clicked", lambda *_: self._answer())
        self._asked.add_suffix(send)
        self._asking = Adw.PreferencesGroup(
            description="Typed into the run and nowhere else: not the history, "
            "not the output, not this machine."
        )
        self._asking.add(self._asked)
        self._asking.set_visible(False)

        self._header = w.box(spacing=14)
        self._buffer = Gtk.TextBuffer()
        self._view = Gtk.TextView(
            buffer=self._buffer,
            editable=False,
            cursor_visible=False,
            monospace=True,
            wrap_mode=Gtk.WrapMode.WORD_CHAR,
        )
        self._view.add_css_class("console-output")
        self._make_tags()

        self._matches: list[tuple[int, int]] = []
        self._at_match = -1
        self._find = Gtk.SearchEntry(placeholder_text="Find in this output")
        self._find.connect("search-changed", lambda *_: self._search(0))
        self._find.connect("next-match", lambda *_: self._search(1))
        self._find.connect("previous-match", lambda *_: self._search(-1))
        self._find.connect("activate", lambda *_: self._search(1))
        self._found = w.label("", "metric-detail")
        self._found.set_valign(Gtk.Align.CENTER)
        finder_row = w.box(Gtk.Orientation.HORIZONTAL, 8)
        self._find.set_hexpand(True)
        finder_row.append(self._find)
        finder_row.append(self._found)
        self._finder = Gtk.SearchBar(child=finder_row)
        self._finder.connect_entry(self._find)

        self._scroller = Gtk.ScrolledWindow(child=self._view, vexpand=True)
        self._scroller.get_vadjustment().connect("value-changed", self._on_scrolled)

        # An empty terminal is a black rectangle that says nothing. This says
        # whether the silence is a run still starting or a run that printed
        # nothing at all.
        self._placeholder = w.label("", "console-placeholder", xalign=0.5, wrap=True)
        self._placeholder.set_valign(Gtk.Align.CENTER)
        self._placeholder.set_halign(Gtk.Align.CENTER)
        overlay = Gtk.Overlay(child=self._scroller)
        overlay.add_overlay(self._placeholder)

        # The header grew: facts, the command, what the run told, the other
        # steps of its launch, the recap, the failures, and it sits above an
        # output pane that fills what is left. Together they came to demand
        # more height than the window has, which the toast overlay reports as
        # exceeding it. It scrolls on its own now and never asks for more.
        heading = Gtk.ScrolledWindow(
            child=self._header,
            hscrollbar_policy=Gtk.PolicyType.NEVER,
            propagate_natural_height=True,
            max_content_height=HEADER_MAX_HEIGHT,
        )

        body = w.box(spacing=16)
        body.append(heading)
        body.append(self._asking)
        body.append(self._doing)
        body.append(self._finder)
        frame = Gtk.Frame(child=overlay)
        frame.set_vexpand(True)
        body.append(frame)

        outer = w.clamp(body, maximum=1100)
        outer.set_vexpand(True)
        self.append(outer)

    def _make_tags(self) -> None:
        dark = Adw.StyleManager.get_default().get_dark()
        palette = DARK_COLOURS if dark else TAG_COLOURS
        table = self._buffer.get_tag_table()
        for name, colour in palette.items():
            if table.lookup(name) is None:
                self._buffer.create_tag(name, foreground=colour)
        if table.lookup("bold") is None:
            self._buffer.create_tag("bold", weight=Pango.Weight.BOLD)
        if table.lookup("dim") is None:
            self._buffer.create_tag("dim", foreground_rgba=_muted())
        if table.lookup("match") is None:
            self._buffer.create_tag("match", background="#f2c744", foreground="#1c1c1c")
        if table.lookup("here") is None:
            self._buffer.create_tag("here", background="#e0685f", foreground="#ffffff")

    def _on_scrolled(self, adjustment) -> None:
        at_end = adjustment.get_value() + adjustment.get_page_size() >= adjustment.get_upper() - 40
        self._stick = at_end

    def show(self, run: Run, output: str, active=None) -> None:
        """Displays a run; if `active` is given, follows it to completion."""
        self.stop()
        self._run = run
        self._active = active
        self._stick = True
        self._buffer.set_text("")
        self._append(output)
        self._rebuild_header()
        self._show_placeholder()
        self._show_doing()
        self._show_asking()
        self._clear_matches()
        self._find.set_text("")

        if active is not None and not active.finished:
            self._stop.clear()
            self._follow_thread = threading.Thread(
                target=self._follow, args=(active,), daemon=True, name=f"view-{run.id}"
            )
            self._follow_thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._stop_ticking()
        self._follow_thread = None

    def _follow(self, active) -> None:
        for chunk in active.stream():
            if self._stop.is_set():
                return
            if chunk:
                GLib.idle_add(self._append, chunk)
        GLib.idle_add(self._finished)

    def _finished(self) -> bool:
        if self._run is not None and self._active is not None:
            self._run = self._active.run
            self._rebuild_header()
        self._show_placeholder()
        self._show_doing()
        self._show_asking()
        return False

    def _show_placeholder(self) -> None:
        """What the empty pane says, which depends on whether it is still filling."""
        if self._buffer.get_char_count():
            self._placeholder.set_visible(False)
            return
        live = self._run is not None and self._run.state == "running"
        self._placeholder.set_text(
            "Waiting for the first line…"
            if live
            else "This run printed nothing.\nThe result above is everything it reported."
        )
        self._placeholder.set_visible(True)

    def _append(self, text: str) -> bool:
        if not text:
            return False
        buffer = self._buffer
        if buffer.get_char_count() > MAX_OUTPUT_CHARS:
            return False
        for segment in ansi.segments(text):
            end = buffer.get_end_iter()
            if segment.styles:
                buffer.insert_with_tags_by_name(end, segment.text, *segment.styles)
            else:
                buffer.insert(end, segment.text)
        if self._stick:
            GLib.idle_add(self._scroll_to_end)
        self._placeholder.set_visible(False)
        self._show_doing()
        self._show_asking()
        return False

    def _answer(self) -> None:
        secret = self._asked.get_text()
        if not secret or self._active is None:
            return
        self._active.answer(secret)
        # Cleared straight away: a password sitting in a field is one somebody
        # walks away from.
        self._asked.set_text("")
        self._show_asking()

    def _show_asking(self) -> None:
        asked = self._active.asking if self._active is not None else ""
        self._asking.set_visible(bool(asked))
        if asked:
            self._asked.set_title(asked.rstrip(":"))
            self._asked.grab_focus()

    def _text(self) -> str:
        buffer = self._buffer
        return buffer.get_text(buffer.get_start_iter(), buffer.get_end_iter(), False)

    def _show_doing(self) -> None:
        """Only while it is alive: when it ends, the recap says more than this could."""
        run = self._run
        if run is None or run.state != "running":
            self._doing.set_visible(False)
            return
        where = summary_module.progress(self._text())
        self._doing.set_visible(where.known)
        self._doing.set_text(where.summary)

    # --- finding a line in a run that printed hundreds ---

    def find(self) -> None:
        """Opens the search bar and puts the cursor in it."""
        self._finder.set_search_mode(True)
        self._find.grab_focus()

    def _search(self, step: int) -> None:
        needle = self._find.get_text()
        if not needle:
            self._clear_matches()
            return
        if step == 0 or not self._matches:
            self._collect(needle)
            self._at_match = 0 if self._matches else -1
        elif self._matches:
            self._at_match = (self._at_match + step) % len(self._matches)
        self._show_match()

    def _collect(self, needle: str) -> None:
        self._clear_matches()
        buffer = self._buffer
        start = buffer.get_start_iter()
        while True:
            found = start.forward_search(needle, Gtk.TextSearchFlags.CASE_INSENSITIVE, None)
            if found is None:
                break
            begin, end = found
            buffer.apply_tag_by_name("match", begin, end)
            self._matches.append((begin.get_offset(), end.get_offset()))
            start = end

    def _clear_matches(self) -> None:
        buffer = self._buffer
        buffer.remove_tag_by_name("match", buffer.get_start_iter(), buffer.get_end_iter())
        buffer.remove_tag_by_name("here", buffer.get_start_iter(), buffer.get_end_iter())
        self._matches = []
        self._at_match = -1
        self._found.set_text("")

    def _show_match(self) -> None:
        if not self._matches:
            self._found.set_text("No matches")
            return
        buffer = self._buffer
        buffer.remove_tag_by_name("here", buffer.get_start_iter(), buffer.get_end_iter())
        begin_at, end_at = self._matches[self._at_match]
        begin = buffer.get_iter_at_offset(begin_at)
        end = buffer.get_iter_at_offset(end_at)
        buffer.apply_tag_by_name("here", begin, end)
        # Following a match means leaving the end, or every step would be
        # undone by the next line the run prints.
        self._stick = False
        self._view.scroll_to_iter(begin, 0.2, False, 0.0, 0.5)
        self._found.set_text(f"{self._at_match + 1} of {len(self._matches)}")

    def _scroll_to_end(self) -> bool:
        adjustment = self._scroller.get_vadjustment()
        adjustment.set_value(adjustment.get_upper() - adjustment.get_page_size())
        return False

    def _start_ticking(self) -> None:
        self._stop_ticking()
        self._tick()
        self._ticker = GLib.timeout_add_seconds(1, self._tick)

    def _stop_ticking(self) -> None:
        if self._ticker:
            GLib.source_remove(self._ticker)
            self._ticker = 0

    def _tick(self) -> bool:
        run = self._run
        if run is None or run.state != "running" or self._elapsed is None:
            self._ticker = 0
            return False
        seconds = since(run.started)
        self._elapsed.set_text(f"running {took(seconds) or 'now'}")
        # A prompt is the case where output stops, so nothing arriving is
        # exactly when it has to be noticed. The clock is already ticking.
        self._show_asking()
        return True

    def _rebuild_header(self) -> None:
        self._stop_ticking()
        self._elapsed = None
        # Everything below is about to be disposed, and some of it is
        # selectable: focus has to leave first or GTK walks a dead widget.
        w.release_focus(self._header)
        child = self._header.get_first_child()
        while child is not None:
            self._header.remove(child)
            child = self._header.get_first_child()
        run = self._run
        if run is None:
            return

        title_row = w.box(Gtk.Orientation.HORIZONTAL, 10)
        name = w.label(run.name)
        name.add_css_class("title-2")
        title_row.append(name)
        title_row.append(w.state_badge(run.state))
        if run.state == "running":
            spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
            title_row.append(spinner)
            # How long it has been going. A run with no elapsed time is one
            # nobody can tell apart from a run that has hung.
            self._elapsed = w.label("", "numeric", "tint-muted")
            self._elapsed.set_valign(Gtk.Align.CENTER)
            title_row.append(self._elapsed)
            self._start_ticking()
            cancel = Gtk.Button(label="Cancel", valign=Gtk.Align.CENTER)
            cancel.add_css_class("destructive-action")
            cancel.set_halign(Gtk.Align.END)
            cancel.set_hexpand(True)
            cancel.connect("clicked", lambda *_: self._on_cancel(run.id))
            title_row.append(cancel)
        else:
            title_row.append(_relaunch_buttons(run, self._on_relaunch))
        self._header.append(title_row)

        self._header.append(
            _facts(
                [
                    ("Environment", run.environment, ""),
                    ("Built on", run.builder, ""),
                    ("Started", moment(run.started), run.started),
                    ("Took", took(run.duration_s), ""),
                    ("Exit", str(run.exit_code) if run.exit_code is not None else "", ""),
                    ("By", run.actor, ""),
                ]
            )
        )
        self._header.append(_command_strip(run.command))

        alongside = self._steps_of(run.sequence)
        if len(alongside) > 1:
            # Folded: the other steps are context for this one, and open they
            # pushed what the run actually told below the fold.
            section = w.Section(f"Part of one launch: {len(alongside)} steps", folded=True)
            section.set_child(_alongside(run, alongside, self._on_open))
            self._header.append(section)

        told = notices.read(self._text(), self._notice_task())
        if told.any:
            self._header.append(_told(told))

        result = run.result
        if result.has_recap:
            self._header.append(_recap(result))
        if result.failures:
            self._header.append(_failures(result))


def _told(told) -> Gtk.Widget:
    """What this run told the outside world, and which of it got through.

    Every one of these is `failed_when: false` in the playbook, so a webhook
    that never landed costs a deploy nothing and is invisible unless something
    looks. This is the something.
    """
    missed = len(told.missed)
    group = Adw.PreferencesGroup(
        title=f"Told the outside world: {told.summary}",
        description=(
            "A notification that did not land costs the deploy nothing, which is "
            "why it goes unnoticed."
            if missed
            else None
        ),
    )
    for notice in told.notices:
        row = Adw.ActionRow(title=notice.name, subtitle=notice.detail)
        row.set_subtitle_lines(2)
        row.add_prefix(w.dot({"landed": "ok", "missed": "bad"}.get(notice.state, "muted")))
        if notice.state == "missed":
            row.add_suffix(w.badge("DID NOT LAND", "high"))
        group.add(row)
    return group


def _alongside(run: Run, steps: list[Run], on_open) -> Gtk.Widget:
    """The other steps of the same launch, in the order they ran.

    A runbook writes four records: its checks, its precheck, the operation and
    its postcheck, and without this the only thing relating them is the clock.
    """
    group = Adw.PreferencesGroup(description="Every step of this runbook, in the order it ran.")
    for step in steps:
        row = Adw.ActionRow(
            title=step.name,
            subtitle=f"{language.run_kind(step.kind)} · "
            f"{took(step.duration_s) or 'under a second'}",
        )
        row.add_prefix(w.state_icon(step.state))
        if step.id == run.id:
            row.add_suffix(w.badge("THIS ONE", "ok"))
        else:
            row.set_activatable(True)
            row.connect("activated", lambda _r, one=step.id: on_open(one))
            row.add_suffix(Gtk.Image.new_from_icon_name("go-next-symbolic"))
        group.add(row)
    return group


def _relaunch_buttons(run: Run, on_relaunch) -> Gtk.Widget:
    """Run it again, and, where the recap named hosts that failed, only those."""
    row = w.box(Gtk.Orientation.HORIZONTAL, 8)
    row.set_halign(Gtk.Align.END)
    row.set_hexpand(True)
    row.set_valign(Gtk.Align.CENTER)

    failures = relaunch.failed_hosts(run)
    if failures and relaunch.against_failures(run).possible:
        only = Gtk.Button(label=f"Run again on the {plural(len(failures), 'host')} that failed")
        only.set_tooltip_text(", ".join(failures))
        only.connect("clicked", lambda *_: on_relaunch(run.id, True))
        row.append(only)

    again = Gtk.Button(label="Run again")
    again.add_css_class("suggested-action")
    again.set_tooltip_text("The same command, from what this run recorded")
    again.connect("clicked", lambda *_: on_relaunch(run.id, False))
    row.append(again)
    return row


def _facts(facts: list[tuple[str, str, str]]) -> Gtk.Widget:
    """Labelled values rather than one comma-joined blob.

    Each carries the exact figure as a tooltip where it has one, so nothing is
    lost by saying `today at 13:27` instead of the stamp it came from.
    """
    row = w.box(Gtk.Orientation.HORIZONTAL, 26)
    for name, value, exact in facts:
        if not value:
            continue
        cell = w.box(spacing=1)
        cell.append(w.label(name.upper(), "metric-label"))
        cell.append(w.selectable(w.label(value, "numeric")))
        if exact:
            cell.set_tooltip_text(exact)
        row.append(cell)
    return row


def _command_strip(command: str) -> Gtk.Widget:
    strip = w.box(Gtk.Orientation.HORIZONTAL, 10)
    strip.add_css_class("command-strip")
    inner = w.box(spacing=1, hexpand=True)
    inner.append(w.label("COMMAND", "metric-label"))
    # Selectable, because the header clears focus before it tears itself down.
    # The copy button stays: selecting a wrapped command by hand is worse.
    text = w.selectable(w.label(command, "numeric", wrap=True))
    text.add_css_class("monospace")
    inner.append(text)
    strip.append(inner)

    copy = Gtk.Button(icon_name="edit-copy-symbolic", valign=Gtk.Align.CENTER)
    copy.set_tooltip_text("Copy: paste this into a terminal if the app is unavailable")
    copy.add_css_class("flat")
    copy.connect("clicked", lambda *_: _copy(command))
    strip.append(copy)
    return strip


def _copy(text: str) -> None:
    display = Gdk.Display.get_default()
    if display is not None:
        display.get_clipboard().set(text)


def _recap(result) -> Gtk.Widget:
    group = Adw.PreferencesGroup(title=f"Result: {result.headline}")
    for host in result.hosts:
        row = Adw.ActionRow(
            title=host.host,
            subtitle=(
                f"ok {host.ok} · changed {host.changed} · failed {host.failed} · "
                f"unreachable {host.unreachable} · skipped {host.skipped}"
            ),
        )
        icon = Gtk.Image.new_from_icon_name(
            "dialog-error-symbolic" if host.bad else "emblem-ok-symbolic"
        )
        icon.add_css_class("tint-bad" if host.bad else "tint-ok")
        row.add_prefix(icon)
        group.add(row)
    return group


def _failures(result) -> Gtk.Widget:
    group = Adw.PreferencesGroup(title="Failures")
    for failure in result.failures:
        row = Adw.ActionRow(
            title=f"{failure.host}: {failure.task}",
            subtitle=failure.message or failure.kind,
        )
        row.set_subtitle_lines(4)
        # What a person came here to take away: the message a host printed.
        row.set_subtitle_selectable(True)
        icon = Gtk.Image.new_from_icon_name("dialog-error-symbolic")
        icon.add_css_class("tint-bad")
        row.add_prefix(icon)
        group.add(row)
    if result.truncated_failures:
        group.add(Adw.ActionRow(title=f"… and {result.truncated_failures} more"))
    return group


def _muted():
    rgba = Gdk.RGBA()
    rgba.parse("#8b8f99")
    return rgba
