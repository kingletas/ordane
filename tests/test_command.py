import pytest

from ordane.core import command
from ordane.core.catalog import Catalog, Environment, Playbook, Target
from ordane.core.command import (
    ValidationError,
    for_playbook,
    for_target,
    validate_environment,
    validate_params,
)
from ordane.core.config import Config, Param


def catalog(**kwargs):
    return Catalog(
        targets=kwargs.get("targets", []),
        environments=kwargs.get(
            "environments",
            [
                Environment("docker", usable=True, allowed=True),
                Environment("production", usable=True, allowed=False),
                Environment("performance", usable=False, reason="no profile", allowed=True),
            ],
        ),
        playbooks=kwargs.get("playbooks", [Playbook("playbook.yml", "playbook.yml")]),
        shortcuts=[],
    )


def test_an_allow_listed_environment_passes():
    assert validate_environment(catalog(), "docker") == "docker"


def test_an_environment_outside_the_allow_list_is_refused():
    with pytest.raises(ValidationError, match="not in the allow list"):
        validate_environment(catalog(), "production")


def test_an_unusable_environment_is_refused_with_its_reason():
    with pytest.raises(ValidationError, match="no profile"):
        validate_environment(catalog(), "performance")


def test_an_unknown_environment_is_refused():
    with pytest.raises(ValidationError, match="unknown environment"):
        validate_environment(catalog(), "typo")


def test_a_value_outside_the_choice_list_is_refused(tmp_path):
    target = Target(
        name="patch-fleet",
        description="",
        params={"state": Param("state", choices=["present", "absent"])},
    )
    with pytest.raises(ValidationError, match="not one of the permitted values"):
        validate_params(target, {"state": "wipe"}, catalog(), tmp_path)


def test_a_shell_metacharacter_is_refused(tmp_path):
    target = Target(name="magento", description="", params={"cmd": Param("cmd", allow_other=True)})
    with pytest.raises(ValidationError, match="not permitted"):
        validate_params(target, {"cmd": "cache:flush; rm -rf /"}, catalog(), tmp_path)


def test_a_backtick_is_refused(tmp_path):
    target = Target(name="magento", description="", params={"cmd": Param("cmd", allow_other=True)})
    with pytest.raises(ValidationError, match="not permitted"):
        validate_params(target, {"cmd": "`id`"}, catalog(), tmp_path)


def test_a_required_parameter_that_is_missing_is_refused(tmp_path):
    target = Target(name="magento", description="", params={"cmd": Param("cmd", required=True)})
    with pytest.raises(ValidationError, match="required"):
        validate_params(target, {}, catalog(), tmp_path)


def test_an_undeclared_parameter_is_refused(tmp_path):
    target = Target(name="ping", description="")
    with pytest.raises(ValidationError, match="unknown parameter"):
        validate_params(target, {"sneaky": "value"}, catalog(), tmp_path)


def test_a_target_command_carries_the_environment_assignment():
    target = Target(name="flush-cache", description="")
    built = for_target(target=target, environment="docker", params={}, config=Config())
    assert built.argv == ["make", "flush-cache", "environment=docker"]


def test_a_fixed_environment_target_is_launched_without_an_assignment():
    target = Target(name="stage", description="", fixed_environment="staging")
    built = for_target(target=target, environment="staging", params={}, config=Config())
    assert built.argv == ["make", "stage"]


def test_dry_run_is_only_added_when_the_target_supports_it():
    plain = Target(name="ping", description="")
    supported = Target(name="deploy", description="", dry_run=True)
    assert (
        "EXTRA=--check"
        not in for_target(
            target=plain, environment="docker", params={}, config=Config(), dry_run=True
        ).argv
    )
    assert (
        "EXTRA=--check"
        in for_target(
            target=supported, environment="docker", params={}, config=Config(), dry_run=True
        ).argv
    )


def test_the_playbook_template_is_substituted():
    built = for_playbook(
        playbook="playbook.yml",
        environment="docker",
        template=["ansible-playbook", "-i", "inventory/{environment}", "{playbook}"],
        flags={"check": True},
        limit="apps",
        verbosity=2,
    )
    assert built.argv == [
        "ansible-playbook",
        "-i",
        "inventory/docker",
        "playbook.yml",
        "--check",
        "--limit",
        "apps",
        "-vv",
    ]


def test_a_limit_with_a_metacharacter_is_refused():
    with pytest.raises(ValidationError, match="not permitted"):
        for_playbook(
            playbook="playbook.yml",
            environment="docker",
            template=["ansible-playbook", "{playbook}"],
            flags={},
            limit="apps; whoami",
        )


# --- the run options that existed and were never offered ---


def test_diff_limit_tags_and_verbosity_become_the_flags_ansible_spells():
    options = command.Options(diff=True, limit="web:!web3", tags="deploy,cache", verbosity=2)
    assert options.validated().flags == [
        "--diff",
        "--limit",
        "web:!web3",
        "--tags",
        "deploy,cache",
        "-vv",
    ]


def test_nothing_chosen_adds_nothing():
    assert command.Options().validated().flags == []
    assert not command.Options().any


def test_verbosity_stops_where_ansible_does():
    assert command.Options(verbosity=9).validated().flags == ["-vvvv"]
    assert command.Options(verbosity=-3).validated().flags == []


@pytest.mark.parametrize("limit", ["; rm -rf /", "$(id)", "web`whoami`", "a\nb"])
def test_a_limit_that_is_not_a_limit_is_refused_rather_than_quoted(limit):
    with pytest.raises(command.ValidationError):
        command.Options(limit=limit).validated()


@pytest.mark.parametrize("tags", ["deploy;id", "a|b", "$(x)"])
def test_a_tag_list_that_is_not_one_is_refused(tags):
    with pytest.raises(command.ValidationError):
        command.Options(tags=tags).validated()
