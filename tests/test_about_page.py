"""About: what this copy is, where it reads from, and who wrote it."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_scene, page_text


def an_about_page():
    from ordane.desktop.aboutpage import AboutPage

    return AboutPage(
        on_copy=lambda *_: None, on_guide=lambda *_: None, on_shortcuts=lambda *_: None
    )


def test_it_builds(adw):
    assert an_about_page() is not None


def test_every_fact_it_is_given_is_drawn(adw, tmp_path):
    from ordane.core import plane as plane_module
    from ordane.desktop import aboutpage

    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    facts = aboutpage.facts(
        repo=scene.repo,
        plane=plane_module.of(scene.repo, scene.config.control_plane),
        state_dir=scene.state_dir,
        runs=0,
        history=scene.state_dir / "history.csv",
        events=scene.state_dir / "deployments.jsonl",
    )
    page = an_about_page()
    page.render(facts)
    text = page_text(page)

    assert facts, "the about page was given nothing to draw"
    for name, value in facts:
        assert name in text, f"the row {name!r} is missing"
        assert value in text, f"the value of {name!r} is missing"
