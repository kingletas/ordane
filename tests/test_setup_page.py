"""Setup: the ordered list of what is not finished, on a first launch."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_bare_plane, a_scene, page_text


def a_setup_page():
    from ordane.desktop.setuppage import SetupPage

    return SetupPage(on_remedy=lambda *_: None)


def drawn(scene) -> str:
    page = a_setup_page()
    page.render(scene.setup)
    return page_text(page)


def test_it_builds(adw):
    assert a_setup_page() is not None


def test_a_plane_with_nothing_configured_lists_its_steps(adw, tmp_path):
    scene = a_scene(a_bare_plane(tmp_path), tmp_path)
    text = drawn(scene)
    assert scene.setup.steps, "the setup sequence has no steps at all"
    for step in scene.setup.steps:
        assert step.title in text, f"step {step.title!r} is not on the page"


def test_a_configured_plane_still_draws_the_sequence(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    text = drawn(scene)
    for step in scene.setup.steps:
        assert step.title in text
