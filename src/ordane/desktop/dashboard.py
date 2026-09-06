"""The health dashboard: a verdict first, then the evidence behind it."""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..insight import health as health_module  # noqa: E402
from ..insight.health import Health  # noqa: E402
from . import widgets as w  # noqa: E402
from .folding import Folding  # noqa: E402

CARD_MIN_WIDTH = 210
COLUMNS = 2

RECENT_SECTION = "recent-runs"


class Dashboard(Gtk.Box):
    """Rebuilt from scratch on every refresh; nothing here holds state."""

    def __init__(self, on_open_run, on_remedy=None, folding=None) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_open_run = on_open_run
        self._on_remedy = on_remedy or (lambda _name: None)
        self._folding = folding or Folding()
        self._body = w.box(spacing=22)
        self._scroller = w.scrolled(w.clamp(self._body))
        self._signature: tuple | None = None
        self.append(self._scroller)

    def render(self, *, catalog, snapshot, health: Health, runs, repo) -> None:
        """Rebuilds only when something actually changed.

        The window refreshes on a timer. Rebuilding regardless would throw the
        reader's scroll position away every few seconds, which is worse than
        showing a figure a moment late.
        """
        signature = _signature(catalog, snapshot, health, runs)
        if signature == self._signature:
            return
        first = self._signature is None
        self._signature = signature

        child = self._body.get_first_child()
        while child is not None:
            self._body.remove(child)
            child = self._body.get_first_child()

        self._body.append(_top_row(health, catalog, self._on_remedy))
        if len(health.problems + health.attention) > 1:
            self._body.append(_attention(health))
        self._body.append(_measures(snapshot))
        self._body.append(_objectives(snapshot))
        self._body.append(_recent(runs, self._on_open_run, self._folding))

        if first:
            # Building the page gives focus to its first focusable row, and the
            # scroller follows focus: landing below the verdict, which is the
            # one thing that has to be seen. Reset after the layout settles.
            GLib.idle_add(self._to_top)

    def _to_top(self) -> bool:
        self._scroller.get_vadjustment().set_value(0)
        return False


def _signature(catalog, snapshot, health: Health, runs) -> tuple:
    """Everything the page draws, reduced to something comparable."""
    return (
        health.level,
        health.headline,
        tuple((c.level, c.title, c.detail) for c in health.concerns),
        tuple((m.key, m.value, m.blocked) for m in snapshot.measures),
        tuple((s.label, s.value, s.blocked) for s in snapshot.slos),
        tuple(snapshot.cadence.values),
        tuple((e.name, e.blocked_reason) for e in catalog.environments),
        tuple((r.id, r.state, r.duration_s) for r in runs[:8]),
    )


def _top_row(health: Health, catalog, on_remedy) -> Gtk.Widget:
    """The two things to read first, side by side: the state, and the estate."""
    grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
    status = w.status_card(health, on_remedy)
    status.set_valign(Gtk.Align.FILL)
    grid.attach(status, 0, 0, 1, 1)
    environments = w.environment_card(catalog, lambda: on_remedy(health_module.CHOOSE_ENVIRONMENTS))
    environments.set_valign(Gtk.Align.FILL)
    grid.attach(environments, 1, 0, 1, 1)
    return grid


def _attention(health: Health) -> Gtk.Widget:
    """The operational concerns, when there is more than the one the card names.

    Measurement gaps are deliberately not here: a metric with no source is a
    setup state, and mixing the two makes a broken environment read like a
    missing integration.
    """
    group = Adw.PreferencesGroup(title="Attention required")
    for concern in health.problems + health.attention:
        group.add(_concern_row(concern))
    return group


def _concern_row(concern) -> Gtk.Widget:
    """What happened, then the evidence for it.

    The detail alone used to be the row, so a concern the status card was not
    naming arrived as a fragment: `90% against 95% over 90d`, of what.
    """
    row = Adw.ActionRow(title=concern.title)
    row.set_title_lines(2)
    under = " · ".join(part for part in (concern.detail, concern.hint) if part)
    if under:
        row.set_subtitle(under)
        row.set_subtitle_lines(3)
    row.add_prefix(_concern_icon(concern.level))
    return row


def _concern_icon(level: str) -> Gtk.Image:
    image = Gtk.Image.new_from_icon_name(w.VERDICT_ICON[level])
    image.add_css_class(w.VERDICT_TINT[level])
    return image


def _measures(snapshot) -> Gtk.Widget:
    holder = w.box(spacing=8)
    # The explanation used to be a sentence under the heading, competing with
    # the numbers. It is on the heading now, where somebody who wants it can
    # find it and everyone else is not reading past it.
    heading = w.heading("Delivery performance")
    heading.set_tooltip_text(
        "From the release history the reporter commits and the runs this console "
        "recorded. A card with no source says what would fill it."
    )
    holder.append(heading)

    grid = Gtk.Grid(row_spacing=10, column_spacing=10, column_homogeneous=True)
    for index, measure in enumerate(snapshot.measures):
        card = (
            w.metric_card_with_series(measure, snapshot.cadence)
            if measure.key == "cadence"
            else w.metric_card(measure)
        )
        card.set_size_request(CARD_MIN_WIDTH, -1)
        card.set_valign(Gtk.Align.FILL)
        grid.attach(card, index % COLUMNS, index // COLUMNS, 1, 1)
    holder.append(grid)
    return holder


def _objectives(snapshot) -> Gtk.Widget:
    measured = sum(1 for slo in snapshot.slos if slo.has_data)
    group = Adw.PreferencesGroup(
        title="Service objectives",
        description=f"{measured} of {len(snapshot.slos)} measured.",
    )
    edit_them = Gtk.Button(label="Set up…", valign=Gtk.Align.CENTER)
    edit_them.add_css_class("flat")
    edit_them.set_action_name("win.objectives")
    edit_them.set_tooltip_text("Add, change or remove an objective")
    group.set_header_suffix(edit_them)
    if not snapshot.slos:
        row = Adw.ActionRow(
            title="No objectives are declared",
            subtitle="An objective is a target this estate holds itself to. "
            "Set one up and it appears here with what measures it.",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("dialog-information-symbolic"))
        group.add(row)
        return group
    for slo in snapshot.slos:
        group.add(w.slo_row(slo))
    return group


def _recent(runs, on_open, folding) -> Gtk.Widget:
    section = w.Section(
        "Recent runs",
        folded=folding.is_folded(RECENT_SECTION),
        on_fold=lambda folded: folding.remember(RECENT_SECTION, folded),
    )
    group = Adw.PreferencesGroup()
    section.set_child(group)
    if not runs:
        row = Adw.ActionRow(
            title="Nothing has run through this console yet",
            subtitle="Every run recorded here fills a gap in the measures above.",
        )
        row.add_prefix(Gtk.Image.new_from_icon_name("document-open-recent-symbolic"))
        group.add(row)
        return section
    for run in runs[:8]:
        group.add(w.run_row(run, on_open))
    return section
