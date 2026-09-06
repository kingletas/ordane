"""A suite of checks, recorded like anything else that ran.

**Evidence nobody wrote down is a claim.** The window drew the result and the
history held nothing, so *the checks passed before this went out* was true and
unprovable an hour later.
"""

from pathlib import Path

from ordane.core import validation
from ordane.record import checks
from ordane.record.store import RunStore

SUITE = validation.read(
    {
        "image": "an/image:1",
        "checks": [{"name": "Syntax", "run": ["true"]}, {"name": "Lint", "run": ["false"]}],
    }
)


def _report(*outcomes: bool) -> validation.Report:
    return validation.Report(
        results=[
            validation.Result(check, ok=ok, output=f"{check.name} said something", seconds=0.5)
            for check, ok in zip(SUITE.checks, outcomes, strict=True)
        ]
    )


def _store(tmp_path: Path) -> RunStore:
    store = RunStore(tmp_path)
    store.prepare()
    return store


def test_a_passing_suite_is_a_succeeded_run_in_the_history(tmp_path):
    store = _store(tmp_path)
    checks.record(store, _report(True, True), suite=SUITE, plane="a/plane", repo=tmp_path)
    recorded = store.all(plane="a/plane")
    assert [(r.name, r.state, r.exit_code) for r in recorded] == [("checks", "succeeded", 0)]
    assert recorded[0].duration_s == 1.0


def test_a_failing_suite_is_a_failed_run(tmp_path):
    store = _store(tmp_path)
    checks.record(store, _report(True, False), suite=SUITE, plane="a/plane", repo=tmp_path)
    assert store.all(plane="a/plane")[0].state == "failed"


def test_it_can_never_be_counted_as_a_deploy(tmp_path):
    """A suite that carried the label would move a delivery measure on its own."""
    store = _store(tmp_path)
    written = checks.record(store, _report(True, True), suite=SUITE, plane="a/plane", repo=tmp_path)
    assert written.labels == {}
    assert written.kind == checks.CHECKS


def test_each_failing_check_is_named_rather_than_left_in_the_output(tmp_path):
    store = _store(tmp_path)
    written = checks.record(
        store, _report(False, False), suite=SUITE, plane="a/plane", repo=tmp_path
    )
    failures = written.result.failures
    assert [f.host for f in failures] == ["Syntax", "Lint"]
    assert "said something" in failures[0].message


def test_no_recap_is_claimed_because_no_play_ran(tmp_path):
    """Host counts on a thing with no hosts would be an invented measurement."""
    store = _store(tmp_path)
    written = checks.record(store, _report(True, True), suite=SUITE, plane="a/plane", repo=tmp_path)
    assert not written.result.has_recap
    assert written.result.hosts == []


def test_the_transcript_leads_with_the_summary_and_holds_every_check(tmp_path):
    store = _store(tmp_path)
    written = checks.record(
        store, _report(True, False), suite=SUITE, plane="a/plane", repo=tmp_path
    )
    text = store.output_path(written.id).read_text(encoding="utf-8")
    assert text.splitlines()[0].startswith("1 of 2 passed")
    assert "PASSED  Syntax" in text
    assert "FAILED  Lint" in text


def test_a_gating_run_says_which_environment_it_gated(tmp_path):
    store = _store(tmp_path)
    written = checks.record(
        store,
        _report(True, True),
        suite=SUITE,
        plane="a/plane",
        repo=tmp_path,
        environment="staging",
    )
    assert written.environment == "staging"


def test_a_transcript_that_cannot_be_written_does_not_lose_the_record(tmp_path):
    """The record is worth more than the transcript, and a full disk loses one."""
    store = _store(tmp_path)
    # The transcript's own path taken by a directory: the write fails, the
    # record must not.
    written_to = store.output_path("placeholder")
    written_to.parent.mkdir(parents=True, exist_ok=True)
    store.output_path = lambda _id: written_to.parent
    written = checks.record(store, _report(True, True), suite=SUITE, plane="a/plane", repo=tmp_path)
    assert store.all(plane="a/plane") and written.state == "succeeded"
