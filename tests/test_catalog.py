from ordane.core.catalog import discover_playbooks, parse_make_help

HELP = """Usage: make <target> environment=<env> [branch_name=...]

Environments (a directory under inventory/):
  docker
  staging
  performance  (no profile -- unusable)

Targets:
  check: everything verifiable without contacting a host
  deploy: build and deploy in one shot (needs environment=)
  docker-up: build and start the fake fleet

Shortcuts: stage (staging), development (newdev)
"""


def test_targets_are_read_with_their_descriptions():
    targets, _, _ = parse_make_help(HELP)
    assert [t.name for t in targets] == ["check", "deploy", "docker-up"]
    assert targets[1].description == "build and deploy in one shot (needs environment=)"


def test_an_environment_with_a_parenthesised_reason_is_unusable():
    _, environments, _ = parse_make_help(HELP)
    assert [e.name for e in environments] == ["docker", "staging", "performance"]
    assert environments[0].usable
    assert not environments[2].usable
    assert environments[2].reason == "no profile"


def test_shortcuts_are_captured():
    _, _, shortcuts = parse_make_help(HELP)
    assert shortcuts[0] == "stage"


def test_empty_help_yields_nothing_rather_than_raising():
    targets, environments, shortcuts = parse_make_help("")
    assert (targets, environments, shortcuts) == ([], [], [])


def test_requirements_yml_is_not_offered_as_a_playbook(tmp_path):
    (tmp_path / "playbook.yml").write_text("---")
    (tmp_path / "requirements.yml").write_text("---")
    (tmp_path / ".ordane.yml").write_text("---")
    found = discover_playbooks(tmp_path, ["*.yml"])
    assert [p.path for p in found] == ["playbook.yml"]


def test_the_reason_drops_the_verdict_make_help_already_wrote():
    _, environments, _ = parse_make_help(
        "Environments:\n  staging  (no inventory - unusable)\n  perf  (no profile -- not usable)\n"
    )
    assert environments[0].reason == "no inventory"
    assert environments[1].reason == "no profile"


def test_an_environment_flagged_with_nothing_but_a_verdict_is_still_unusable():
    _, environments, _ = parse_make_help("Environments:\n  odd  (-- unusable)\n")
    assert environments[0].usable is False
    assert environments[0].blocked_reason == "unusable"
