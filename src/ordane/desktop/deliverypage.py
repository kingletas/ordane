"""Delivery: the four signals and the objectives, given a place of their own.

Overview keeps a summary of the two that are measured. This is where all four
live, each one either a figure with the range it was computed over, or a
dormant card saying in a sentence what would turn it on.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Gtk  # noqa: E402

from . import widgets as w  # noqa: E402

COLUMNS = 2

BOUNDARY = (
    "A restore is the deploy that followed a failed one — Ordane does not read an "
    "incident tracker, so this is deployment recovery rather than service recovery."
)


class DeliveryPage(Gtk.Box):
    """Four measures, then the objectives, then what none of it can see."""

    def __init__(self, *, on_remedy, on_go) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._on_remedy = on_remedy
        self._on_go = on_go
        self._body = w.box(spacing=24)
        self.append(w.scrolled(w.clamp(self._body)))
        self._signature: tuple | None = None

    def render(self, snapshot, scope: str = "") -> None:
        signature = (
            tuple((m.key, m.value, m.blocked) for m in snapshot.measures),
            tuple((s.label, s.value, s.blocked) for s in snapshot.slos),
            tuple(snapshot.cadence.values),
            tuple(snapshot.lead_time.values),
            tuple(snapshot.notes),
            scope,
        )
        if signature == self._signature:
            return
        self._signature = signature
        w.clear(self._body)

        self._body.append(
            w.band("The four delivery signals", scope or "every environment on record")
        )
        grid = Gtk.Grid(column_spacing=12, row_spacing=12, column_homogeneous=True)
        for index, measure in enumerate(snapshot.measures):
            series = None
            if measure.key == "cadence" and snapshot.cadence:
                series = snapshot.cadence
            elif measure.key == "lead_time" and snapshot.lead_time:
                series = snapshot.lead_time
            card = w.metric_card(measure, series, animate=False)
            card.set_valign(Gtk.Align.FILL)
            if not measure.has_data:
                card.append(self._turn_on(measure))
            grid.attach(card, index % COLUMNS, index // COLUMNS, 1, 1)
        self._body.append(grid)

        self._body.append(
            w.band(
                "Service objectives",
                f"{sum(1 for s in snapshot.slos if s.has_data)} of {len(snapshot.slos)} measured",
                w.linkish("Add an objective", lambda: self._on_remedy("edit-objectives")),
            )
        )
        if snapshot.slos:
            card = w.card()
            for index, slo in enumerate(snapshot.slos):
                card.append(
                    w.objective_row(
                        slo,
                        last=index == len(snapshot.slos) - 1,
                        on_fix=lambda: self._on_remedy("edit-objectives"),
                    )
                )
            self._body.append(card)
        else:
            self._body.append(
                w.dormant_note(
                    "An objective is a target with a window and a source. Without one "
                    "there is nothing here to be under or over.",
                    "Set one up",
                    lambda: self._on_remedy("edit-objectives"),
                )
            )

        self._body.append(_boundaries(snapshot.notes))

    def _turn_on(self, measure) -> Gtk.Widget:
        """The button that would fill this card, named for where it goes."""
        where, text = (
            ("actions", "Launch a deploy")
            if measure.key in ("failure_rate", "recovery")
            else ("setup", "See what it needs")
        )
        button = w.button(text, "quiet", lambda: self._on_go(where), small=True)
        button.set_halign(Gtk.Align.START)
        button.set_margin_top(12)
        return button


def _boundaries(notes: list[str]) -> Gtk.Widget:
    """What this page cannot see, in the copy rather than in fine print."""
    holder = w.box(spacing=8)
    holder.append(w.band("What these numbers do not cover"))
    card = w.card()
    for index, text in enumerate([*notes, BOUNDARY]):
        line = w.row(10)
        line.add_css_class("obj-row")
        if index == len(notes):
            line.add_css_class("last")
        icon = Gtk.Image.new_from_icon_name("dialog-information-symbolic")
        icon.set_valign(Gtk.Align.START)
        icon.add_css_class("tint-muted")
        line.append(icon)
        said = w.label(text, "actrow-note", wrap=True)
        said.set_hexpand(True)
        line.append(said)
        card.append(line)
    holder.append(card)
    return holder
