import json
from datetime import UTC, datetime, timedelta

from ordane.insight import metrics
from ordane.insight.metrics import MAX_MONTHS, Release, read_events, read_history, snapshot
from ordane.record.store import Run

CSV = (
    "date,env_name,release,version,platform,platform_upgrade,outcome,is_rollback,"
    "commit_count,lead_time_days,duration_s,window_s,setup_upgrade_ran,actor,source,theme\n"
    "2020-01-29,production,Awolnation,,2.3.2,True,success,False,2755,,,,,,backfill,Foundation\n"
    "2026-08-10,production,Zebra,,2.4.7,False,success,False,49,8.3,,,,,backfill,Feature\n"
    "2026-07-01,production,Yak,,2.4.7,False,success,False,60,12.0,,,,,backfill,Feature\n"
)


def a_run(**kwargs):
    base = dict(
        id="x",
        kind="target",
        name="deploy",
        environment="docker",
        params={},
        argv=[],
        command="",
        actor="t",
        started="2026-09-01T00:00:00Z",
    )
    return Run(**(base | kwargs))


def test_history_is_parsed_with_missing_lead_times_as_none(tmp_path):
    path = tmp_path / "history.csv"
    path.write_text(CSV)
    releases = read_history(path)
    assert len(releases) == 3
    assert releases[0].lead_time_days is None
    assert releases[1].lead_time_days == 8.3


def test_a_missing_history_file_is_not_fatal(tmp_path):
    assert read_history(tmp_path / "absent.csv") == []


def test_a_malformed_event_line_is_skipped(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text(json.dumps({"event": "build.succeeded"}) + "\nnot json\n\n")
    assert len(read_events(path)) == 1


def test_cadence_and_lead_time_report_from_the_history(tmp_path):
    history = tmp_path / "history.csv"
    history.write_text(CSV)
    snap = snapshot(
        history_path=history, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    )
    assert snap.measure("cadence").has_data
    assert snap.measure("lead_time").has_data


def test_a_measure_with_no_data_says_so_rather_than_reporting_zero(tmp_path):
    snap = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=[],
        slo_specs=[],
    )
    cadence = snap.measure("cadence")
    assert not cadence.has_data
    assert cadence.value == ""
    assert cadence.blocked


def test_an_slo_with_no_cutover_is_blocked_not_a_hundred_percent(tmp_path):
    snap = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=[],
        slo_specs=[{"label": "Cutover succeeds", "kind": "cutover_success", "target": "95%"}],
    )
    assert not snap.slos[0].has_data
    assert snap.slos[0].blocked


def test_cutover_success_counts_only_finished_cutover_runs(tmp_path):
    runs = [
        a_run(labels={"cutover": "true"}, state="succeeded", exit_code=0),
        a_run(labels={"cutover": "true"}, state="failed", exit_code=2),
        a_run(labels={"cutover": "true"}, state="running"),
        a_run(state="succeeded", exit_code=0),
    ]
    snap = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=runs,
        slo_specs=[{"label": "Cutover succeeds", "kind": "cutover_success", "target": "95%"}],
    )
    slo = snap.slos[0]
    assert slo.value == "50%"
    assert slo.status == "breach"


def test_an_event_log_from_only_a_test_environment_is_called_out(tmp_path):
    events = tmp_path / "events.jsonl"
    events.write_text(json.dumps({"event": "build.succeeded", "env_name": "docker"}) + "\n")
    snap = snapshot(history_path=tmp_path / "none.csv", events_path=events, runs=[], slo_specs=[])
    assert any("No production cutover has been instrumented" in n for n in snap.notes)


def test_an_objective_ignores_runs_from_outside_its_environments(tmp_path):
    runs = [a_run(environment="docker", labels={"cutover": "true"}, state="succeeded", exit_code=0)]
    snap = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=runs,
        slo_specs=[
            {
                "label": "Cutover succeeds",
                "kind": "cutover_success",
                "environments": ["production"],
                "target": "95%",
            }
        ],
    )
    slo = snap.slos[0]
    assert not slo.has_data
    assert "production" in slo.blocked


def test_release_risk_ignores_runs_outside_the_metric_scope(tmp_path):
    runs = [a_run(environment="docker", labels={"deploy": "true"}, state="succeeded", exit_code=0)]
    snap = snapshot(
        history_path=tmp_path / "none.csv",
        events_path=tmp_path / "none.jsonl",
        runs=runs,
        slo_specs=[],
        scope=["production"],
    )
    risk = snap.measure("failure_rate")
    assert not risk.has_data
    assert "production" in risk.blocked


def test_the_cadence_series_counts_production_releases_by_month(tmp_path):
    history = tmp_path / "history.csv"
    history.write_text(CSV)
    snap = snapshot(
        history_path=history, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    )
    series = snap.cadence
    assert series
    assert len(series.labels) == len(series.values)
    assert series.labels[-1] == "2026-08"
    assert series.values[-1] == 1.0


def test_the_series_spans_the_data_rather_than_a_fixed_window(tmp_path):
    """An axis that starts before the first release disagrees with the basis
    line above it, and a reader has no way to tell which is the measurement."""
    history = tmp_path / "history.csv"
    history.write_text(CSV)
    snap = snapshot(
        history_path=history, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    )
    for series in (snap.cadence, snap.lead_time):
        if not series:
            continue
        assert series.labels[-1] == "2026-08"
        assert len(series.labels) <= MAX_MONTHS
        assert series.caption.endswith(f"{series.labels[0]} to {series.labels[-1]}")


def test_the_series_never_grows_past_what_a_chart_can_draw(tmp_path):
    """2020 to 2026 is 80 months, and 80 bars in 460 px is a smear."""
    history = tmp_path / "history.csv"
    history.write_text(CSV)
    series = snapshot(
        history_path=history, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    ).cadence
    assert len(series.values) == MAX_MONTHS


def test_a_month_with_no_release_is_a_zero_not_a_gap(tmp_path):
    history = tmp_path / "history.csv"
    history.write_text(CSV)
    series = snapshot(
        history_path=history, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    ).cadence
    assert 0.0 in series.values


def test_too_little_history_yields_no_series_rather_than_a_flat_line(tmp_path):
    empty = tmp_path / "empty.csv"
    empty.write_text("date,env_name,release,lead_time_days,source\n")
    series = snapshot(
        history_path=empty, events_path=tmp_path / "none.jsonl", runs=[], slo_specs=[]
    ).cadence
    assert not series


# --- the configured scope, which two measures used to ignore ---


def _release(env, day, lead=2.0):
    return Release(
        date=day,
        environment=env,
        release="r",
        outcome="success",
        lead_time_days=lead,
        source="test",
    )


def test_cadence_counts_the_environments_the_config_named():
    releases = [_release("staging", "2026-01-01"), _release("staging", "2026-03-01")]
    measure = metrics._cadence(releases, ["staging"])
    assert measure.has_data
    assert "staging releases" in measure.detail


def test_cadence_ignores_releases_outside_that_scope():
    releases = [_release("staging", "2026-01-01"), _release("staging", "2026-03-01")]
    measure = metrics._cadence(releases, ["production"])
    assert not measure.has_data
    assert "production" in measure.blocked


def test_the_default_scope_is_production_when_the_config_says_nothing():
    assert metrics._scope(None) == ["production"]
    assert metrics._scope([]) == ["production"]


def test_lead_time_is_scoped_the_same_way():
    recent = (datetime.now(UTC) - timedelta(days=10)).date().isoformat()
    releases = [_release("staging", recent, 4.0)]
    assert metrics._lead_time(releases, ["staging"]).has_data
    assert not metrics._lead_time(releases, ["production"]).has_data


# --- time to restore, which nothing computed before ---


def _deploy(environment: str, started: str, exit_code: int, state: str = "succeeded"):
    return Run(
        id=started,
        kind="target",
        name="deploy",
        environment=environment,
        params={},
        argv=[],
        command="",
        actor="tester",
        started=started,
        state=state,
        exit_code=exit_code,
        labels={"deploy": "true"},
    )


def test_recovery_is_the_gap_between_a_failed_deploy_and_the_next_that_worked():
    runs = [
        _deploy("staging", "2026-09-01T10:00:00Z", 2, state="failed"),
        _deploy("staging", "2026-09-01T12:00:00Z", 0),
    ]
    measure = metrics._recovery(runs, ["staging"])
    assert measure.has_data
    assert measure.value == "2h 00m"
    assert "1 recoveries" in measure.detail


def test_a_second_failure_before_a_fix_does_not_restart_the_clock():
    """The service broke when it first broke, not when somebody tried again."""
    runs = [
        _deploy("staging", "2026-09-01T10:00:00Z", 2, state="failed"),
        _deploy("staging", "2026-09-01T11:00:00Z", 2, state="failed"),
        _deploy("staging", "2026-09-01T13:00:00Z", 0),
    ]
    assert metrics._recoveries(runs) == [3 * 3600]


def test_a_failure_on_one_environment_is_not_restored_by_a_fix_on_another():
    runs = [
        _deploy("staging", "2026-09-01T10:00:00Z", 2, state="failed"),
        _deploy("docker", "2026-09-01T11:00:00Z", 0),
    ]
    assert metrics._recoveries(runs) == []


def test_a_history_with_no_failure_says_so_rather_than_reporting_zero():
    runs = [_deploy("staging", "2026-09-01T10:00:00Z", 0)]
    measure = metrics._recovery(runs, ["staging"])
    assert not measure.has_data
    assert "no failed deploy" in measure.blocked


def test_recovery_is_scoped_like_every_other_measure():
    runs = [
        _deploy("docker", "2026-09-01T10:00:00Z", 2, state="failed"),
        _deploy("docker", "2026-09-01T12:00:00Z", 0),
    ]
    assert not metrics._recovery(runs, ["staging"]).has_data
    assert metrics._recovery(runs, ["docker"]).has_data


def test_a_run_still_going_is_not_counted_either_way():
    runs = [
        _deploy("staging", "2026-09-01T10:00:00Z", 2, state="failed"),
        _deploy("staging", "2026-09-01T12:00:00Z", None, state="running"),
    ]
    assert not metrics._recovery(runs, ["staging"]).has_data
