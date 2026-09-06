"""Asking hosts a question, and the instructions this deliberately cannot give."""

import pytest

from ordane.core import adhoc
from ordane.core.command import ValidationError


def test_the_question_becomes_the_command_ansible_would_be_given():
    built = adhoc.probe(inventory="inventory/staging", group="web", module="ping")
    assert built.argv == ["ansible", "web", "-i", "inventory/staging", "-m", "ping"]


@pytest.mark.parametrize("module", ["command", "shell", "raw", "script", "copy", "file"])
def test_nothing_that_can_change_a_host_is_askable(module):
    """The catalogue is the safety boundary; an ad hoc command is a hole in it."""
    with pytest.raises(ValidationError):
        adhoc.probe(inventory="inventory/staging", group="web", module=module)


@pytest.mark.parametrize("group", ["web; rm -rf /", "$(id)", "", "-web", "a b"])
def test_a_group_that_is_not_a_group_is_refused_rather_than_quoted(group):
    with pytest.raises(ValidationError):
        adhoc.probe(inventory="inventory/staging", group=group, module="ping")


def test_an_environment_with_no_inventory_cannot_be_asked():
    with pytest.raises(ValidationError):
        adhoc.probe(inventory="", group="web", module="ping")


def test_a_selector_ansible_understands_is_allowed_through():
    for group in ("web", "web:!web3", "apps,cron", "builder"):
        assert adhoc.probe(inventory="inventory/staging", group=group, module="ping")


def test_every_question_offered_is_one_the_builder_accepts():
    for one in adhoc.QUESTIONS:
        assert adhoc.probe(inventory="i", group="all", module=one.module)
        assert adhoc.question(one.module) is one
