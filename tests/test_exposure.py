"""What makes a run dangerous is where it is aimed, not what it is called.

`ping` against docker is a keystroke. The same `ping` against production is a
keystroke against the thing customers are using, and nothing in a Makefile ever
says so. The name of the environment is the one piece of evidence there is.
"""

from __future__ import annotations

import pytest

from ordane.core import exposure

LIVE = ["production", "prod", "prd", "live", "shop-prod-web", "production-eu", "PROD"]
SAFE = ["staging", "stage", "stg", "newstage", "dev", "newdev", "development", "docker", "local"]
NOBODY_KNOWS = ["performance", "uat", "preview", "blue", "", "customer-acceptance"]


@pytest.mark.parametrize("name", LIVE)
def test_a_production_name_reads_as_production(name):
    assert exposure.reading(name) == exposure.PRODUCTION


@pytest.mark.parametrize("name", SAFE)
def test_the_four_safe_families_read_as_safe(name):
    assert exposure.reading(name) == exposure.SAFE


@pytest.mark.parametrize("name", NOBODY_KNOWS)
def test_anything_else_reads_as_unknown(name):
    """Not safe. Unknown, and said out loud."""
    assert exposure.reading(name) == exposure.UNKNOWN


def test_a_name_carrying_both_reads_as_production():
    """`dev-mirror-of-prod` reaches production hosts, whatever it is called."""
    assert exposure.reading("dev-mirror-of-prod") == exposure.PRODUCTION


def test_production_makes_a_harmless_action_dangerous():
    """This is the whole rule: `ping` is rated `low` and still gets the warning."""
    assert exposure.level_for("production", "low") == "high"


def test_an_unknown_environment_is_warned_about_rather_than_waved_through():
    assert exposure.level_for("performance", "low") == "medium"


def test_a_safe_environment_leaves_the_action_as_it_was():
    assert exposure.level_for("docker", "low") == "low"


def test_a_dangerous_action_stays_dangerous_on_a_safe_environment():
    """The environment raises the floor; it never lowers a rating."""
    assert exposure.level_for("docker", "high") == "high"
    assert exposure.level_for("newstage", "medium") == "medium"


def test_the_worst_of_two_wins_whichever_way_round():
    assert exposure.worst("low", "high") == "high"
    assert exposure.worst("high", "low") == "high"
    assert exposure.worst("medium", "low") == "medium"
    assert exposure.worst() == "low"


def test_a_rating_nobody_recognises_is_ignored_rather_than_trusted():
    assert exposure.worst("catastrophic", "low") == "low"


def test_production_says_who_is_affected():
    said = exposure.caution("production")
    assert "Customers are on production" in said


def test_an_unknown_environment_names_itself_in_its_warning():
    assert "“performance”" in exposure.caution("performance")


def test_a_safe_environment_has_nothing_to_say():
    assert exposure.caution("docker") == ""
    assert exposure.label("docker") == ""


def test_the_chip_words():
    assert exposure.label("production") == "Production"
    assert exposure.label("performance") == "Could be dangerous"
