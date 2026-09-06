"""The Estate view: what the shared stores know that this machine does not.

**It is a separate view on purpose.** Health reads local files and works with
nothing running; this one needs two databases, so it fails on its own rather
than taking the console down with it. A store that is not there says so, and
every other view carries on.

Every query runs on a thread. A view that blocks the main loop on a network
call is a window that has hung, whatever it says in the status bar.
"""

from __future__ import annotations

import threading
import time

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, GLib, Gtk  # noqa: E402

from ..insight import estate as estate_module  # noqa: E402
from ..insight import stores as stores_module  # noqa: E402
from ..presentation.text import ago, plural  # noqa: E402
from . import chart as chart_module  # noqa: E402
from . import widgets as w  # noqa: E402

# How long an answer stands before showing this view asks again. Long enough
# that switching away and back is not five more network calls.
STALE_SECONDS = 120

# How many rows a table panel prints before it says how many it is holding
# back. A panel is a shape to read, not a page of the store.
ROWS_SHOWN = 4

WHERE_FROM = {
    estate_module.FROM_INFLUX: "InfluxDB",
    estate_module.FROM_NEO4J: "Neo4j",
}


class Estate(Gtk.Box):
    """One panel per question, each saying which store answered it."""

    def __init__(self) -> None:
        super().__init__(orientation=Gtk.Orientation.VERTICAL)
        self._body = w.box(spacing=22)
        self.append(w.scrolled(w.clamp(self._body)))
        self._loading = False
        self._asked_at = 0.0
        self._head: Gtk.Widget | None = None
        self._results: list = []
        self._on_copied = None
        self._stores = stores_module.Stores()
        self._show_unasked()

    # --- what it does ---

    def refresh(self, stores, force: bool = False) -> None:
        """Asks every panel, on a thread.

        Called again while loading does nothing, and called again after an answer does
        nothing unless asked to: switching to this view and back is not a reason to make
        five network calls.
        """
        if self._loading:
            return
        self._stores = stores
        if not stores.any:
            self._show_unconfigured()
            return
        if self._results and not force and time.monotonic() - self._asked_at < STALE_SECONDS:
            return
        self._loading = True
        self.show_waiting()
        threading.Thread(target=self._ask, args=(stores,), daemon=True, name="estate").start()

    def _ask(self, stores) -> None:
        results = estate_module.ask_all(stores, stores.influx_bucket)
        GLib.idle_add(self._render, results)

    def _render(self, results) -> bool:
        self._loading = False
        self._results = results
        self._asked_at = time.monotonic()
        self._clear()
        self._head = self._header(results)
        self._body.append(self._head)
        figures = estate_module.headline(results)
        if figures:
            self._body.append(_strip(figures))
        self._body.append(_panels(results))
        return False

    def _show_unasked(self) -> None:
        """Before anything has been asked. A spinner here would be a lie."""
        self._clear()
        self._body.append(
            w.empty(
                "The estate",
                "Years the local history does not cover, and questions no row can answer. "
                "Nothing has been asked yet.",
                "network-server-symbolic",
            )
        )

    def show_waiting(self) -> None:
        """An answer already on screen stays there; only a first ask gets a blank page."""
        if self._results:
            self._replace_head(self._asking_head())
            return
        self._clear()
        page = w.empty(
            "Asking the stores",
            "Every panel here is a question the local history cannot answer.",
            "content-loading-symbolic",
        )
        spinner = Gtk.Spinner(spinning=True)
        page.set_child(spinner)
        self._body.append(page)

    def _clear(self) -> None:
        """Empties the page and forgets the head with it, so nothing stale is removed twice."""
        _empty(self._body)
        self._head = None

    def _replace_head(self, head: Gtk.Widget) -> None:
        if self._head is not None:
            self._body.remove(self._head)
        self._head = head
        self._body.prepend(head)

    def _asking_head(self) -> Gtk.Widget:
        """What is on screen is the last answer, and it says so rather than vanishing."""
        holder = self._title_row()
        line = w.box(Gtk.Orientation.HORIZONTAL, 8)
        line.set_margin_top(2)
        spinner = Gtk.Spinner(spinning=True, valign=Gtk.Align.CENTER)
        line.append(spinner)
        line.append(
            w.label(
                f"Asking the stores again. Everything below was {ago(self._age(), 'answered')}.",
                "tint-muted",
                wrap=True,
            )
        )
        holder.append(line)
        return holder

    def _age(self) -> float:
        return time.monotonic() - self._asked_at

    def _show_unconfigured(self) -> None:
        """Not a dead end: the file to write, and a button that copies it."""
        self._clear()
        path = stores_module.settings_path()
        page = w.empty(
            "No shared store is pointed at yet",
            "This view reads a time-series store and a graph store: years the local "
            "history does not cover, and questions no row can answer.\n\n"
            f"Fill them in below and this view starts answering. They are written to {path}, "
            "which only this account can read. Nothing else in this console needs "
            "them: every other view reads files on this machine and works with nothing "
            "running.",
            "network-server-symbolic",
        )

        buttons = w.box(Gtk.Orientation.HORIZONTAL, 8)
        buttons.set_halign(Gtk.Align.CENTER)
        setup = Gtk.Button(label="Point at the stores…")
        setup.add_css_class("suggested-action")
        setup.add_css_class("pill")
        setup.set_tooltip_text(f"Fill them in here: written to {path}")
        setup.set_action_name("win.stores")
        buttons.append(setup)

        copy = Gtk.Button(label="Copy the template")
        copy.add_css_class("pill")
        copy.set_tooltip_text("For a machine where the file is written by hand")
        copy.connect("clicked", lambda *_: self._copy_template())
        buttons.append(copy)
        page.set_child(buttons)
        self._body.append(page)

    def _copy_template(self) -> None:
        w.copy_to_clipboard(stores_module.TEMPLATE)
        if self._on_copied is not None:
            self._on_copied(f"Template copied: paste it into {stores_module.settings_path()}")

    def _title_row(self, lede: str = "") -> Gtk.Box:
        again = Gtk.Button(label="Ask again")
        again.set_tooltip_text("These are network calls, so they are made when you ask")
        again.connect("clicked", lambda *_: self.refresh(self._stores, force=True))
        return w.page_header("The estate", lede, again)

    def _header(self, results) -> Gtk.Widget:
        """What answered, what did not, and the way to ask again."""
        answered = [r for r in results if r.ok]
        failed = [r for r in results if not r.ok]
        if failed:
            # Which half still stands, in the same breath as the half that did
            # not: a partial answer is worth more than a page of nothing.
            holder = self._title_row()
            holder.append(
                w.label(
                    f"{plural(len(answered), 'panel')} answered; "
                    f"{len(failed)} could not reach a store. "
                    "What is below came from the store that did answer.",
                    "tint-warn",
                    wrap=True,
                )
            )
            return holder
        return self._title_row(
            "Years the local history does not cover, and questions no row can answer. "
            f"{ago(self._age(), 'Asked')}."
        )


def _strip(figures) -> Gtk.Widget:
    """The headline numbers, in a row that reflows rather than a fixed two columns."""
    flow = Gtk.FlowBox(
        selection_mode=Gtk.SelectionMode.NONE,
        homogeneous=True,
        min_children_per_line=2,
        max_children_per_line=len(figures),
        column_spacing=12,
        row_spacing=12,
    )
    for figure in figures:
        flow.append(_figure_card(figure))
    return flow


def _figure_card(figure) -> Gtk.Widget:
    card = w.box(spacing=3)
    card.add_css_class("metric-card")
    card.append(w.label(figure.kicker, "metric-label"))

    line = w.box(Gtk.Orientation.HORIZONTAL, 4)
    line.append(w.label(figure.value, "metric-value", "numeric"))
    if figure.unit:
        unit = w.label(figure.unit, "metric-detail")
        unit.set_valign(Gtk.Align.END)
        unit.set_margin_bottom(6)
        line.append(unit)
    card.append(line)

    if figure.detail:
        detail = w.label(figure.detail, "metric-detail", wrap=True)
        # Wrapped rather than long: the strip lays out on natural width, and one
        # long sentence would drop four cards to two per line.
        detail.set_max_width_chars(24)
        if figure.tint:
            detail.add_css_class(f"tint-{figure.tint}")
        card.append(detail)
    return card


def _panels(results) -> Gtk.Widget:
    """Two to a row: five panels stacked was a page nobody reached the end of."""
    grid = Gtk.Grid(column_spacing=16, row_spacing=22, column_homogeneous=True)
    last = len(results) - 1
    for index, result in enumerate(results):
        panel = _panel(result)
        panel.set_valign(Gtk.Align.START)
        # An odd last panel takes the whole row rather than leaving half of it
        # blank and ellipsizing its own title into the gap.
        alone = index == last and index % 2 == 0
        grid.attach(panel, 0 if alone else index % 2, index // 2, 2 if alone else 1, 1)
    return grid


def _panel(result) -> Gtk.Widget:
    group = Adw.PreferencesGroup(
        title=result.panel.title,
        description=f"{result.panel.why}  ·  {WHERE_FROM.get(result.panel.store, '')}",
    )
    if not result.ok:
        row = Adw.ActionRow(title="This one could not be answered", subtitle=result.error)
        row.set_subtitle_lines(3)
        icon = Gtk.Image.new_from_icon_name("dialog-warning-symbolic")
        icon.add_css_class("tint-warn")
        row.add_prefix(icon)
        group.add(row)
        return group
    if result.empty:
        group.add(
            Adw.ActionRow(
                title="Nothing to show yet",
                subtitle="The store answered and had no rows for this. Load an export into it.",
            )
        )
        return group

    if result.panel.chart:
        # The chart carries its own axis and its own values, so the rows that
        # made it would be the same numbers printed a second time.
        group.add(_chart_row(result))
        return group
    for row in result.rows[:ROWS_SHOWN]:
        group.add(_row(result.panel, row))
    held = len(result.rows) - ROWS_SHOWN
    if held > 0:
        more = Adw.ActionRow(title=f"and {held} more")
        more.add_css_class("dim-label")
        group.add(more)
    return group


def _row(panel, values: dict) -> Adw.ActionRow:
    first, *rest = panel.columns
    row = Adw.ActionRow(title=_pretty(values.get(first[0])))
    row.set_subtitle(" · ".join(f"{label}: {_pretty(values.get(name))}" for name, label in rest))
    row.set_subtitle_lines(2)
    return row


def _chart_row(result) -> Adw.ActionRow:
    """The series with its axis on it, and a note when the last year is still running."""
    points = estate_module.series(result)
    # A plain row rather than an action row: an action row with no title still
    # reserves the line the title would have gone on.
    row = Adw.PreferencesRow(activatable=False)
    holder = w.box(spacing=4)
    holder.set_margin_top(12)
    holder.set_margin_bottom(10)
    holder.set_margin_start(14)
    holder.set_margin_end(14)

    line = result.panel.key == "lead_time"
    graph = chart_module.YearChart(
        points,
        mode=chart_module.LINE if line else chart_module.BARS,
        unit=" d" if line else "",
    )
    holder.append(graph)

    running = [one for one in points if one.partial]
    if running:
        holder.append(
            w.label(
                f"{running[-1].year} is the year to date, drawn open.",
                "metric-detail",
            )
        )
    row.set_child(holder)
    return row


def _pretty(value) -> str:
    """A year rather than a nanosecond timestamp, and a number without its noise."""
    if value is None:
        return "—"
    text = str(value)
    if len(text) >= 10 and text[4] == "-" and text[7] == "-" and "T" in text:
        return text[:10]
    if text.replace(".", "", 1).isdigit() and "." in text:
        return f"{float(text):g}"
    return text


def _empty(container: Gtk.Box) -> None:
    child = container.get_first_child()
    while child is not None:
        container.remove(child)
        child = container.get_first_child()
