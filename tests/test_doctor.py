from pathlib import Path

from ordane.core import doctor

HELP = """all:
	@true

# A real control plane reads the variable the console assigns; the doctor
# fails a Makefile that does not, so the fixture has to be realistic.
deploy:
	@ansible-playbook -i inventory/$(environment) deploy.yml

help:
	@echo "Environments (a directory under inventory/):"
	@echo "  docker"
	@echo "  broken  (no inventory -- unusable)"
	@echo ""
	@echo "Targets:"
	@echo "  deploy: build and deploy"
	@echo "  ping: check every host answers"
	@echo ""
	@echo "Shortcuts: stage (staging)"
"""


def a_repo(tmp_path: Path, config: str = "") -> Path:
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / "Makefile").write_text(HELP, encoding="utf-8")
    if config:
        (repo / ".ordane.yml").write_text(config, encoding="utf-8")
    return repo


def levels(report, level):
    return [f.title for f in report.findings if f.level == level]


def test_a_healthy_control_plane_reports_no_failures(tmp_path):
    repo = a_repo(tmp_path, "environments:\n  allow: [docker]\n")
    report = doctor.examine(repo)
    assert report.healthy
    assert "2 targets" in " ".join(levels(report, doctor.OK))


def test_no_allow_list_is_a_warning_with_the_way_out(tmp_path):
    report = doctor.examine(a_repo(tmp_path, "environments:\n  allow: []\n"))
    warning = next(f for f in report.findings if f.title.startswith("Read-only"))
    assert "environments.allow" in warning.fix
    assert report.healthy


def test_an_environment_that_make_help_never_prints_is_a_failure(tmp_path):
    report = doctor.examine(a_repo(tmp_path, "environments:\n  allow: [dokcer]\n"))
    assert not report.healthy
    failure = next(f for f in report.failures if "allow list names" in f.title)
    assert "dokcer" in failure.detail
    assert "docker" in failure.fix


def test_a_shortcut_is_a_real_target_and_is_not_reported_as_stale(tmp_path):
    config = "environments:\n  allow: [docker]\ngroups:\n  Release: [stage, deploy]\n"
    report = doctor.examine(a_repo(tmp_path, config))
    assert not [f for f in report.findings if "no longer exist" in f.title]


def test_a_target_the_makefile_dropped_is_reported(tmp_path):
    config = "environments:\n  allow: [docker]\ngroups:\n  Release: [deploy, gone-away]\n"
    report = doctor.examine(a_repo(tmp_path, config))
    stale = next(f for f in report.findings if "no longer exist" in f.title)
    assert "gone-away" in stale.detail


def test_a_fixed_environment_that_does_not_exist_is_a_failure(tmp_path):
    config = "environments:\n  allow: [docker]\ntargets:\n  deploy:\n    environment: ghost\n"
    report = doctor.examine(a_repo(tmp_path, config))
    assert any("does not exist" in f.title for f in report.failures)


def test_a_required_choice_list_that_matches_nothing_is_a_failure(tmp_path):
    config = (
        "environments:\n  allow: [docker]\n"
        "targets:\n  deploy:\n    params:\n      patch:\n"
        "        required: true\n        choices_from: patches\n"
    )
    report = doctor.examine(a_repo(tmp_path, config))
    assert any("no values to offer" in f.title for f in report.failures)


def test_unreadable_yaml_stops_at_one_finding(tmp_path):
    report = doctor.examine(a_repo(tmp_path, "environments: [\n"))
    assert len(report.findings) == 1
    assert not report.healthy


def test_a_folder_with_nothing_to_drive_says_so(tmp_path):
    report = doctor.examine(tmp_path)
    assert not report.healthy
    assert "neither a Makefile nor any playbooks" in report.failures[0].title


def test_a_front_end_can_add_a_finding_the_engine_cannot_answer(tmp_path):
    extra = doctor.Finding(doctor.WARN, "No toolkit here", "", "install it")
    report = doctor.examine(a_repo(tmp_path, "environments:\n  allow: [docker]\n"), extra=[extra])
    assert report.findings[-1] is extra
    assert report.healthy


def test_the_desktop_probe_answers_rather_than_raising():
    from ordane.desktop.availability import finding

    assert finding().level in (doctor.OK, doctor.WARN)


# --- the environment variable, which is the silent one ---

SCRIPTED = """help:
\t@echo "Usage: make <target> environment=<env>"
\t@echo ""
\t@echo "Environments (a directory under inventory/):"
\t@echo "  docker"
\t@echo ""
\t@echo "Targets:"
\t@echo "  deploy: build and deploy"

deploy:
\t@bin/deploy
"""

MISMATCHED = """help:
\t@echo "Environments (a directory under inventory/):"
\t@echo "  docker"
\t@echo ""
\t@echo "Targets:"
\t@echo "  deploy: build and deploy"

deploy:
\t@ansible-playbook -i inventory/$(env) deploy.yml
"""


def a_plane(tmp_path, makefile, name, config="environments:\n  allow: [docker]\n"):
    repo = tmp_path / name
    repo.mkdir()
    (repo / "Makefile").write_text(makefile, encoding="utf-8")
    (repo / ".ordane.yml").write_text(config, encoding="utf-8")
    return repo


def test_a_variable_only_a_script_reads_is_not_reported(tmp_path):
    """The shape of the control plane this was built for: `make help` documents
    the variable, a recipe hands it to a script, and no Makefile mentions it."""
    report = doctor.examine(a_plane(tmp_path, SCRIPTED, "scripted"))
    assert not [f for f in report.findings if "mentions" in f.title]


def test_a_variable_nothing_mentions_is_a_warning_not_a_failure(tmp_path):
    report = doctor.examine(a_plane(tmp_path, MISMATCHED, "mismatched"))
    finding = next(f for f in report.findings if "mentions" in f.title)
    assert finding.level == doctor.WARN
    assert "env" in finding.fix
    assert report.healthy, "a check that cannot be sure must not fail the report"


def test_a_control_plane_with_no_environments_is_not_asked_about_a_variable(tmp_path):
    bare = "build: ## Build it\n\t@true\n"
    report = doctor.examine(a_plane(tmp_path, bare, "bare", "environments:\n  allow: [default]\n"))
    assert not [f for f in report.findings if "mentions" in f.title]


def _titled(report, fragment: str):
    return [f for f in report.findings if fragment in f.title]


def test_a_plane_with_no_ansible_cfg_is_warned_about(tmp_path, monkeypatch):
    """Every setting is an Ansible default and nothing else would ever say so."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nobody")
    report = doctor.examine(a_repo(tmp_path))
    found = _titled(report, "has no ansible.cfg")
    assert len(found) == 1
    assert found[0].level == doctor.WARN
    assert "vault password file" in found[0].detail


def test_a_plane_with_one_is_silent_about_it(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nobody")
    repo = a_repo(tmp_path)
    (repo / "ansible.cfg").write_text("[defaults]\nforks = 17\n", encoding="utf-8")
    report = doctor.examine(repo)
    assert not _titled(report, "has no ansible.cfg")
    assert _titled(report, "Ansible is configured by")[0].level == doctor.OK


def test_declared_settings_are_reported_as_filling_the_gap(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nobody")
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_ROLES_PATH: ./roles\n")
    report = doctor.examine(repo)
    found = _titled(report, "configured by .ordane.yml alone")
    assert len(found) == 1
    assert "ANSIBLE_ROLES_PATH" in found[0].detail


def test_declared_settings_are_reported_as_adding_to_a_cfg(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path / "nobody")
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_ROLES_PATH: ./roles\n")
    (repo / "ansible.cfg").write_text("[defaults]\nforks = 17\n", encoding="utf-8")
    report = doctor.examine(repo)
    found = _titled(report, "Ansible is configured by")
    assert "on top of it" in found[0].detail


def test_a_callback_that_would_empty_every_recap_is_warned_about(tmp_path):
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_STDOUT_CALLBACK: minimal\n")
    found = _titled(doctor.examine(repo), "ANSIBLE_STDOUT_CALLBACK")
    assert len(found) == 1
    assert found[0].level == doctor.WARN


def test_the_default_callback_is_not_warned_about(tmp_path):
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_STDOUT_CALLBACK: default\n")
    assert not _titled(doctor.examine(repo), "ANSIBLE_STDOUT_CALLBACK")


def test_a_refused_setting_stops_the_console_with_its_reason(tmp_path):
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_CONFIG: ./ours.cfg\n")
    report = doctor.examine(repo)
    assert not report.healthy
    assert "vault_password_file" in report.failures[0].detail


def test_a_misspelt_setting_is_named(tmp_path):
    """Ansible ignores a variable it does not recognise without a word."""
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_ROLESPATH: ./roles\n")
    found = _titled(doctor.examine(repo), "does not recognise")
    assert len(found) == 1
    assert found[0].level == doctor.WARN
    assert "ANSIBLE_ROLESPATH" in found[0].title


def test_a_setting_ansible_knows_is_not_named(tmp_path):
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_ROLES_PATH: ./roles\n")
    report = doctor.examine(repo)
    assert not _titled(report, "does not recognise")
    assert (
        "Every name is one Ansible knows" in _titled(report, "Ansible is configured by")[0].detail
    )


def test_a_plane_declaring_nothing_never_asks_ansible(tmp_path, monkeypatch):
    """The check is silent, and it does not pay for a subprocess either."""
    from ordane.core import settings as settings_module

    def refuse():
        raise AssertionError("ansible-config was asked for a plane that declares nothing")

    monkeypatch.setattr(settings_module, "known_names", refuse)
    report = doctor.examine(a_repo(tmp_path))
    assert not _titled(report, "does not recognise")


def test_it_says_so_when_ansible_could_not_be_asked(tmp_path, monkeypatch):
    from ordane.core import settings as settings_module

    monkeypatch.setattr(settings_module, "known_names", lambda: None)
    repo = a_repo(tmp_path, "ansible:\n  ANSIBLE_ROLESPATH: ./roles\n")
    report = doctor.examine(repo)
    assert not _titled(report, "does not recognise"), "an unasked question is not a finding"
    detail = _titled(report, "Ansible is configured by")[0].detail
    assert "could not be asked" in detail


def test_the_former_config_name_is_still_read(tmp_path):
    """A control plane written before the rename keeps working."""
    repo = a_repo(tmp_path)
    (repo / ".ansible-gui.yml").write_text("environments:\n  allow: [docker]\n", encoding="utf-8")
    report = doctor.examine(repo)
    assert not _titled(report, "There is no"), "the old name was not read"
    found = _titled(report, "under its former name")
    assert len(found) == 1
    assert found[0].level == doctor.OK
    assert "git mv" in found[0].fix


def test_the_current_name_wins_where_a_repo_has_both(tmp_path):
    repo = a_repo(tmp_path, "environments:\n  allow: [docker]\n")
    (repo / ".ansible-gui.yml").write_text("environments:\n  allow: []\n", encoding="utf-8")
    report = doctor.examine(repo)
    assert _titled(report, "is present")[0].title.startswith(".ordane.yml")
    assert not _titled(report, "under its former name")
