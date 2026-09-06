"""What a series looks like: a sparkline inline, and a full chart with an axis.

A chart with no scale is a picture of a shape, and the reader has to go and
find the numbers somewhere else. Everything drawn here carries its own axis,
its own baseline and its own values, so nothing has to be printed twice.
"""

from __future__ import annotations

import gi

gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
gi.require_version("PangoCairo", "1.0")

from gi.repository import Adw, Gdk, Gtk, Pango, PangoCairo  # noqa: E402

from ..presentation.scale import ceiling  # noqa: E402

# Chart ink. Deliberately not the theme accent: an accent can be any colour the
# system chooses, and a red bar chart reads as a column of failures.
CHART_LIGHT = "#4a6a86"
CHART_DARK = "#8fb3cf"

# Chart text is painted by cairo rather than by the stylesheet, so it is out of
# reach of the CSS the contrast gate reads. It is held at the same floor, and
# tests/test_contrast.py checks this constant against it.
LABEL_ALPHA = 0.78

# The steps an axis is allowed to climb in, so a tick is a number a person
# already counts in.

BARS = "bars"
LINE = "line"


def ink() -> Gdk.RGBA:
    rgba = Gdk.RGBA()
    rgba.parse(CHART_DARK if Adw.StyleManager.get_default().get_dark() else CHART_LIGHT)
    return rgba


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
        fg = self.get_color()
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
            context.set_source_rgba(fg.red, fg.green, fg.blue, LABEL_ALPHA)
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
        fg = self.get_color()
        layout = self._small(tidy(round(point.value, 1)) + self._unit, bold=True)
        size = layout.get_pixel_size()
        context.set_source_rgba(fg.red, fg.green, fg.blue, LABEL_ALPHA)
        context.move_to(x - size.width / 2, y - size.height - 3)
        PangoCairo.show_layout(context, layout)

    def _years(self, context, fg, plot, height: int) -> None:
        left, _, span, _ = plot
        each = span / len(self._points)
        for index, point in enumerate(self._points):
            layout = self._small(str(point.year), bold=point.partial)
            size = layout.get_pixel_size()
            context.set_source_rgba(fg.red, fg.green, fg.blue, LABEL_ALPHA)
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
