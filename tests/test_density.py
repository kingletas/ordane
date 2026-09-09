"""The run-density rules: what folds, what never does, and what a row prints.

The rule that matters most is the one about what is *not* allowed to fold. A
history that quietly swallowed a failure would be worse than the log it
replaced, so each of the five exemptions is asserted separately.
"""

from datetime import UTC, datetime, timedelta

from ordane.insight import density
from ordane.record.store import Run
from ordane.record.summary import HostResult, Summary


def at(minutes_ago: int) -> str:
    when = datetime.now(UTC) - timedelta(minutes=minutes_ago)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def a_run(**kwargs) -> Run:
    base = dict(
        id=f"r{kwargs.get('minutes', 0)}",
        kind="target",
        name="ping",
        environment="docker",
        params={},
        argv=["make", "ping"],
        command="make ping",
        actor="ada",
        started=at(kwargs.pop("minutes", 10)),
        state="succeeded",
        exit_code=0,
        duration_s=3.0,
        origin=density.BY_SCHEDULE,
    )
    hosts = kwargs.pop("hosts", 2)
    changed = kwargs.pop("changed", 0)
    failed = kwargs.pop("failed", 0)
    unreachable = kwargs.pop("unreachable", 0)
    base["summary"] = Summary(
        hosts=[
            HostResult(
                host=f"web-{index + 1}",
                ok=4,
                changed=1 if index < changed else 0,
                failed=1 if (failed and index == hosts - 1) else 0,
                unreachable=1 if (unreachable and index == hosts - 1) else 0,
            )
            for index in range(hosts)
        ],
        has_recap=True,
    ).as_record()
    base.update(kwargs)
    return Run(**base)


# --- what folds, and the five things that never do -------------------------


def test_a_scheduled_pass_that_changed_nothing_folds():
    assert density.routine(a_run())


def test_a_run_somebody_launched_by_hand_keeps_its_line():
    assert not density.routine(a_run(origin=density.BY_HAND))


def test_a_run_that_changed_something_keeps_its_line():
    assert not density.routine(a_run(changed=1))


def test_a_run_that_failed_keeps_its_line():
    assert not density.routine(a_run(state="failed", exit_code=2))


def test_a_run_still_going_keeps_its_line():
    assert not density.routine(a_run(state="running", exit_code=None))


def test_a_run_whose_recap_reports_a_failed_host_keeps_its_line():
    """It finished cleanly and did not do what the repository says."""
    run = a_run(failed=1)
    assert density.outcome(run) == density.WARN
    assert not density.routine(run)


def test_a_repeat_folds_because_nobody_pressed_a_button_for_it():
    assert density.routine(a_run(origin=density.BY_REPEAT))


def test_a_step_of_a_runbook_folds():
    assert density.routine(a_run(origin=density.BY_STEP, kind="precheck"))


# --- folding, and the count staying on the page ----------------------------


def test_consecutive_routine_passes_become_one_row_that_prints_its_count():
    runs = [a_run(minutes=index, id=f"r{index}") for index in range(6)]
    rows = density.fold(runs)
    assert len(rows) == 1
    assert rows[0].kind == "rolled"
    assert rows[0].count == 6
    assert rows[0].headline == "6 passed"


def test_a_deviation_splits_the_roll_rather_than_joining_it():
    runs = [
        a_run(minutes=1, id="a"),
        a_run(minutes=2, id="b", changed=2),
        a_run(minutes=3, id="c"),
    ]
    rows = density.fold(runs)
    assert [row.kind for row in rows] == ["rolled", "run", "rolled"]


def test_a_roll_never_crosses_an_environment():
    runs = [a_run(minutes=1, id="a"), a_run(minutes=2, id="b", environment="staging")]
    rows = density.fold(runs)
    assert [row.kind for row in rows] == ["rolled", "rolled"]
    assert [row.environment for row in rows] == ["docker", "staging"]


def test_the_ceiling_cuts_deviations_and_never_the_summary():
    runs = [a_run(minutes=index, id=f"d{index}", changed=1) for index in range(9)]
    runs.append(a_run(minutes=20, id="quiet"))
    rows = density.fold(runs, ceiling=density.OVERVIEW_ROWS)
    assert sum(1 for row in rows if row.kind == "run") == density.OVERVIEW_ROWS
    assert any(row.kind == "rolled" for row in rows)
    more = [row for row in rows if row.kind == "more"]
    assert more and more[0].count == 9 - density.OVERVIEW_ROWS


# --- what a row prints, and what it leaves out -----------------------------


def test_a_row_prints_no_zero_for_an_unchanged_host_count():
    assert "0" not in density.note(a_run())


def test_a_changed_row_counts_hosts_rather_than_tasks():
    assert density.note(a_run(hosts=6, changed=4)) == "4 of 6 hosts changed"


def test_a_failed_row_names_the_host_and_what_it_said():
    run = a_run(state="failed", exit_code=2)
    run.summary["failures"] = [
        {"host": "db-01", "task": "migrate", "kind": "failed", "message": "lock timeout"}
    ]
    assert density.note(run) == "db-01: lock timeout"


def test_an_unremarkable_duration_is_not_printed():
    runs = [a_run(minutes=index, id=f"r{index}") for index in range(6)]
    medians = density._medians(runs)
    assert "took" not in density.note(runs[0], medians.get("ping"))


def test_an_unusual_duration_is_printed_because_it_is_the_news():
    runs = [a_run(minutes=index, id=f"r{index}") for index in range(6)]
    slow = a_run(minutes=7, id="slow", duration_s=90.0)
    medians = density._medians(runs)
    assert "usual" in density.note(slow, medians.get("ping"))


# --- the ribbon ------------------------------------------------------------


def test_the_ribbon_is_one_tick_per_run_with_the_routine_ones_short():
    runs = [a_run(minutes=index, id=f"r{index}") for index in range(4)]
    runs.append(a_run(minutes=5, id="moved", changed=1))
    band = density.ribbon(runs)
    assert band.total == 5
    assert sum(1 for tick in band.ticks if tick.tall) == 1
    assert "changed something" in band.sentence


def test_the_ribbon_covers_a_day_and_nothing_older():
    runs = [a_run(minutes=10, id="new"), a_run(minutes=60 * 30, id="old")]
    assert density.ribbon(runs).total == 1


def test_the_default_filter_never_hides_anything_that_matters():
    for run in (
        a_run(origin=density.BY_HAND),
        a_run(changed=1),
        a_run(state="failed", exit_code=1),
        a_run(state="running", exit_code=None),
        a_run(failed=1),
    ):
        assert density.worth_a_look(run)
