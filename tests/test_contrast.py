"""The muted text in the stylesheet, measured against WCAG rather than eyeballed.

A monitoring interface whose secondary text sits at 3:1 is one whose reasons
are harder to read than its numbers. Every `alpha(@window_fg_color, N)` in the
stylesheet is checked here against the palette libadwaita actually supplies, in
both of its schemes.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "ordane" / "desktop"
CSS = ROOT / "assets" / "app.css"
CHART = ROOT / "chart.py"

# libadwaita 1.5, read from a running Gtk.Window rather than guessed. The dark
# card background is a translucent white over the window, so its opaque
# equivalent is what a reader actually sees.
PALETTE = {
    "light": {"fg": (61, 61, 61), "window": (250, 250, 250), "card": (255, 255, 255)},
    "dark": {"fg": (247, 247, 247), "window": (44, 44, 44), "card": (61, 61, 61)},
}

# WCAG 2.1: 4.5:1 for body text, 3:1 for large text. Everything measured here
# is body-sized, so the higher bar applies to all of it.
MINIMUM = 4.5

_ALPHA = re.compile(r"alpha\(@window_fg_color,\s*([0-9.]+)\)")


def _linear(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def luminance(colour: tuple[int, int, int]) -> float:
    red, green, blue = (_linear(c) for c in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: tuple[int, int, int], second: tuple[int, int, int]) -> float:
    one, two = sorted((luminance(first), luminance(second)), reverse=True)
    return (one + 0.05) / (two + 0.05)


def over(foreground, background, alpha: float) -> tuple[int, int, int]:
    """What a translucent foreground actually looks like on a ground."""
    pairs = zip(foreground, background, strict=True)
    return tuple(round(alpha * front + (1 - alpha) * back) for front, back in pairs)


def test_the_contrast_maths_agrees_with_known_pairs():
    assert round(contrast((0, 0, 0), (255, 255, 255)), 1) == 21.0
    assert round(contrast((255, 255, 255), (255, 255, 255)), 1) == 1.0
    # #767676 on white is the canonical 4.5:1 boundary case.
    assert 4.4 < contrast((118, 118, 118), (255, 255, 255)) < 4.6


def test_every_muted_text_colour_is_readable_in_both_schemes():
    alphas = {float(match) for match in _ALPHA.findall(CSS.read_text(encoding="utf-8"))}
    assert alphas, "no alpha(@window_fg_color, …) found: has the stylesheet changed shape?"

    failures = []
    for alpha in sorted(alphas):
        for scheme, palette in PALETTE.items():
            for ground in ("window", "card"):
                ratio = contrast(over(palette["fg"], palette[ground], alpha), palette[ground])
                if ratio < MINIMUM:
                    failures.append(f"{alpha} on the {scheme} {ground} is {ratio:.2f}:1")
    assert not failures, "muted text below 4.5:1, " + "; ".join(failures)


def test_the_floor_is_where_it_is_for_a_reason():
    """The value just below the one in use must fail, or the floor is arbitrary."""
    light = PALETTE["light"]
    assert contrast(over(light["fg"], light["card"], 0.55), light["card"]) < MINIMUM
    assert contrast(over(light["fg"], light["card"], 0.78), light["card"]) >= MINIMUM


def test_chart_text_is_held_to_the_same_floor_as_the_stylesheet():
    """Cairo paints the axis, so no rule in app.css can be asked about it."""
    found = re.search(r"^LABEL_ALPHA = ([0-9.]+)", CHART.read_text(encoding="utf-8"), re.M)
    assert found, "no LABEL_ALPHA in chart.py: has the chart stopped drawing its own labels?"
    alpha = float(found.group(1))
    for palette in PALETTE.values():
        for ground in ("window", "card"):
            assert contrast(over(palette["fg"], palette[ground], alpha), palette[ground]) >= MINIMUM
