"""Actions: the page anything gets run from, and the one a mistake is expensive on."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_bare_plane, a_scene, page_text


def an_actions_page():
    from ordane.desktop.actionspage import ActionsPage

    return ActionsPage(
        on_launch=lambda *_: None, on_open_full=lambda *_: None, on_search=lambda *_: None
    )


def drawn(scene, needle: str = "") -> str:
    page = an_actions_page()
    page.render(catalog=scene.catalog, config=scene.config, needle=needle, hosts={})
    return page_text(page)


def test_it_builds(adw):
    assert an_actions_page() is not None


def test_a_plane_with_one_target_still_draws_a_page(adw, tmp_path):
    scene = a_scene(a_bare_plane(tmp_path), tmp_path)
    assert drawn(scene).strip(), "a bare control plane drew nothing at all"


def test_what_the_repository_declares_reaches_the_page(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    text = drawn(scene)
    assert scene.catalog.targets, "the example plane declares no runnable target"
    assert scene.catalog.targets[0].name in text, (
        "the first thing a person can run is not on the page"
    )


def test_a_search_that_matches_nothing_says_so(adw, tmp_path):
    """An empty list with no sentence reads as a broken page rather than no match."""
    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    text = drawn(scene, needle="zzzzzz-no-such-target")
    assert text.strip(), "a search with no matches drew an empty page"
    assert "zzzzzz-no-such-target" in text or "nothing" in text.lower()
