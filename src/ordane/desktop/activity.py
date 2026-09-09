"""What ran, drawn under the density rules rather than one line per run.

Four things on a row: the outcome, the action on its environment, the single
fact that explains the outcome, and when. No zeroes — an unchanged host count
and an unremarkable duration are left out rather than printed as `0`.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from ..insight import density  # noqa: E402
from ..presentation.text import plural  # noqa: E402
from . import widgets as w  # noqa: E402
from .chart import Ribbon as RibbonChart  # noqa: E402

# The outcome column, wide enough for the longest pill and no wider.
SLOT = 124

# The time column. Right-aligned, tabular, so a run of them reads as a column.
WHEN = 84


def ribbon_block(ribbon: density.Ribbon) -> Gtk.Widget:
    """A day of runs as ticks, and one line of prose giving the counts."""
    holder = w.box(spacing=0)
    holder.add_css_class("ribbon")
    holder.append(RibbonChart(ribbon.ticks))

    foot = w.row(6)
    foot.set_margin_top(8)
    foot.add_css_class("ribbon-foot")
    counted = w.label(plural(ribbon.total, "run"))
    counted.add_css_class("strong")
    counted.add_css_class("mono")
    foot.append(counted)
    if ribbon.since:
        foot.append(w.label(f"since {ribbon.since} — {ribbon.sentence}", wrap=True))
    foot.append(w.spacer())
    foot.append(w.label("now", "mono"))
    holder.append(foot)
    return holder


def activity(rows: list, *, on_open, on_more=None) -> Gtk.Widget:
    """The rows a list draws, with a rolled row that expands in place."""
    holder = w.box(spacing=0)
    for index, item in enumerate(rows):
        last = index == len(rows) - 1
        if item.kind == "run":
            holder.append(run_row(item, on_open, last=last))
        elif item.kind == "rolled":
            holder.append(_rolled(item, on_open, last=last))
        else:
            holder.append(_more(item, on_more, last=last))
    return holder


def run_row(item: density.Row, on_open, last: bool = False, indented: bool = False) -> Gtk.Widget:
    """One run that earned its own line."""
    line = w.row(14)
    line.add_css_class("actrow")
    if last:
        line.add_css_class("last")
    if indented:
        line.add_css_class("folded")
        line.set_margin_start(32)

    slot = w.box()
    slot.set_size_request(SLOT, -1)
    slot.set_valign(Gtk.Align.CENTER)
    slot.append(w.pill(item.word, item.state))
    line.append(slot)

    what = w.row(4)
    what.set_valign(Gtk.Align.CENTER)
    what.append(w.label(item.action, "actrow-what", "mono"))
    if item.environment:
        what.append(w.label("on", "actrow-what"))
        what.append(w.label(item.environment, "actrow-what", "mono"))
    line.append(what)
    line.append(w.spacer())

    if item.note:
        note = w.label(item.note, "actrow-note", xalign=1.0)
        note.set_ellipsize(3)
        note.set_valign(Gtk.Align.CENTER)
        line.append(note)

    when = w.label(item.when, "actrow-when", "num", xalign=1.0)
    when.set_size_request(WHEN, -1)
    when.set_valign(Gtk.Align.CENTER)
    line.append(when)

    return _clickable(line, lambda: on_open(item.run.id), f"Open {item.action}")


def _rolled(item: density.Rolled, on_open, last: bool = False) -> Gtk.Widget:
    """Consecutive routine passes, folded, with the count still on the page."""
    holder = w.box(spacing=0)

    line = w.row(14)
    line.add_css_class("actrow")
    line.add_css_class("roll")
    if last:
        line.add_css_class("last")

    slot = w.box()
    slot.set_size_request(SLOT, -1)
    slot.set_valign(Gtk.Align.CENTER)
    slot.append(w.pill(item.headline, "mute"))
    line.append(slot)

    caret = Gtk.Image.new_from_icon_name("pan-end-symbolic")
    caret.set_valign(Gtk.Align.CENTER)
    line.append(caret)
    line.append(w.label(item.what, "actrow-what"))
    line.append(w.spacer())
    line.append(w.label(item.note, "actrow-note", xalign=1.0))
    when = w.label(item.when, "actrow-when", "num", xalign=1.0)
    when.set_size_request(WHEN, -1)
    when.set_valign(Gtk.Align.CENTER)
    line.append(when)

    inside = w.box(spacing=0)
    revealer = Gtk.Revealer(
        transition_type=Gtk.RevealerTransitionType.NONE, reveal_child=False, child=inside
    )

    def toggle() -> None:
        opening = not revealer.get_reveal_child()
        if opening and inside.get_first_child() is None:
            _fill_rolled(inside, item, on_open)
        revealer.set_reveal_child(opening)
        caret.set_from_icon_name("pan-down-symbolic" if opening else "pan-end-symbolic")

    holder.append(_clickable(line, toggle, f"Show the {item.count} folded runs"))
    holder.append(revealer)
    return holder


def _fill_rolled(inside: Gtk.Widget, item: density.Rolled, on_open) -> None:
    """The folded runs, each still openable. Nothing is hidden, only folded."""
    shown = item.runs[: density.OVERVIEW_ROWS]
    medians: dict[str, float] = {}
    for run in shown:
        inside.append(
            run_row(
                density.Row(
                    run=run,
                    state="ok",
                    word="Passed",
                    action=run.name,
                    environment=run.environment,
                    note=density.note(run, medians.get(run.name)),
                    when=item.when,
                ),
                on_open,
                indented=True,
            )
        )
    left = item.count - len(shown)
    if left:
        rest = w.row(14)
        rest.add_css_class("actrow")
        rest.add_css_class("folded")
        rest.add_css_class("last")
        rest.set_margin_start(32)
        rest.append(w.label(f"{left} more, all the same", "actrow-note"))
        inside.append(rest)


def _more(item: density.More, on_more, last: bool = False) -> Gtk.Widget:
    line = w.row(14)
    line.add_css_class("actrow")
    if last:
        line.add_css_class("last")
    line.append(w.label(f"{item.count} more worth a look", "actrow-what"))
    line.append(w.spacer())
    line.append(Gtk.Image.new_from_icon_name("pan-end-symbolic"))
    return _clickable(line, on_more or (lambda: None), "Open the full history")


def _clickable(line: Gtk.Widget, run, tooltip: str) -> Gtk.Widget:
    """A row is a button, so it is reachable by keyboard as well as by mouse."""
    button = Gtk.Button(child=line)
    button.add_css_class("flat")
    button.add_css_class("actrow-holder")
    button.set_tooltip_text(tooltip)
    button.connect("clicked", lambda *_: run())
    for name in ("actrow", "roll", "last", "folded"):
        if line.has_css_class(name):
            button.add_css_class(name)
            line.remove_css_class(name)
    return button
