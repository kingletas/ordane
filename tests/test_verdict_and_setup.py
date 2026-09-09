"""The one sentence at the top of Overview, and the seven steps behind it.

The rule under test throughout is the one the design calls the most important
in the document: **unconfigured is blue, never amber**. A repository that has
not finished being set up must never reach `degraded` or `failed`, or there is
nothing left to escalate to when something actually breaks.
"""

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ordane.core.catalog import Catalog, Discovery, Environment, Target
from ordane.core.config import Config
from ordane.insight import health as health_module
from ordane.insight import setup as sequence
from ordane.insight import verdict as verdict_module
from ordane.insight.metrics import Measure, Slo, Snapshot
from ordane.record.store import Run
from ordane.record.summary import HostResult, Summary

HISTORY = "docs/dora/history.csv"


def a_catalog(*, environments, targets=("deploy",)) -> Catalog:
    return Catalog(
        targets=[Target(name=name, description=name) for name in targets],
        environments=list(environments),
        playbooks=[],
        shortcuts=[],
        discovery=Discovery(targets="make-help-block", environments="make-help"),
    )


def a_snapshot(*, measured=2, slos=()) -> Snapshot:
    keys = ("cadence", "lead_time", "failure_rate", "recovery")
    return Snapshot(
        measures=[
            Measure(
                key,
                key,
                value="1" if index < measured else "",
                blocked="" if index < measured else "no source",
            )
            for index, key in enumerate(keys)
        ],
        slos=list(slos),
    )


def a_run(**kwargs) -> Run:
    base = dict(
        id="r1",
        kind="target",
        name="deploy",
        environment="staging",
        params={},
        argv=["make", "deploy"],
        command="make deploy",
        actor="ada",
        started=(datetime.now(UTC) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ"),
        state="succeeded",
        exit_code=0,
        summary=Summary(hosts=[HostResult(host="web-01", ok=3)], has_recap=True).as_record(),
    )
    base.update(kwargs)
    return Run(**base)


def judge(*, catalog, config=None, snapshot=None, runs=(), repo: Path, error=""):
    config = config or Config(allow_environments=["staging"])
    snapshot = snapshot or a_snapshot()
    runs = list(runs)
    steps = sequence.assess(
        catalog=catalog,
        config=config,
        snapshot=snapshot,
        runs=runs,
        repo=repo,
        history_path=repo / HISTORY,
    )
    health = (
        health_module.assess(catalog=catalog, config=config, snapshot=snapshot, runs=runs)
        if catalog is not None
        else health_module.Health()
    )
    return verdict_module.decide(
        catalog=catalog, health=health, setup=steps, runs=runs, error=error
    ), steps


# --- the verdict -----------------------------------------------------------


def test_a_ready_repository_says_where_it_is_safe_to_deploy(tmp_path):
    catalog = a_catalog(
        environments=[
            Environment(name="staging", usable=True),
            Environment(name="docker", usable=True),
        ]
    )
    found, _ = judge(
        catalog=catalog,
        config=Config(allow_environments=["staging", "docker"]),
        repo=tmp_path,
    )
    assert found.state == verdict_module.READY
    assert found.headline.startswith("Ready to deploy to docker and staging")


def test_a_repository_that_has_not_been_set_up_is_waiting_and_never_amber(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True, allowed=False)])
    found, _ = judge(catalog=catalog, config=Config(allow_environments=[]), repo=tmp_path)
    assert found.state == verdict_module.WAITING
    assert found.state not in (verdict_module.DEGRADED, verdict_module.FAILED)
    assert "read-only" in found.note


def test_an_environment_with_no_inventory_does_not_make_the_verdict_a_fault(tmp_path):
    catalog = a_catalog(
        environments=[
            Environment(name="staging", usable=True),
            Environment(name="performance", usable=False, reason="no inventory"),
        ]
    )
    found, _ = judge(catalog=catalog, repo=tmp_path)
    assert found.state == verdict_module.READY
    assert "performance has no inventory" in found.note


def test_a_failed_run_is_the_verdict_and_it_says_to_look_first(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    found, _ = judge(
        catalog=catalog,
        runs=[a_run(state="failed", exit_code=2)],
        repo=tmp_path,
    )
    assert found.state == verdict_module.FAILED
    assert "Look before deploying" in found.headline


def test_a_missed_objective_is_degraded_rather_than_failed(tmp_path):
    """It ran and the result is not what the repository says. Nothing broke."""
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    slo = Slo(label="Cutover succeeds", target="95%", window="90d", value="90%", attained=90.0)
    found, _ = judge(catalog=catalog, snapshot=a_snapshot(slos=[slo]), repo=tmp_path)
    assert found.state == verdict_module.DEGRADED
    # It still answers the question the page is opened with.
    assert "Ready to deploy" in found.headline


def test_a_repository_that_cannot_be_read_says_so_and_offers_the_check(tmp_path):
    found, _ = judge(catalog=None, repo=tmp_path, error="`make help` exited 2")
    assert found.state == verdict_module.FAILED
    assert found.remedy == "check"
    assert "make help" in found.note


# --- the seven steps -------------------------------------------------------


def test_there_are_seven_steps_and_each_one_says_what_it_turns_on(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    _, steps = judge(catalog=catalog, repo=tmp_path)
    assert steps.total == 7
    for step in steps.steps:
        assert step.title
        assert step.note
        assert step.unlocks


def test_the_next_step_is_the_first_one_not_done(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    _, steps = judge(catalog=catalog, config=Config(allow_environments=[]), repo=tmp_path)
    assert steps.next_step.key == "config"


def test_every_step_that_is_not_done_carries_a_button_that_goes_somewhere(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    _, steps = judge(catalog=catalog, config=Config(allow_environments=[]), repo=tmp_path)
    for step in steps.steps:
        if not step.done:
            assert step.button, f"{step.key} has nothing to press"


def test_the_card_leads_with_what_can_be_measured_not_with_what_is_missing(tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    _, steps = judge(catalog=catalog, repo=tmp_path)
    assert steps.headline(a_snapshot()) == "Ordane can measure 2 of the 4 delivery signals"
    assert steps.headline(a_snapshot(measured=4)) == "Ordane is measuring every delivery signal"


def test_no_step_ever_says_the_words_setup_needed(tmp_path):
    """The words the whole redesign exists to remove."""
    catalog = a_catalog(environments=[Environment(name="p", usable=False, reason="no inventory")])
    _, steps = judge(catalog=catalog, config=Config(allow_environments=[]), repo=tmp_path)
    for step in steps.steps:
        assert "setup needed" not in f"{step.title} {step.note} {step.unlocks}".lower()


@pytest.mark.parametrize(
    "key", ["repository", "config", "allow", "reach", "deploy", "history", "objectives"]
)
def test_each_step_is_present_by_the_name_the_window_looks_it_up_by(key, tmp_path):
    catalog = a_catalog(environments=[Environment(name="staging", usable=True)])
    _, steps = judge(catalog=catalog, repo=tmp_path)
    assert any(step.key == key for step in steps.steps)
