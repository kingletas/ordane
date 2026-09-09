"""The rail's own icons, drawn rather than looked up.

Adwaita has no glyph for a delivery chart or for a lane of hosts, and the rail
is the one place where six icons have to look like one set. Each is drawn in a
16×16 box with a 1.4px stroke, and takes its colour from the widget's own CSS
`color` — so a place that is current gets the pine and the rest stay muted
without a second palette.
"""

from __future__ import annotations

import math

import gi

gi.require_version("Gtk", "4.0")

from gi.repository import Gtk  # noqa: E402

BOX = 16.0
STROKE = 1.4


def _circle(context, x: float, y: float, radius: float) -> None:
    context.new_sub_path()
    context.arc(x, y, radius, 0, math.tau)


def _rounded(context, x: float, y: float, width: float, height: float, radius: float) -> None:
    context.new_sub_path()
    context.arc(x + width - radius, y + radius, radius, -math.pi / 2, 0)
    context.arc(x + width - radius, y + height - radius, radius, 0, math.pi / 2)
    context.arc(x + radius, y + height - radius, radius, math.pi / 2, math.pi)
    context.arc(x + radius, y + radius, radius, math.pi, 3 * math.pi / 2)
    context.close_path()


def overview(context) -> None:
    """A roof: the place you look at the whole thing from."""
    context.move_to(2, 9.5)
    context.line_to(8, 3)
    context.line_to(14, 9.5)
    context.stroke()
    context.move_to(3.6, 8.5)
    context.line_to(3.6, 13)
    context.line_to(12.4, 13)
    context.line_to(12.4, 8.5)
    context.stroke()


def actions(context) -> None:
    """A play triangle: the one place something is deliberately started."""
    context.move_to(4.5, 2.8)
    context.line_to(12.5, 8)
    context.line_to(4.5, 13.2)
    context.close_path()
    context.stroke()


def runs(context) -> None:
    """A clock, because a run is a thing that happened at a time."""
    _circle(context, 8, 8, 6)
    context.stroke()
    context.move_to(8, 4.6)
    context.line_to(8, 8)
    context.line_to(10.4, 9.6)
    context.stroke()


def environments(context) -> None:
    """A globe: separate worlds, each reached differently."""
    _circle(context, 8, 8, 6)
    context.stroke()
    context.move_to(2.2, 8)
    context.line_to(13.8, 8)
    context.stroke()
    context.move_to(8, 2.1)
    context.curve_to(11.2, 5.5, 11.2, 10.5, 8, 13.9)
    context.curve_to(4.8, 10.5, 4.8, 5.5, 8, 2.1)
    context.stroke()


def estate(context) -> None:
    """Two racks: hosts, stacked."""
    _rounded(context, 2.2, 3, 11.6, 4, 1.2)
    context.stroke()
    _rounded(context, 2.2, 9, 11.6, 4, 1.2)
    context.stroke()


def delivery(context) -> None:
    """Four bars of different heights: a measure that moves."""
    for x, top in ((2.5, 7.0), (6.5, 3.5), (10.5, 9.0), (14.0, 5.5)):
        context.move_to(x, 12.5)
        context.line_to(x, top)
    context.stroke()


def repository(context) -> None:
    """A git node above another: the thing the console is pointed at."""
    _circle(context, 8, 4, 2)
    context.stroke()
    _circle(context, 8, 12, 2)
    context.stroke()
    context.move_to(8, 6)
    context.line_to(8, 10)
    context.stroke()


def search(context) -> None:
    _circle(context, 7, 7, 4.5)
    context.stroke()
    context.move_to(10.4, 10.4)
    context.line_to(14, 14)
    context.stroke()


def refresh(context) -> None:
    """An arc with an arrow head, which is what re-reading looks like."""
    context.new_sub_path()
    context.arc(8, 8, 5.5, -math.pi * 0.72, math.pi * 0.92)
    context.stroke()
    context.move_to(13.6, 2.2)
    context.line_to(13.6, 5.6)
    context.line_to(10.2, 5.6)
    context.stroke()


def brand(context) -> None:
    """The mark: a rounded square with a filled centre."""
    _rounded(context, 1.6, 1.6, 12.8, 12.8, 3.6)
    context.stroke()
    _circle(context, 8, 8, 2.4)
    context.fill()


SHAPES = {
    "overview": overview,
    "actions": actions,
    "runs": runs,
    "environments": environments,
    "estate": estate,
    "delivery": delivery,
    "repository": repository,
    "search": search,
    "refresh": refresh,
    "brand": brand,
}


class Glyph(Gtk.DrawingArea):
    """One drawn icon, at whatever size it is asked for."""

    def __init__(self, name: str, size: int = 15) -> None:
        super().__init__()
        self._draw_shape = SHAPES.get(name, overview)
        self._size = size
        self.set_content_width(size)
        self.set_content_height(size)
        self.set_valign(Gtk.Align.CENTER)
        self.add_css_class("glyph")
        self.set_draw_func(self._draw)

    def _draw(self, _area, context, width: int, height: int) -> None:
        colour = self.get_color()
        context.set_source_rgba(colour.red, colour.green, colour.blue, colour.alpha)
        scale = min(width, height) / BOX
        context.scale(scale, scale)
        context.set_line_width(STROKE)
        context.set_line_cap(1)
        context.set_line_join(1)
        self._draw_shape(context)
