"""A toast may not ask for more width than a narrow window has.

This is the warning that fired hundreds of times in CI and that could not be
reproduced on the machine that wrote the code: `AdwToastOverlay exceeds
ConsoleWindow width: requested 1236 px, 1170 px available`.

The cause was bounding the toast with `set_max_width_chars`, which is a count
of characters and therefore a guess about the font. The same fifty-six
characters are far wider in the font a CI runner has. The bound is pixels now,
and this measures the widget on its own rather than inside a window, so the
number under test is the toast's and nothing else's.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk, Pango  # noqa: E402

from ordane.desktop.window import TOAST_WIDTH_PX  # noqa: E402

# The longest thing this console says, and the worst shape for a wrapping
# label: one unbreakable token most of the way through it.
LONGEST = "Template copied: paste it into ~/.config/ordane/stores.env"

# Narrower than any window this runs in, and narrower than the 1170 px the
# runner had when it complained.
NARROWEST_WINDOW_PX = 640


def toast_title(message: str) -> Gtk.Widget:
    """The same widget tree `ConsoleWindow._toast` builds."""
    said = Gtk.Label(label=message, wrap=True, xalign=0.5)
    said.set_justify(Gtk.Justification.CENTER)
    said.set_wrap_mode(Pango.WrapMode.WORD_CHAR)
    said.set_natural_wrap_mode(Gtk.NaturalWrapMode.NONE)
    return Adw.Clamp(maximum_size=TOAST_WIDTH_PX, tightening_threshold=TOAST_WIDTH_PX, child=said)


# The bug only appeared on a machine whose font is wider than this one's, so a
# test that used the local font would pass on both the broken and the fixed
# code -- and did. This forces a font wide enough to stand in for the runner's.
WIDE_FONT_PX = 32


def widest(message: str, font_px: int | None = None) -> int:
    Adw.init()
    title = toast_title(message)
    window = Gtk.Window(child=title)
    window.realize()
    css = None
    if font_px:
        css = Gtk.CssProvider()
        css.load_from_data(f"* {{ font-size: {font_px}px; }}".encode())
        Gtk.StyleContext.add_provider_for_display(window.get_display(), css, 900)
    _, natural, _, _ = title.measure(Gtk.Orientation.HORIZONTAL, -1)
    if css is not None:
        Gtk.StyleContext.remove_provider_for_display(window.get_display(), css)
    window.destroy()
    return natural


def test_the_bound_is_a_pixel_count():
    """A character count is a guess about the font, which is how this broke."""
    assert isinstance(TOAST_WIDTH_PX, int)
    assert TOAST_WIDTH_PX < NARROWEST_WINDOW_PX


@pytest.mark.parametrize(
    "message",
    [
        LONGEST,
        "deploy ran and its postcheck passed",
        "Saved: only this account can read that file",
        # One token and nothing else: the case a word-wrapping label cannot break.
        "/a/very/long/path/that/has/no/spaces/in/it/at/all/whatsoever/really",
    ],
)
def test_no_message_makes_the_toast_wider_than_the_bound(message):
    assert widest(message) <= TOAST_WIDTH_PX


@pytest.mark.parametrize(
    "message",
    [LONGEST, "/a/very/long/path/that/has/no/spaces/in/it/at/all/whatsoever/really"],
)
def test_the_bound_holds_in_a_font_this_machine_does_not_have(message):
    """The case that failed in CI and passed here.

    A character count is wider in a wider font; a pixel clamp is not. Without
    this, the same test passes on both the broken code and the fixed code,
    because the font on the machine that wrote it never triggered the bug.
    """
    assert widest(message, WIDE_FONT_PX) <= TOAST_WIDTH_PX


def test_it_fits_a_window_narrower_than_the_one_that_complained():
    assert widest(LONGEST) < NARROWEST_WINDOW_PX
