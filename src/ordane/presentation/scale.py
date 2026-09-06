"""Choosing a round top for an axis, and the step to climb it in.

Arithmetic rather than drawing, so it sits above the line with the rest of the
engine. It used to live beside the widget that uses it, which meant a test of
these numbers could not run on a machine with no toolkit installed -- and that
is exactly the machine the unit suite is supposed to prove it works on.
"""

from __future__ import annotations

# Steps a person reads without doing arithmetic: 1, 2, 2.5 and 5 of whatever
# power of ten the data is in.
STEPS = (1.0, 2.0, 2.5, 5.0, 10.0)


def ceiling(peak: float) -> tuple[float, float]:
    """A round top for the axis and the step to climb it in, aiming at three ticks."""
    if peak <= 0:
        return 1.0, 1.0
    magnitude = 10 ** _floor_log10(peak / 3)
    for step in STEPS:
        candidate = step * magnitude
        if candidate * 3 >= peak:
            return _round_up(peak, candidate), candidate
    candidate = 10 * magnitude
    return _round_up(peak, candidate), candidate


def _floor_log10(value: float) -> int:
    exponent = 0
    while value >= 10:
        value /= 10
        exponent += 1
    while value < 1:
        value *= 10
        exponent -= 1
    return exponent


def _round_up(value: float, step: float) -> float:
    steps = int(value / step)
    return step * (steps if steps * step >= value else steps + 1)
