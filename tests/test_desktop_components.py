"""The pieces below a page that compute something rather than only arrange it.

A widget that only puts other widgets in a box is covered by the page test above
it. These are the ones with a lookup, a fallback or a drawing routine in them,
which is where an input nobody expected goes wrong quietly.
"""

from __future__ import annotations

import pytest
from conftest import EXAMPLE_PLANE, a_scene, page_text

# --- glyphs: a lookup with a fallback, which is the shape that hid a crash ---


def test_every_place_in_the_rail_has_a_glyph(adw):
    """The ledger page's pill map had this hole and it crashed the window."""
    from ordane.desktop.glyphs import SHAPES
    from ordane.desktop.rail import PLACES

    for place in PLACES:
        name = place if isinstance(place, str) else place.name
        if name == "—":
            continue
        assert name.lower() in SHAPES, f"the {name} place has no glyph"


def test_an_unknown_glyph_falls_back_rather_than_raising(adw):
    from ordane.desktop.glyphs import Glyph

    assert Glyph("no-such-icon") is not None


# --- chart: drawing routines, against the inputs that have no shape ---


@pytest.mark.parametrize("series", [[], [1.0], [0.0, 0.0, 0.0], [3.0, 1.0, 4.0, 1.0, 5.0]])
def test_a_sparkline_takes_any_series_including_none_at_all(adw, series):
    from ordane.desktop.chart import Sparkline

    assert Sparkline(series) is not None


@pytest.mark.parametrize(
    ("value", "expected"), [(0.0, "0"), (1.0, "1"), (1.5, "1.5"), (1000.0, "1000")]
)
def test_a_figure_on_a_chart_is_written_the_way_a_person_writes_it(adw, value, expected):
    from ordane.desktop.chart import tidy

    assert tidy(value) == expected


# --- the dialogs, each of which is a path the window opens rarely ---


def test_the_stores_dialog_builds(adw):
    from ordane.desktop.storesetup import StoresDialog

    assert StoresDialog() is not None


def test_the_aws_inventory_dialog_builds(adw, tmp_path):
    from ordane.desktop.awsdialog import AwsInventoryDialog

    assert AwsInventoryDialog(repo=tmp_path) is not None


def test_the_checkup_dialog_draws_whatever_the_doctor_found(adw, tmp_path):
    from ordane.core import doctor
    from ordane.desktop.checkup import CheckupDialog

    report = doctor.examine(EXAMPLE_PLANE)
    dialog = CheckupDialog(report, EXAMPLE_PLANE)
    text = page_text(dialog)

    assert report.findings, "the doctor found nothing at all to say"
    assert report.headline in text, "the verdict the doctor reached is not on the dialog"
    for finding in report.findings:
        assert finding.title in text, f"{finding.title!r} was found and not drawn"


def test_the_paste_dialog_builds_for_every_kind_of_list_it_can_add_to(adw, tmp_path):
    from ordane.core import choices as choices_module
    from ordane.desktop.pastedialog import PasteDialog

    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    sources = [
        choices_module.source_for(param, scene.repo)
        for target in scene.catalog.targets
        for param in target.params.values()
    ]
    kinds = {s.noun: s for s in sources if s is not None}
    assert kinds, "the example plane offers no list a person can add to"
    for source in kinds.values():
        dialog = PasteDialog(source=source, repo=scene.repo, on_added=lambda *_: None)
        assert source.noun in page_text(dialog), f"the dialog never names the {source.noun}"
