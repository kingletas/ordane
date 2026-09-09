"""Runs: what happened, folded so a busy day is still readable, and one run open.

The list on the left applies the density rules with a day heading over each
group and one rolled row per day. Its default filter never hides a failure, a
change or a run somebody launched by hand, so nothing that matters is behind a
toggle.

The pane on the right is the run itself, which is where the shape of a run and
its output live.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gio, GLib, Gtk  # noqa: E402

from ..insight import density  # noqa: E402
from ..insight import runs as runs_module  # noqa: E402
from ..presentation.text import clock, moment, plural  # noqa: E402
from ..record.store import Run  # noqa: E402
from . import widgets as w  # noqa: E402

LIST_WIDTH = 296

WORTH_A_LOOK = "worth"
EVERYTHING = "everything"

# How many days of history the list draws. Beyond this a person is searching,
# and the terminal front end is the better tool for it.
DAYS_SHOWN = 14

# How many decisions the panel under the list prints before it counts the rest.
DECISIONS_SHOWN = 12

DECISION_ICONS = {
    "ref": "media-playlist-repeat-symbolic",
    "environments": "preferences-system-symbolic",
    "objectives": "emblem-ok-symbolic",
}


class RunsPage(Gtk.Box):
    """The list and the detail pane, side by side."""

    def __init__(self, *, detail: Gtk.Widget, on_open, on_relaunch=None) -> None:
        super().__init__(orientation=Gtk.Orientation.HORIZONTAL, spacing=16)
        self._on_open = on_open
        self._on_relaunch = on_relaunch
        self._density = WORTH_A_LOOK
        self._question = runs_module.ALL
        self._chosen = ""
        self._rows: dict[str, Gtk.Widget] = {}
        self._signature: tuple | None = None
        self._runs: list[Run] = []
        self._taken: list = []

        column = w.box(spacing=16)
        column.set_size_request(LIST_WIDTH, -1)
        self._list = w.card()
        column.append(self._list)
        self._decisions = w.box(spacing=8)
        column.append(self._decisions)
        self.append(w.scrolled(_padded(column)))

        detail.set_hexpand(True)
        self.append(detail)

    # --- what the window tells it ---

    def render(self, runs: list[Run], decisions: list) -> None:
        signature = (
            tuple((r.id, r.state, r.duration_s) for r in runs),
            self._density,
            self._question,
            self._chosen,
            tuple(d.summary for d in decisions[:DECISIONS_SHOWN]),
        )
        if signature == self._signature:
            return
        self._signature = signature
        self._runs = list(runs)
        self._taken = list(decisions)
        self._draw(runs)
        self._draw_decisions(decisions)

    def chosen(self) -> str:
        return self._chosen

    def ask(self, question: str) -> None:
        """Which of the four questions the history is being asked."""
        self._question = question
        self._signature = None
        self._draw(self._runs)

    def select(self, run_id: str) -> None:
        """Marks a run as the one being read, without reopening it."""
        self._chosen = run_id
        for key, widget in self._rows.items():
            if key == run_id:
                widget.add_css_class("chosen")
            else:
                widget.remove_css_class("chosen")

    # --- the list ---

    def _draw(self, runs: list[Run]) -> None:
        w.clear(self._list)
        self._rows = {}
        self._list.append(self._filters())

        kept = runs_module.apply(runs, self._question)
        if not kept:
            self._list.append(_quiet(runs_module.by_key(self._question).empty, last=True))
            return

        drawn = 0
        days = density.by_day(kept)
        for heading, day_runs in days[:DAYS_SHOWN]:
            self._list.append(_day_label(heading, len(day_runs)))
            rows = (
                density.fold(day_runs, under_a_day=True)
                if self._density == WORTH_A_LOOK
                else [
                    density.Row(
                        run=run,
                        state=density.outcome(run),
                        word=density.outcome_word(run),
                        action=run.name,
                        environment=run.environment,
                        note=density.note(run),
                        when=clock(run.started),
                    )
                    for run in day_runs
                ]
            )
            for item in rows:
                if item.kind == "rolled":
                    self._list.append(self._rolled(item))
                else:
                    self._list.append(self._item(item))
                drawn += 1
        older = sum(len(one) for _, one in days[DAYS_SHOWN:])
        if older:
            # Nothing is lost, only not drawn — and the command that prints the
            # rest is named rather than left to be found.
            self._list.append(
                _quiet(
                    f"{plural(older, 'older run')} not shown. Every one of them is in "
                    f"the history file, and `ordane runs -n {len(kept)}` prints them."
                )
            )
        if drawn:
            last = self._list.get_last_child()
            if last is not None:
                last.add_css_class("last")

    def _filters(self) -> Gtk.Widget:
        line = w.row(9)
        line.add_css_class("card-head")
        line.set_margin_top(9)
        line.set_margin_bottom(9)
        line.set_margin_start(11)
        line.set_margin_end(11)

        seg = w.row(2)
        seg.add_css_class("seg")
        seg.set_hexpand(True)
        for key, name in ((WORTH_A_LOOK, "Worth a look"), (EVERYTHING, "Everything")):
            button = Gtk.Button(label=name, hexpand=True)
            button.add_css_class("flat")
            if key == self._density:
                button.add_css_class("chosen")
            button.connect("clicked", lambda _b, one=key: self._choose_density(one))
            seg.append(button)
        line.append(seg)
        line.append(self._question_button())
        return line

    def _question_button(self) -> Gtk.Widget:
        """The four questions the history is asked, kept beside the two-way filter."""
        menu = Gio.Menu()
        for one in runs_module.FILTERS:
            item = Gio.MenuItem.new(one.label, None)
            item.set_action_and_target_value("win.runs-filter", GLib.Variant.new_string(one.key))
            menu.append_item(item)
        button = Gtk.MenuButton(
            icon_name="view-more-symbolic", menu_model=menu, valign=Gtk.Align.CENTER
        )
        button.add_css_class("iconbtn")
        button.set_tooltip_text(
            f"Showing: {runs_module.by_key(self._question).label}. "
            "Ask the history a different question"
        )
        return button

    def _item(self, item: density.Row) -> Gtk.Widget:
        line = w.box(spacing=3)
        top = w.row(8)
        top.append(w.pill("", item.state))
        name = w.label(
            f"{item.action} → {item.environment}" if item.environment else item.action,
            "runitem-name",
            "mono",
        )
        name.set_ellipsize(3)
        name.set_hexpand(True)
        top.append(name)
        top.append(w.label(item.when, "actrow-when", "num"))
        line.append(top)
        if item.note:
            note = w.label(item.note, "runitem-meta", wrap=True)
            line.append(note)

        button = Gtk.Button(child=line)
        button.add_css_class("runitem")
        button.add_css_class("flat")
        if item.run.id == self._chosen:
            button.add_css_class("chosen")
        button.set_tooltip_text(f"Open {item.action}")
        button.connect("clicked", lambda *_, one=item.run.id: self._on_open(one))
        self._menu_for(button, item.run)
        self._rows[item.run.id] = button
        return button

    def _menu_for(self, widget: Gtk.Widget, run: Run) -> None:
        """A row that only answers a left click is hiding half of what it can do."""
        entries = [("Open this run", lambda: self._on_open(run.id))]
        if self._on_relaunch is not None and run.state != "running":
            entries.append(("Run it again", lambda: self._on_relaunch(run.id, False)))
        entries += [
            ("Copy the command", lambda: w.copy_to_clipboard(run.command)),
            ("Copy the run id", lambda: w.copy_to_clipboard(run.id)),
        ]
        w.attach_context_menu(widget, entries)

    def _rolled(self, item: density.Rolled) -> Gtk.Widget:
        holder = w.box(spacing=0)
        line = w.row(8)
        caret = Gtk.Image.new_from_icon_name("pan-end-symbolic")
        line.append(caret)
        line.append(
            w.label(
                f"{plural(item.count, 'routine run')}, all passed — {', '.join(item.actions)}",
                "runitem-meta",
                wrap=True,
            )
        )

        inside = w.box(spacing=0)
        revealer = Gtk.Revealer(
            transition_type=Gtk.RevealerTransitionType.NONE, reveal_child=False, child=inside
        )

        def toggle() -> None:
            opening = not revealer.get_reveal_child()
            if opening and inside.get_first_child() is None:
                for run in item.runs:
                    inside.append(
                        self._item(
                            density.Row(
                                run=run,
                                state="ok",
                                word="Passed",
                                action=run.name,
                                environment=run.environment,
                                note=density.note(run),
                                when=clock(run.started),
                            )
                        )
                    )
            revealer.set_reveal_child(opening)
            caret.set_from_icon_name("pan-down-symbolic" if opening else "pan-end-symbolic")

        button = Gtk.Button(child=line)
        button.add_css_class("runitem")
        button.add_css_class("flat")
        button.set_tooltip_text(f"Show the {item.count} folded runs")
        button.connect("clicked", lambda *_: toggle())
        holder.append(button)
        holder.append(revealer)
        return holder

    def _choose_density(self, key: str) -> None:
        """Redraws at once: a filter that waits for the next tick reads as broken."""
        self._density = key
        self._signature = None
        self._draw(self._runs)

    # --- what was changed, which is a different history from what was run ---

    def _draw_decisions(self, decisions: list) -> None:
        w.clear(self._decisions)
        if not decisions:
            return
        self._decisions.append(w.band("Decisions", "what was changed here, and by whom"))
        card = w.card()
        for index, decision in enumerate(decisions[:DECISIONS_SHOWN]):
            card.append(_decision_row(decision, last=index == len(decisions[:DECISIONS_SHOWN]) - 1))
        if len(decisions) > DECISIONS_SHOWN:
            card.append(_quiet(f"and {len(decisions) - DECISIONS_SHOWN} more", last=True))
        self._decisions.append(card)


def _decision_row(decision, last: bool) -> Gtk.Widget:
    line = w.row(10)
    line.add_css_class("obj-row")
    if last:
        line.add_css_class("last")
    icon = Gtk.Image.new_from_icon_name(DECISION_ICONS.get(decision.kind, "emblem-system-symbolic"))
    icon.set_valign(Gtk.Align.START)
    if decision.widened:
        icon.add_css_class("tint-warn")
    line.append(icon)
    text = w.box(spacing=2, hexpand=True)
    text.append(w.label(decision.summary, "runitem-name", wrap=True))
    text.append(w.label(f"{decision.actor} · {moment(decision.at)}", "runitem-meta"))
    line.append(text)
    if decision.widened:
        line.append(w.pill("Widened", "warn"))
    return line


def _day_label(heading: str, count: int) -> Gtk.Widget:
    line = w.row(8)
    line.add_css_class("daylabel")
    line.append(w.label(heading))
    line.append(w.spacer())
    counted = w.label(plural(count, "run"), "count", "mono")
    line.append(counted)
    return line


def _quiet(text: str, last: bool = False) -> Gtk.Widget:
    line = w.row(0)
    line.add_css_class("actrow")
    if last:
        line.add_css_class("last")
    line.append(w.label(text, "actrow-note", wrap=True))
    return line


def _padded(child: Gtk.Widget) -> Gtk.Widget:
    holder = w.box(spacing=0)
    holder.append(child)
    return holder
