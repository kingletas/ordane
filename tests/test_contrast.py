"""The palette, measured against WCAG rather than eyeballed.

A monitoring interface whose secondary text sits at 3:1 is one whose reasons
are harder to read than its numbers. Every colour the design uses for text is
checked here against the ground it is drawn on, in both schemes.

Three of the colours in the design document are a shade darker or lighter here
than it printed them, and this is why: `ink-3` at `#7C837F` reads at 3.1:1 on
the canvas, `degraded` at `#95681A` at 3.9:1, and the rail's muted grey at
3.8:1 on the rail. The hues are unchanged; the values moved far enough to
clear the floor and no further.
"""

import re
from pathlib import Path

from ordane.desktop import tokens

ROOT = Path(__file__).resolve().parents[1] / "src" / "ordane" / "desktop"
CSS = ROOT / "assets" / "app.css"

# WCAG 2.1: 4.5:1 for body text, 3:1 for large text. Everything measured here
# is body-sized or smaller, so the higher bar applies to all of it.
MINIMUM = 4.5

# Which ground each text colour is actually drawn on. A colour that appears on
# more than one is checked against all of them.
ON_CANVAS_AND_CARD = ("canvas", "card", "card-head", "card-inset")

PAIRS = {
    "ink": ON_CANVAS_AND_CARD,
    "ink-2": ON_CANVAS_AND_CARD,
    "ink-3": ON_CANVAS_AND_CARD,
    "ready": (*ON_CANVAS_AND_CARD, "ready-bg"),
    "waiting": (*ON_CANVAS_AND_CARD, "waiting-bg"),
    "degraded": (*ON_CANVAS_AND_CARD, "degraded-bg"),
    "failed": (*ON_CANVAS_AND_CARD, "failed-bg"),
    "rail-fg": ("rail", "rail-card", "rail-hover"),
    "rail-fg-strong": ("rail", "rail-active", "rail-hover"),
    "rail-muted": ("rail", "rail-card", "rail-raised"),
    "rail-accent": ("rail", "rail-active"),
    "rail-chip-fg": ("rail-chip",),
    "rail-chip-clean": ("rail-chip",),
    "rail-key-fg": ("rail-key",),
    "log-fg": ("log-bg",),
    "log-time": ("log-bg",),
    "log-ok": ("log-bg",),
    "log-warn": ("log-bg",),
}

# White on a filled button, which is the one place text is not a palette entry.
ON_FILL = (("on-ready", "ready"), ("on-waiting", "waiting"), ("on-failed", "failed"))


def _linear(channel: float) -> float:
    channel /= 255
    return channel / 12.92 if channel <= 0.04045 else ((channel + 0.055) / 1.055) ** 2.4


def rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[at : at + 2], 16) for at in (0, 2, 4))


def luminance(colour: tuple[int, int, int]) -> float:
    red, green, blue = (_linear(one) for one in colour)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast(first: str, second: str) -> float:
    one, two = sorted((luminance(rgb(first)), luminance(rgb(second))), reverse=True)
    return (one + 0.05) / (two + 0.05)


def test_the_contrast_maths_agrees_with_known_pairs():
    assert round(contrast("#000000", "#ffffff"), 1) == 21.0
    assert round(contrast("#ffffff", "#ffffff"), 1) == 1.0
    # #767676 on white is the canonical 4.5:1 boundary case.
    assert 4.4 < contrast("#767676", "#ffffff") < 4.6


def test_every_text_colour_is_readable_on_every_ground_it_is_drawn_on():
    failures = []
    for scheme in (tokens.LIGHT, tokens.DARK):
        palette = tokens.palette(scheme)
        for ink, grounds in PAIRS.items():
            for ground in grounds:
                ratio = contrast(palette[ink], palette[ground])
                if ratio < MINIMUM:
                    failures.append(f"{scheme}: {ink} on {ground} is {ratio:.2f}:1")
    assert not failures, "text below 4.5:1, " + "; ".join(failures)


def test_a_filled_button_reads_against_its_own_fill():
    """White on the dark scheme's light pine is 2.2:1, so the text goes dark."""
    for scheme in (tokens.LIGHT, tokens.DARK):
        palette = tokens.palette(scheme)
        for ink, fill in ON_FILL:
            ratio = contrast(palette[ink], palette[fill])
            assert ratio >= MINIMUM, f"{scheme}: {ink} on {fill} is {ratio:.2f}:1"


def test_the_floor_is_where_it_is_for_a_reason():
    """The colours the design printed must fail, or the change to them was noise."""
    light = tokens.palette(tokens.LIGHT)
    assert contrast("#7C837F", light["canvas"]) < MINIMUM
    assert contrast("#95681A", light["canvas"]) < MINIMUM
    assert contrast("#6E7976", light["rail"]) < MINIMUM


def test_the_stylesheet_names_no_colour_the_palette_does_not_define():
    """A `@name` with nothing behind it is a rule GTK drops without a word."""
    text = CSS.read_text(encoding="utf-8")
    known = set(tokens.palette(tokens.LIGHT))
    # `@define-color` is the at-rule the palette is written with, not a name it
    # defines; it only appears in the block this file prepends.
    used = set(re.findall(r"@([a-z0-9-]+)", text)) - {"define-color", "media"}
    unknown = used - known
    assert not unknown, f"the stylesheet reads {sorted(unknown)}, which nothing defines"


def test_both_schemes_define_the_same_names():
    assert set(tokens.palette(tokens.LIGHT)) == set(tokens.palette(tokens.DARK))


def test_the_stylesheet_hardcodes_almost_no_colour():
    """Every colour comes from the palette, or the two schemes drift apart."""
    text = CSS.read_text(encoding="utf-8")
    found = {one.upper() for one in re.findall(r"#[0-9a-fA-F]{3,8}", text)}
    allowed: set[str] = set()
    assert found <= allowed, f"hardcoded colours: {sorted(found - allowed)}"
