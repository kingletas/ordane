"""Environments: what may be launched against, and what each one still needs."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_bare_plane, a_failed_run, a_scene, page_text


def an_environments_page():
    from ordane.desktop.environmentspage import EnvironmentsPage

    return EnvironmentsPage(
        on_manage=lambda *_: None, on_ask=lambda *_: None, on_run_here=lambda *_: None
    )


def drawn(scene) -> str:
    page = an_environments_page()
    page.render(scene.standings, source=scene.catalog.discovery.environment_source)
    return page_text(page)


def test_it_builds(adw):
    assert an_environments_page() is not None


def test_a_plane_declaring_none_draws_a_page(adw, tmp_path):
    scene = a_scene(a_bare_plane(tmp_path), tmp_path)
    assert drawn(scene).strip(), "no environments drew an empty page"


def test_every_declared_environment_is_drawn(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    text = drawn(scene)
    assert scene.standings, "the example plane declares no environments"
    for standing in scene.standings:
        assert standing.name in text, f"{standing.name} is declared and not drawn"


def test_a_failed_run_does_not_take_the_page_down(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_failed_run()])
    text = drawn(scene)
    for standing in scene.standings:
        assert standing.name in text
