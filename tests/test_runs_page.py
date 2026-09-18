"""Runs: the history, and the decisions taken beside it."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_failed_run, a_run, a_scene, page_text


def a_runs_page():
    from gi.repository import Gtk

    from ordane.desktop.runspage import RunsPage

    return RunsPage(detail=Gtk.Box(), on_open=lambda *_: None)


def drawn(runs, decisions=()) -> str:
    page = a_runs_page()
    page.render(list(runs), list(decisions))
    return page_text(page)


def test_it_builds(adw):
    assert a_runs_page() is not None


def test_a_history_with_nothing_in_it_says_so(adw):
    text = drawn([])
    assert text.strip(), "no runs drew an empty page instead of a sentence"


def test_a_run_reaches_the_page(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_run()])
    text = drawn(scene.runs)
    assert scene.runs[0].name in text
    assert scene.runs[0].environment in text


def test_a_failed_run_is_drawn_as_failed(adw, tmp_path):
    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_failed_run()])
    text = drawn(scene.runs)
    assert scene.runs[0].name in text
    assert "failed" in text.lower(), "a failed run is drawn with no sign it failed"
