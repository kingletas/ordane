"""The Ansible settings a control plane may declare, and the three it may not.

Every refusal here was measured against a real `ansible-config dump` before it
was written: ANSIBLE_CONFIG replaces the repository's file rather than adding
to it, and only Ansible's default callback prints a PLAY RECAP.
"""

from __future__ import annotations

import pytest

from ordane.core import config as config_module
from ordane.core import settings as settings_module


def test_no_block_declares_nothing():
    declared = settings_module.read(None)
    assert not declared
    assert declared.names == []


def test_a_setting_becomes_one_environment_variable():
    declared = settings_module.read({"ANSIBLE_ROLES_PATH": "./roles"})
    assert declared.values == {"ANSIBLE_ROLES_PATH": "./roles"}
    assert declared.applied_to({"PATH": "/usr/bin"}) == {
        "PATH": "/usr/bin",
        "ANSIBLE_ROLES_PATH": "./roles",
    }


def test_it_adds_rather_than_replaces():
    """The whole reason env vars were chosen over ANSIBLE_CONFIG."""
    before = {"ANSIBLE_FORCE_COLOR": "1", "HOME": "/home/you"}
    after = settings_module.read({"ANSIBLE_TIMEOUT": "60"}).applied_to(before)
    assert after["ANSIBLE_FORCE_COLOR"] == "1"
    assert after["HOME"] == "/home/you"
    assert after["ANSIBLE_TIMEOUT"] == "60"


def test_booleans_are_written_the_way_ansible_reads_them():
    declared = settings_module.read({"ANSIBLE_HOST_KEY_CHECKING": False})
    assert declared.values == {"ANSIBLE_HOST_KEY_CHECKING": "False"}


def test_numbers_survive_as_strings():
    assert settings_module.read({"ANSIBLE_FORKS": 17}).values == {"ANSIBLE_FORKS": "17"}


def test_the_whole_file_switch_is_refused_with_its_reason():
    with pytest.raises(settings_module.SettingsError) as raised:
        settings_module.read({"ANSIBLE_CONFIG": "./ours.cfg"})
    assert "vault_password_file" in str(raised.value)


def test_a_credential_value_is_refused():
    with pytest.raises(settings_module.SettingsError):
        settings_module.read({"ANSIBLE_VAULT_PASSWORD": "hunter2000"})


def test_but_the_file_that_holds_one_is_allowed():
    """The path is not the secret, and it is the setting this estate actually uses."""
    where = "~/.secrets/prod.pass"
    declared = settings_module.read({"ANSIBLE_VAULT_PASSWORD_FILE": where})
    assert declared.values["ANSIBLE_VAULT_PASSWORD_FILE"] == where


def test_a_key_that_is_not_an_ansible_setting_is_refused():
    with pytest.raises(settings_module.SettingsError) as raised:
        settings_module.read({"roles_path": "./roles"})
    assert "ANSIBLE_ROLES_PATH" in str(raised.value)


def test_a_value_that_is_not_scalar_is_refused():
    with pytest.raises(settings_module.SettingsError):
        settings_module.read({"ANSIBLE_ROLES_PATH": ["./roles", "./other"]})


def test_a_key_with_no_value_is_refused():
    with pytest.raises(settings_module.SettingsError):
        settings_module.read({"ANSIBLE_ROLES_PATH": None})


def test_the_block_must_be_a_mapping():
    with pytest.raises(settings_module.SettingsError):
        settings_module.read(["ANSIBLE_ROLES_PATH=./roles"])


def test_the_default_callback_keeps_the_recap():
    assert settings_module.read({"ANSIBLE_STDOUT_CALLBACK": "default"}).recap_at_risk == ""


def test_any_other_callback_is_named_as_at_risk():
    """Measured: minimal, oneline and json each print no PLAY RECAP at all."""
    for callback in ("minimal", "oneline", "json"):
        declared = settings_module.read({"ANSIBLE_STDOUT_CALLBACK": callback})
        assert declared.recap_at_risk == callback


def test_nothing_declared_puts_nothing_at_risk():
    assert settings_module.read({"ANSIBLE_FORKS": "5"}).recap_at_risk == ""


def test_the_display_is_what_you_could_paste():
    declared = settings_module.read({"ANSIBLE_FORKS": "5", "ANSIBLE_TIMEOUT": "60"})
    assert declared.display == "ANSIBLE_FORKS=5 ANSIBLE_TIMEOUT=60"


def test_the_config_reads_the_block(tmp_path):
    (tmp_path / ".ordane.yml").write_text(
        "ansible:\n  ANSIBLE_ROLES_PATH: ./roles\n  ANSIBLE_FORKS: 20\n"
    )
    config = config_module.load(tmp_path)
    assert config.ansible.values == {"ANSIBLE_ROLES_PATH": "./roles", "ANSIBLE_FORKS": "20"}


def test_a_refused_setting_fails_the_whole_config(tmp_path):
    """It is a config error like any other, so the doctor reports it the same way."""
    (tmp_path / ".ordane.yml").write_text("ansible:\n  ANSIBLE_CONFIG: ./ours.cfg\n")
    with pytest.raises(config_module.ConfigError):
        config_module.load(tmp_path)


def test_a_config_with_no_block_declares_nothing(tmp_path):
    (tmp_path / ".ordane.yml").write_text("driver: make\n")
    assert not config_module.load(tmp_path).ansible


# --- what Ansible itself recognises, which is the difference between a setting
#     that applies and a typo that is ignored in silence ---


def test_ansible_is_asked_what_it_knows():
    names = settings_module.known_names()
    assert names is not None, "ansible-config could not be read"
    assert "ANSIBLE_ROLES_PATH" in names
    assert "ANSIBLE_VAULT_PASSWORD_FILE" in names
    assert "ANSIBLE_ROLESPATH" not in names


def test_it_answers_none_rather_than_empty_when_it_cannot_ask(monkeypatch):
    """None and an empty set are not the same claim: one means Ansible knows
    nothing, the other means nobody looked. Reporting a typo in every declared
    name on a machine with no ansible-config is what this prevents."""
    monkeypatch.setattr(settings_module.host, "which", lambda _name: None)
    assert settings_module.known_names() is None


def test_a_failing_ansible_config_is_not_read_as_an_answer(monkeypatch):
    class Failed:
        returncode = 1
        stdout = ""

    monkeypatch.setattr(settings_module.host, "which", lambda _name: "/usr/bin/ansible-config")
    monkeypatch.setattr(settings_module.subprocess, "run", lambda *a, **k: Failed())
    assert settings_module.known_names() is None


def test_unreadable_output_is_not_read_as_an_answer(monkeypatch):
    class Garbage:
        returncode = 0
        stdout = "not json at all"

    monkeypatch.setattr(settings_module.host, "which", lambda _name: "/usr/bin/ansible-config")
    monkeypatch.setattr(settings_module.subprocess, "run", lambda *a, **k: Garbage())
    assert settings_module.known_names() is None


def test_a_config_under_the_former_name_is_loaded(tmp_path):
    """The rename must not quietly empty a control plane's configuration."""
    (tmp_path / ".ansible-gui.yml").write_text("ansible:\n  ANSIBLE_ROLES_PATH: ./roles\n")
    assert config_module.load(tmp_path).ansible.values == {"ANSIBLE_ROLES_PATH": "./roles"}


def test_the_current_name_is_preferred(tmp_path):
    (tmp_path / ".ansible-gui.yml").write_text("ansible:\n  ANSIBLE_FORKS: 1\n")
    (tmp_path / ".ordane.yml").write_text("ansible:\n  ANSIBLE_FORKS: 99\n")
    assert config_module.load(tmp_path).ansible.values == {"ANSIBLE_FORKS": "99"}
