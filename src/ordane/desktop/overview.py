"""Overview: three bands, in the order a person actually asks the questions.

1. The verdict. One sentence at 29px saying whether it is safe to act, and one
   line naming the single thing standing in the way. Nothing else competes.
2. The instruments. The environments, the setup card while there is one, the
   delivery measures, the objectives.
3. Activity. What ran today, as a real block rather than behind a disclosure —
   the thing you actually did today used to be below the fold.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import GLib, Gtk  # noqa: E402

from ..insight import density  # noqa: E402
from ..insight import environments as env_module
from ..presentation.text import plural  # noqa: E402
from . import activity as activity_module  # noqa: E402
from . import widgets as w  # noqa: E402

# Three tiles fit across the well; beyond that they wrap, which is what a
# repository with six environments needs.
TILES_ACROSS = 3

# What the two dormant measures are waiting on, said once under the pair rather
# than twice inside them.
DORMANT_NOTE = (
    "Change failure rate and time to restore stay dark until a deploy is launched from "
    "Ordane. Nothing here reads an incident tracker — a restore is the deploy that "
    "followed a failed one."
)


class Overview(Gtk.Box):
    """Rebuilt from scratch when something changed; nothing here holds state."""

    def __init__(self, *, on_open_run, on_remedy, on_go) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_open_run = on_open_run
        self._on_remedy = on_remedy
        self._on_go = on_go
        self._body = w.box(spacing=30)
        self._scroller = w.scrolled(w.clamp(self._body))
        self._signature: tuple | None = None
        self.append(self._scroller)

    def render(self, *, catalog, snapshot, verdict, setup, runs, standings, animate=True) -> None:
        """Rebuilds only when something actually changed.

        The window refreshes on a timer. Rebuilding regardless would throw the
        reader's scroll position away every few seconds, which is worse than
        showing a figure a moment late.
        """
        signature = _signature(catalog, snapshot, verdict, setup, runs, standings)
        if signature == self._signature:
            return
        first = self._signature is None
        self._signature = signature
        # Building a page gives focus to its first focusable row, and a
        # scroller follows focus — so a refresh moved the reader down the page
        # every few seconds. The offset is put back once the layout settles.
        where = self._scroller.get_vadjustment().get_value()
        w.release_focus(self._body)
        w.clear(self._body)

        self._body.append(w.verdict_band(verdict, self._on_remedy))
        if standings:
            self._body.append(_tiles(standings))
        if not setup.complete:
            self._body.append(
                w.setup_card(
                    title=setup.headline(snapshot),
                    note=setup.sentence,
                    fraction=setup.fraction,
                    counted=setup.progress_text,
                    on_go=lambda: self._on_go("setup"),
                )
            )
        self._body.append(self._delivery(snapshot, animate and first))
        if snapshot.slos:
            self._body.append(self._objectives(snapshot))
        self._body.append(self._activity(runs))

        GLib.idle_add(self._restore, 0.0 if first else where)

    def _restore(self, where: float) -> bool:
        self._scroller.get_vadjustment().set_value(where)
        return False

    # --- the bands ---

    def _delivery(self, snapshot, animate: bool) -> Gtk.Widget:
        holder = w.box(spacing=11)
        holder.append(
            w.band(
                "Delivery",
                snapshot.cadence.caption or "from the release history and the runs recorded here",
                w.linkish("All four signals", lambda: self._on_go("delivery")),
            )
        )
        live = [measure for measure in snapshot.measures if measure.has_data]
        dark = [measure for measure in snapshot.measures if not measure.has_data]

        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        for index, measure in enumerate(live[:2]):
            series = snapshot.cadence if measure.key == "cadence" else snapshot.lead_time
            card = w.metric_card(measure, series if series else None, animate=animate)
            card.set_valign(Gtk.Align.FILL)
            grid.attach(card, index, 0, 1, 1)
        if live:
            holder.append(grid)
        if dark:
            holder.append(
                w.dormant_note(
                    DORMANT_NOTE if len(dark) > 1 else _one_dormant(dark[0]),
                    "Set them up" if len(dark) > 1 else "Set it up",
                    lambda: self._on_go("setup"),
                )
            )
        return holder

    def _objectives(self, snapshot) -> Gtk.Widget:
        measured = sum(1 for slo in snapshot.slos if slo.has_data)
        holder = w.box(spacing=11)
        holder.append(
            w.band(
                "Service objectives",
                f"{measured} of {len(snapshot.slos)} measured",
                w.linkish("Manage", lambda: self._on_remedy("edit-objectives")),
            )
        )
        card = w.card()
        for index, slo in enumerate(snapshot.slos):
            card.append(w.objective_row(slo, last=index == len(snapshot.slos) - 1))
        holder.append(card)
        return holder

    def _activity(self, runs) -> Gtk.Widget:
        holder = w.box(spacing=11)
        holder.append(
            w.band(
                "Recent runs",
                f"last {density.RIBBON_HOURS} hours",
                w.linkish("Full history", lambda: self._on_go("runs")),
            )
        )
        card = w.card()
        window = density.recent(runs, density.RIBBON_HOURS)
        if not window:
            card.append(_nothing_ran(bool(runs)))
            holder.append(card)
            return holder

        card.append(activity_module.ribbon_block(density.ribbon(runs)))
        rows = density.fold(window, ceiling=density.OVERVIEW_ROWS, under_a_day=True)
        card.append(
            activity_module.activity(
                rows, on_open=self._on_open_run, on_more=lambda: self._on_go("runs")
            )
        )
        holder.append(card)
        return holder


def _one_dormant(measure) -> str:
    from ..presentation import language

    name = language.measure_name(measure.key, measure.label)
    return f"{name} stays dark until it has a source. {measure.blocked}"


def _nothing_ran(has_history: bool) -> Gtk.Widget:
    holder = w.box(spacing=4)
    holder.set_margin_top(18)
    holder.set_margin_bottom(18)
    holder.set_margin_start(15)
    holder.set_margin_end(15)
    holder.append(
        w.label(
            "Nothing has run in the last day."
            if has_history
            else "Nothing has run through this console yet.",
            "actrow-what",
        )
    )
    holder.append(
        w.label(
            "The full history is on Runs."
            if has_history
            else "Every run recorded here fills a gap in the measures above.",
            "actrow-note",
        )
    )
    return holder


def _tiles(standings: list[env_module.Standing]) -> Gtk.Widget:
    grid = Gtk.Grid(column_spacing=10, row_spacing=10, column_homogeneous=True)
    for index, standing in enumerate(standings):
        tile = w.environment_tile(
            name=standing.name,
            state=standing.state,
            word=standing.word,
            facts=standing.facts,
            fix=standing.fix,
        )
        tile.set_valign(Gtk.Align.FILL)
        grid.attach(tile, index % TILES_ACROSS, index // TILES_ACROSS, 1, 1)
    return grid


def _signature(catalog, snapshot, verdict, setup, runs, standings) -> tuple:
    """Everything the page draws, reduced to something comparable."""
    return (
        verdict.state,
        verdict.headline,
        verdict.note,
        setup.done,
        setup.total,
        tuple((m.key, m.value, m.blocked) for m in snapshot.measures),
        tuple((s.label, s.value, s.blocked) for s in snapshot.slos),
        tuple(snapshot.cadence.values),
        tuple(snapshot.lead_time.values),
        tuple((s.name, s.state, s.word, s.host_count, s.when, s.changed_text) for s in standings),
        tuple((r.id, r.state, r.duration_s) for r in runs[: density.OVERVIEW_ROWS * 4]),
        len(runs),
        plural(len(catalog.targets) if catalog else 0, "target"),
    )
