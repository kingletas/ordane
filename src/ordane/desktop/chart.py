"""What a series looks like: bars, a line, a gauge and a day of runs as ticks.

A chart with no scale is a picture of a shape, and the reader has to go and
find the numbers somewhere else. Everything drawn here carries its own axis or
sits directly under the figure it belongs to, and its axis labels name the same
range as the basis line above them.

Every colour comes from the palette in `tokens`, so a bar is the same pine as
the pill beside it in both schemes.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gtk, Pango, PangoCairo  # noqa: E402

from ..presentation.scale import ceiling  # noqa: E402
from . import tokens  # noqa: E402

BARS = "bars"
LINE = "line"

# The metric card's chart, in the card's own viewBox: big enough to read, and
# the same height whichever of the two shapes is drawn in it.
METRIC_HEIGHT = 74

# A day of runs as ticks. A routine run is short and pale; anything that
# changed, drifted or failed is full height and coloured.
RIBBON_HEIGHT = 24
ROUTINE_TICK = 0.38


def scheme() -> str:
    return tokens.DARK if Adw.StyleManager.get_default().get_dark() else tokens.LIGHT


def rgba(name: str) -> Gdk.RGBA:
    """One palette colour, as cairo wants it."""
    colour = Gdk.RGBA()
    colour.parse(tokens.colour(name, scheme()))
    return colour


def _set(context, name: str, alpha: float = 1.0) -> None:
    colour = rgba(name)
    context.set_source_rgba(colour.red, colour.green, colour.blue, alpha)


def ink() -> Gdk.RGBA:
    """The colour a chart is drawn in, which is the ramp's `ready` pine."""
    return rgba("ready")


def tidy(value: float) -> str:
    return f"{value:g}"


class Sparkline(Gtk.DrawingArea):
    """A short bar chart drawn in the chart ink, for a series too small to table."""

    def __init__(self, series, height: int = 34) -> None:
        super().__init__()
        self._series = series
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, height: int) -> None:
        values = self._series.values
        if not values:
            return
        rgba = ink()

        # The line the bars stand on. Without it a short bar reads as hanging
        # from the top rather than as a small number.
        context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.25)
        context.rectangle(0, height - 1, width, 1)
        context.fill()

        peak = max(values) or 1.0
        gap = 2.0
        span = width / len(values)
        bar = max(span - gap, 1.0)

        for index, value in enumerate(values):
            tall = (value / peak) * (height - 2)
            x = index * span
            if value:
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.85)
                context.rectangle(x, height - tall, bar, tall)
            else:
                # A month with no release is drawn as a floor, so an empty month
                # reads as measured rather than missing.
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.18)
                context.rectangle(x, height - 2, bar, 2)
            context.fill()


class YearChart(Gtk.DrawingArea):
    """A year-at-a-time series with an axis, its values on it, and the running year marked."""

    # Both bands are measured at draw time from the labels that go in them: a
    # fixed height clips the value above the tallest bar at some font sizes.
    HEADROOM = 6
    FOOTROOM = 4
    GUTTER = 8

    def __init__(self, points, mode: str = BARS, unit: str = "", height: int = 168) -> None:
        super().__init__()
        self._points = list(points)
        self._mode = mode
        self._unit = unit
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    # --- what it draws ---

    def _draw(self, _area, context, width: int, height: int) -> None:
        if not self._points:
            return
        rgba = ink()
        fg = rgba("ink-3")
        top, step = ceiling(max(one.value for one in self._points))

        band = self._small("0", bold=True).get_pixel_size().height
        head = band + self.HEADROOM
        foot = band + self.FOOTROOM
        gutter = self._axis_width(top, step)
        left = gutter + self.GUTTER
        plot = (left, head, max(width - left, 1), max(height - head - foot, 1))

        self._grid(context, fg, plot, top, step, gutter)
        if self._mode == LINE:
            self._line(context, rgba, plot, top)
        else:
            self._bars(context, rgba, plot, top)
        self._years(context, fg, plot, height)

    def _axis_width(self, top: float, step: float) -> int:
        widest = 0
        for tick in _ticks(top, step):
            layout = self._small(tidy(tick))
            widest = max(widest, layout.get_pixel_size().width)
        return widest

    def _grid(self, context, fg, plot, top: float, step: float, gutter: int) -> None:
        left, y0, span, tall = plot
        for tick in _ticks(top, step):
            y = y0 + tall - (tick / top) * tall
            zero = tick == 0
            context.set_source_rgba(fg.red, fg.green, fg.blue, 0.30 if zero else 0.12)
            context.rectangle(left, round(y) - (1 if zero else 0), span, 2 if zero else 1)
            context.fill()

            layout = self._small(tidy(tick))
            size = layout.get_pixel_size()
            context.set_source_rgba(fg.red, fg.green, fg.blue, 1.0)
            context.move_to(gutter - size.width, y - size.height / 2)
            PangoCairo.show_layout(context, layout)

    def _bars(self, context, rgba, plot, top: float) -> None:
        left, y0, span, tall = plot
        each = span / len(self._points)
        width = max(each - max(each * 0.28, 6), 2)
        for index, point in enumerate(self._points):
            height = (point.value / top) * tall
            x = left + index * each + (each - width) / 2
            y = y0 + tall - height
            if point.partial:
                # A year still running is outlined rather than filled, so a
                # short last bar reads as unfinished instead of as a fall.
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.22)
                context.rectangle(x, y, width, height)
                context.fill()
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.9)
                context.set_line_width(2)
                context.set_dash([4.0, 3.0])
                context.rectangle(x + 1, y + 1, width - 2, max(height - 2, 0))
                context.stroke()
                context.set_dash([])
            else:
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.72)
                context.rectangle(x, y, width, height)
                context.fill()
            self._value(context, point, x + width / 2, y)

    def _line(self, context, rgba, plot, top: float) -> None:
        left, y0, span, tall = plot
        each = span / len(self._points)
        spots = [
            (left + index * each + each / 2, y0 + tall - (point.value / top) * tall)
            for index, point in enumerate(self._points)
        ]
        context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.85)
        context.set_line_width(2)
        context.set_line_join(1)
        context.move_to(*spots[0])
        for spot in spots[1:]:
            context.line_to(*spot)
        context.stroke()
        for point, (x, y) in zip(self._points, spots, strict=True):
            context.rectangle(x - 3.5, y - 3.5, 7, 7)
            if point.partial:
                # Hollow, for the same reason the last bar is outlined.
                context.set_source_rgba(rgba.red, rgba.green, rgba.blue, 0.85)
                context.set_line_width(2)
                context.stroke()
            else:
                context.fill()
            self._value(context, point, x, y)

    def _value(self, context, point, x: float, y: float) -> None:
        fg = rgba("ink-3")
        layout = self._small(tidy(round(point.value, 1)) + self._unit, bold=True)
        size = layout.get_pixel_size()
        context.set_source_rgba(fg.red, fg.green, fg.blue, 1.0)
        context.move_to(x - size.width / 2, y - size.height - 3)
        PangoCairo.show_layout(context, layout)

    def _years(self, context, fg, plot, height: int) -> None:
        left, _, span, _ = plot
        each = span / len(self._points)
        for index, point in enumerate(self._points):
            layout = self._small(str(point.year), bold=point.partial)
            size = layout.get_pixel_size()
            context.set_source_rgba(fg.red, fg.green, fg.blue, 1.0)
            context.move_to(left + index * each + (each - size.width) / 2, height - size.height - 2)
            PangoCairo.show_layout(context, layout)

    def _small(self, text: str, bold: bool = False) -> Pango.Layout:
        layout = self.create_pango_layout(text)
        description = self.get_pango_context().get_font_description().copy()
        description.set_size(int(description.get_size() * 0.82))
        description.set_weight(Pango.Weight.BOLD if bold else Pango.Weight.NORMAL)
        layout.set_font_description(description)
        return layout


def _ticks(top: float, step: float) -> list[float]:
    ticks = []
    tick = 0.0
    while tick <= top + step / 2:
        ticks.append(tick)
        tick += step
    return ticks


class MetricBars(Gtk.DrawingArea):
    """Counts per month under the figure they add up to.

    A month with nothing in it keeps a floor rather than disappearing, so an
    empty month reads as measured instead of missing.
    """

    FLOOR = 1.5
    GAP = 3.0

    def __init__(self, series, height: int = METRIC_HEIGHT) -> None:
        super().__init__()
        self._series = series
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, height: int) -> None:
        values = self._series.values
        if not values:
            return
        base = height - 1
        _set(context, "line")
        context.rectangle(0, base, width, 1)
        context.fill()

        peak = max(values) or 1.0
        span = width / len(values)
        bar = max(span - self.GAP, 1.0)
        for index, value in enumerate(values):
            tall = (value / peak) * (base - 2) if value else self.FLOOR
            _set(context, "ready" if value else "line", 0.82 if value else 1.0)
            context.rectangle(index * span + self.GAP / 2, base - tall, bar, tall)
            context.fill()


class MetricLine(Gtk.DrawingArea):
    """A line with the area under it filled, for a measure that is a level.

    It draws itself left to right once, which is the only motion on the page
    that is not a live run — and none at all when reduced motion is asked for.
    """

    STEP_MS = 16
    DRAW_MS = 900

    def __init__(self, series, height: int = METRIC_HEIGHT, animate: bool = True) -> None:
        super().__init__()
        self._series = series
        self._grown = 0.0 if animate else 1.0
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)
        if animate:
            self._started = 0.0
            self.add_tick_callback(self._step)

    def _step(self, _widget, clock) -> bool:
        now = clock.get_frame_time() / 1000.0
        if not self._started:
            self._started = now
        self._grown = min(1.0, (now - self._started) / self.DRAW_MS)
        self.queue_draw()
        return self._grown < 1.0

    def _draw(self, _area, context, width: int, height: int) -> None:
        values = self._series.values
        if len(values) < 2:
            return
        base = height - 1
        low, high = min(values), max(values)
        span = (high - low) or 1.0
        step = width / (len(values) - 1)
        points = [
            (index * step, base - 4 - ((value - low) / span) * (base - 12))
            for index, value in enumerate(values)
        ]
        drawn = max(2, int(round(len(points) * self._grown)))
        points = points[:drawn]

        context.move_to(*points[0])
        for point in points[1:]:
            context.line_to(*point)
        context.line_to(points[-1][0], base)
        context.line_to(points[0][0], base)
        context.close_path()
        _set(context, "ready", 0.16)
        context.fill()

        context.move_to(*points[0])
        for point in points[1:]:
            context.line_to(*point)
        _set(context, "ready")
        context.set_line_width(1.8)
        context.set_line_join(1)
        context.stroke()

        _set(context, "line")
        context.rectangle(0, base, width, 1)
        context.fill()


class Ribbon(Gtk.DrawingArea):
    """A day of runs as ticks, so `was today normal?` is answered before a word.

    One tick per run, oldest on the left. Routine passes are short and pale;
    anything that changed, drifted or failed is full height and coloured.
    """

    GAP = 2.0

    def __init__(self, ticks, height: int = RIBBON_HEIGHT) -> None:
        super().__init__()
        self._ticks = list(ticks)
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, height: int) -> None:
        if not self._ticks:
            return
        span = width / len(self._ticks)
        bar = max(span - self.GAP, 1.0)
        for index, tick in enumerate(self._ticks):
            tall = height if tick.tall else height * ROUTINE_TICK
            _set(context, _TICK_COLOUR.get(tick.state, "tick-idle"))
            context.rectangle(index * span, height - tall, bar, tall)
            context.fill()


_TICK_COLOUR = {
    "ok": "tick-idle",
    "changed": "ready",
    "live": "ready",
    "warn": "degraded",
    "fail": "failed",
    "mute": "cell-hatch",
}


class Gauge(Gtk.DrawingArea):
    """An objective's attainment with its target marked on the same bar.

    A bar without the target on it makes the reader hold two numbers and do the
    comparison themselves, which is the layout's job.
    """

    HEIGHT = 6

    def __init__(self, attained: float | None, target: float) -> None:
        super().__init__()
        self._attained = attained
        self._target = target
        self.set_content_height(self.HEIGHT + 4)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, _height: int) -> None:
        top = 2.0
        _set(context, "track")
        _rounded(context, 0, top, width, self.HEIGHT)
        context.fill()

        if self._attained is not None:
            reached = max(0.0, min(1.0, self._attained / 100.0)) * width
            met = self._attained >= self._target
            _set(context, "ready" if met else "failed")
            _rounded(context, 0, top, reached, self.HEIGHT)
            context.fill()

        at = max(0.0, min(1.0, self._target / 100.0)) * width
        _set(context, "ink-2")
        context.rectangle(min(at, width - 2), 0, 2, self.HEIGHT + 4)
        context.fill()


def _rounded(context, x: float, y: float, width: float, height: float) -> None:
    """A capsule, because a 6px bar with square ends reads as a table cell."""
    radius = min(height / 2, max(width / 2, 0.1))
    if width <= 0:
        return
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -1.5708, 1.5708)
    context.arc(x + radius, y + height - radius, radius, 1.5708, 4.7124)
    context.close_path()


class Cells(Gtk.DrawingArea):
    """One host's lane: a cell per task, in the state that host left it in.

    This is the one place worth spending visual boldness. It gives the shape of
    a run — which hosts are lagging, which task is slow — in one look, which no
    log can do.
    """

    HEIGHT = 22
    GAP = 4.0

    def __init__(self, states: list[str], height: int = HEIGHT) -> None:
        super().__init__()
        self._states = list(states)
        self.set_content_height(height)
        self.set_hexpand(True)
        self.set_draw_func(self._draw)

    def update(self, states: list[str]) -> None:
        self._states = list(states)
        self.queue_draw()

    def _draw(self, _area, context, width: int, height: int) -> None:
        if not self._states:
            return
        span = width / len(self._states)
        cell = max(span - self.GAP, 1.0)
        for index, state in enumerate(self._states):
            x = index * span
            _set(context, _CELL_COLOUR.get(state, "cell-empty"))
            _rounded_box(context, x, 0, cell, height, 3)
            context.fill()
            if state == "skipped":
                _hatch(context, x, 0, cell, height)


_CELL_COLOUR = {
    "ok": "cell-ok",
    "changed": "ready",
    "skipped": "cell-empty",
    "failed": "failed",
    "running": "cell-ok",
    "pending": "cell-empty",
}


def _rounded_box(context, x: float, y: float, width: float, height: float, radius: float) -> None:
    radius = min(radius, width / 2, height / 2)
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -1.5708, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, 1.5708)
    context.arc(x + radius, y + height - radius, radius, 1.5708, 3.1416)
    context.arc(x + radius, y + radius, radius, 3.1416, 4.7124)
    context.close_path()


def _hatch(context, x: float, y: float, width: float, height: float) -> None:
    """Diagonals over a skipped cell, so it reads as skipped rather than empty."""
    context.save()
    _rounded_box(context, x, y, width, height, 3)
    context.clip()
    _set(context, "cell-hatch")
    context.set_line_width(1.4)
    step = 6.0
    offset = -height
    while offset < width + height:
        context.move_to(x + offset, y + height)
        context.line_to(x + offset + height, y)
        offset += step
    context.stroke()
    context.restore()
