"""Delivery: the measures, and the ones that cannot be measured yet."""

from __future__ import annotations

from conftest import EXAMPLE_PLANE, a_run, a_scene, page_text


def a_delivery_page():
    from ordane.desktop.deliverypage import DeliveryPage

    return DeliveryPage(on_remedy=lambda *_: None, on_go=lambda *_: None)


def drawn(scene) -> str:
    page = a_delivery_page()
    page.render(scene.snapshot, scope=", ".join(scene.config.metric_environments))
    return page_text(page)


def test_it_builds(adw):
    assert a_delivery_page() is not None


def test_a_plane_that_has_deployed_nothing_draws_the_measures_anyway(adw, tmp_path):
    """Dormant is not the same as broken, and the page has to say which."""
    scene = a_scene(EXAMPLE_PLANE, tmp_path)
    text = drawn(scene)
    assert text.strip(), "no history drew an empty page"
    assert "Setup needed" not in text, "a dormant measure is drawn as a fault"


def test_every_measure_reaches_the_page(adw, tmp_path):
    """Through the words the presentation layer chose, which is the actual contract."""
    from ordane.presentation import language

    scene = a_scene(EXAMPLE_PLANE, tmp_path, runs=[a_run()])
    text = drawn(scene)
    assert scene.snapshot.measures, "the snapshot carries no measures"
    for measure in scene.snapshot.measures:
        shown = language.measure_name(measure.key, measure.label)
        assert shown in text, f"{shown} is computed and not drawn"
