"""No single label may decide how wide a screen has to be.

Three defects in this design had one shape. A `Gtk.Label` that neither wraps
nor ellipsises reports its whole text as its minimum width; that becomes the
minimum of the row, then of the card, then of the page. The page then asks for
more room than the window has, and GTK does not refuse it — it draws widgets on
top of each other and logs about an overlay exceeding its width.

The screens are checked at their widest in the window smoke. These are the
pieces, checked with text long enough to break them, because a fixture with
short strings in it proves nothing about a control plane with long ones.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

# Wide enough for any sensible piece, and far below the room a place has.
CEILING = 360

LONG = (
    "the Targets: block that make help prints · every one reaches newdev, "
    "newstage, production, staging"
)

VERY_LONG = " ".join(["reticulating"] * 40)


def widest(widget: Gtk.Widget) -> int:
    Adw.init()
    window = Gtk.Window(child=widget)
    window.realize()
    minimum, _natural, _a, _b = widget.measure(Gtk.Orientation.HORIZONTAL, -1)
    window.destroy()
    return minimum


@pytest.fixture(autouse=True)
def _toolkit():
    Adw.init()


def test_the_maths_catches_a_label_that_cannot_give_up_width():
    """The control: a plain long label really does demand all of it."""
    from ordane.desktop import widgets as w

    assert widest(w.label(VERY_LONG)) > CEILING


def test_a_band_with_a_long_aside_stays_narrow():
    from ordane.desktop import widgets as w

    assert widest(w.band("Defined in", LONG)) <= CEILING


def test_a_band_with_an_absurd_aside_still_stays_narrow():
    from ordane.desktop import widgets as w

    assert widest(w.band("Defined in", VERY_LONG)) <= CEILING


def test_a_wrapping_label_never_demands_its_longest_word():
    """`natural_wrap_mode NONE` is what keeps a path or a hostname from doing it."""
    from ordane.desktop import widgets as w

    said = w.label("/a/very/long/path/with/no/spaces/in/it/whatsoever/at/all", wrap=True)
    assert widest(said) <= CEILING


def test_a_tag_gives_up_width_rather_than_taking_the_row():
    from ordane.desktop import widgets as w

    assert widest(w.tag(VERY_LONG)) <= CEILING


def test_a_danger_chip_gives_up_width_too():
    from ordane.desktop import widgets as w

    chip = w.danger_chip("high")
    assert chip is not None
    assert widest(chip) <= CEILING


def test_the_verdict_line_has_a_floor_but_not_a_large_one():
    """It is pinned above its longest word on purpose; that must stay modest.

    Without a floor GTK reports one minimum for the label and another for the
    same label at a given height, and says so on every layout pass.
    """
    from ordane.desktop import widgets as w
    from ordane.insight.verdict import Verdict

    band = w.verdict_band(Verdict(headline=VERY_LONG, note=VERY_LONG))
    assert widest(band) <= CEILING


def test_a_run_row_note_gives_up_width():
    from ordane.desktop import widgets as w

    said = w.label(VERY_LONG, "actrow-note", wrap=True)
    assert widest(said) <= CEILING
