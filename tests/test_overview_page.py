"""The first screen, against the four things any page has to survive.

It builds, it draws with nothing to draw, it puts the engine's own values on
the page, and it shows a failure as a failure. The ledger page's unguarded
lookup was the first of those, on a path nothing had ever run.
"""

from __future__ import annotations

import pytest
from conftest import EXAMPLE_PLANE, a_bare_plane, a_failed_run, a_run, a_scene, page_text


def an_overview():
    from ordane.desktop.overview import Overview

    return Overview(on_open_run=lambda *_: None, on_remedy=lambda *_: None, on_go=lambda *_: None)


def drawn(scene) -> str:
    page = an_overview()
    page.render(
        catalog=scene.catalog,
        snapshot=scene.snapshot,
        verdict=scene.verdict,
        setup=scene.setup,
        runs=scene.runs,
        standings=scene.standings,
        animate=False,
    )
    return page_text(page)


def test_it_builds(adw):
    assert an_overview() is not None


def test_a_first_launch_draws_a_page_rather_than_nothing(adw, tmp_path):
    """No history, no runs, no ledger. This is the screen somebody new sees."""
    scene = a_scene(a_bare_plane(tmp_path), tmp_path)
    text = drawn(scene)

    assert scene.verdict.headline in text, "the verdict never reached the page"
    assert text.strip(), "an empty control plane drew an empty page"


def test_the_engine_s_own_values_reach_the_labels(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_run()])
    text = drawn(scene)

    assert scene.verdict.headline in text
    for standing in scene.standings:
        assert standing.name in text, f"{standing.name} is declared and not drawn"


def test_a_failure_is_drawn_as_one(adw, tmp_path):
    """The browser drew a problem in the class it uses to play something down."""
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_failed_run()])
    text = drawn(scene)

    assert scene.verdict.state != "ready", "a failed run left the verdict ready"
    assert scene.verdict.headline in text
    assert scene.verdict.state in text, "the page draws no severity for the verdict"


@pytest.mark.parametrize("runs", [(), (a_run(),), (a_failed_run(),)])
def test_it_survives_being_drawn_twice(adw, tmp_path, runs):
    """A refresh re-renders the same page, and that path is where state leaks."""
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=list(runs))
    page = an_overview()
    for _ in range(2):
        page.render(
            catalog=scene.catalog,
            snapshot=scene.snapshot,
            verdict=scene.verdict,
            setup=scene.setup,
            runs=scene.runs,
            standings=scene.standings,
            animate=False,
        )
    assert scene.verdict.headline in page_text(page)
