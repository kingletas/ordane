"""The form is built for real targets, so a broken row is caught by `make check`.

Nothing here drives the widgets — the window smoke does that. This is the
cheaper half: every kind of parameter builds its row without raising, which is
the failure that reached a live window once already.
"""

from __future__ import annotations

from pathlib import Path

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ordane.core import catalog as catalog_module  # noqa: E402
from ordane.core import config as config_module  # noqa: E402

PLANE = Path(__file__).resolve().parents[1] / "examples" / "control-plane"


def a_form(name: str):
    Adw.init()
    from ordane.desktop.launch import LaunchDialog

    config = config_module.load(PLANE)
    catalog = catalog_module.build(PLANE, config)
    target = catalog.target(name)
    assert target is not None, f"{name} is not in the example plane"
    return LaunchDialog(
        target=target,
        catalog=catalog,
        config=config,
        repo=PLANE,
        on_launch=lambda *_: None,
    )


def test_a_target_with_no_parameters_builds():
    assert a_form("ping") is not None


def test_a_free_text_parameter_builds():
    form = a_form("build")
    assert isinstance(form._fields["branch_name"], Gtk.Entry)


def test_a_short_fixed_list_is_a_dropdown():
    """`present` or `absent` is quicker to see than to type."""
    assert isinstance(a_form("patch-fleet")._fields["state"], Adw.ComboRow)


def test_a_list_read_from_a_folder_is_typed_into():
    """It can be added to, so it needs a field the paste row can hang under."""
    assert isinstance(a_form("patch-fleet")._fields["patch"], Gtk.Entry)


def test_the_typed_field_carries_a_completer():
    field = a_form("patch-fleet")._fields["patch"]
    assert getattr(field, "_completer", None) is not None


def test_a_field_with_nothing_to_complete_carries_none():
    field = a_form("build")._fields["branch_name"]
    assert getattr(field, "_completer", None) is None


def test_a_required_parameter_holds_the_run_button():
    form = a_form("patch-fleet")
    assert not form._run_button.get_sensitive()
    assert "required" in (form._run_button.get_tooltip_text() or "")


def test_the_example_is_shown_where_the_makefile_gave_one():
    form = a_form("activate")
    assert form._fields["release"].get_placeholder_text()


# --- how exposed the run is, decided by the environment it is aimed at ---

A_PLANE = """
help:
\t@echo "Environments with a profile and an inventory:"
\t@echo "  docker"
\t@echo "  production"
\t@echo ""
\t@echo "Targets:"
\t@echo "  ping: check that every host answers"

ping:
\t@ansible all -m ping
"""


def a_plane(tmp_path):
    (tmp_path / "Makefile").write_text(A_PLANE)
    for name in ("docker", "production"):
        (tmp_path / "inventory").mkdir(exist_ok=True)
        (tmp_path / "inventory" / name).write_text("localhost ansible_connection=local\n")
    (tmp_path / ".ordane.yml").write_text(
        "environments:\n  allow: [docker, production]\n  names: [docker, production]\n"
    )
    Adw.init()
    from ordane.desktop.launch import LaunchDialog

    config = config_module.load(tmp_path)
    catalog = catalog_module.build(tmp_path, config)
    return LaunchDialog(
        target=catalog.target("ping"),
        catalog=catalog,
        config=config,
        repo=tmp_path,
        on_launch=lambda *_: None,
    )


def aim(form, environment: str) -> None:
    combo = form._fields["environment"]
    model = combo.get_model()
    for index in range(model.get_n_items()):
        if model.get_string(index) == environment:
            combo.set_selected(index)
            return
    raise AssertionError(f"{environment} is not offered")


def test_a_harmless_action_on_a_safe_environment_says_nothing(tmp_path):
    form = a_plane(tmp_path)
    aim(form, "docker")
    assert not form._exposure.get_revealed()
    assert form._run_button.has_css_class("suggested-action")


def test_the_same_action_on_production_is_warned_about(tmp_path):
    """`ping` is rated `low`, and this is the whole point of the rule."""
    form = a_plane(tmp_path)
    aim(form, "production")
    assert form._exposure.get_revealed()
    assert "Customers are on production" in form._exposure.get_title()
    assert form._run_button.has_css_class("destructive-action")


def test_changing_the_environment_back_clears_the_warning(tmp_path):
    """The banner follows the chooser: it is built once and kept in step."""
    form = a_plane(tmp_path)
    aim(form, "production")
    aim(form, "docker")
    assert not form._exposure.get_revealed()
    assert not form._run_button.has_css_class("destructive-action")
