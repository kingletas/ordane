"""Delivery: the measures, and the ones that cannot be measured yet."""

from __future__ import annotations

import shutil
from pathlib import Path

from conftest import EXAMPLE_PLANE, a_run, a_scene, page_text


def a_delivery_page():
    from ordane.desktop.deliverypage import DeliveryPage

    return DeliveryPage(on_remedy=lambda *_: None, on_go=lambda *_: None)


def a_plane_that_never_deployed(tmp_path) -> Path:
    """The example plane with its release history taken away, and nothing else changed."""
    bare = tmp_path / "never-deployed"
    if not bare.exists():
        shutil.copytree(EXAMPLE_PLANE, bare)
        (bare / "docs" / "dora" / "history.csv").unlink(missing_ok=True)
    return bare


def drawn(scene) -> str:
    page = a_delivery_page()
    page.render(scene.snapshot, scope=", ".join(scene.config.metric_environments))
    return page_text(page)


def test_it_builds(adw):
    assert a_delivery_page() is not None


def test_a_plane_that_has_deployed_nothing_draws_the_measures_anyway(adw, tmp_path):
    """Dormant is not the same as broken, and the page has to say which.

    Against a plane with no release history at all, which is what a console
    opened on a fresh control plane shows.
    """
    scene = a_scene(a_plane_that_never_deployed(tmp_path), tmp_path)
    assert not scene.snapshot.releases, "this fixture is supposed to have deployed nothing"

    text = drawn(scene)

    assert text.strip(), "no history drew an empty page"
    assert "Setup needed" not in text, "a dormant measure is drawn as a fault"


def test_a_plane_that_has_deployed_draws_what_was_measured(adw, tmp_path):
    """The other half, which nothing covered while every scene had an empty history."""
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_run()])
    assert scene.snapshot.releases, "the example plane's release history did not reach the scene"

    text = drawn(scene)

    # The page draws the figure and its unit as separate labels, so the figure
    # is what a test can ask for. An unmeasured one is the empty string, which
    # every page contains.
    figures = [m for m in scene.snapshot.measures if m.number]
    assert figures, "every measure came back without a figure"
    for measure in figures:
        assert measure.number in text, (
            f"{measure.key} was measured as {measure.number} and not drawn"
        )


def test_every_measure_reaches_the_page(adw, tmp_path):
    """Through the words the presentation layer chose, which is the actual contract."""
    from ordane.presentation import language

    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_run()])
    text = drawn(scene)
    assert scene.snapshot.measures, "the snapshot carries no measures"
    for measure in scene.snapshot.measures:
        shown = language.measure_name(measure.key, measure.label)
        assert shown in text, f"{shown} is computed and not drawn"
