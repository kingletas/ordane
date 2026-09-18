"""Preferences: a place rather than a dialog, and nothing on it that does nothing."""

from __future__ import annotations

from conftest import page_text


def a_prefs_page(state_dir):
    from ordane.desktop.prefspage import PrefsPage

    return PrefsPage(
        state_dir=state_dir,
        on_theme=lambda *_: None,
        on_density=lambda *_: None,
        on_switch=lambda *_: None,
        on_navigation=lambda *_: None,
    )


def test_it_builds(adw, tmp_path):
    assert a_prefs_page(tmp_path) is not None


def test_it_draws_against_a_state_directory_that_does_not_exist_yet(adw, tmp_path):
    """A first launch has written no settings file, which is the path least run."""
    page = a_prefs_page(tmp_path / "never-written")
    page.render()
    assert page_text(page).strip(), "preferences drew nothing on a first launch"


def test_what_is_not_built_is_named_rather_than_offered(adw, tmp_path):
    """A switch that looks like a setting and changes nothing is worse than none."""
    from ordane.desktop.prefspage import NOT_YET

    page = a_prefs_page(tmp_path)
    page.render()
    assert NOT_YET in page_text(page), (
        "the note naming what this console cannot do yet is not on the page"
    )
