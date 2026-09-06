import json

from ordane.record import dora
from ordane.record.store import Run


def a_run(**kwargs):
    base = dict(
        id="20260902T000000Z-aaa",
        kind="target",
        name="docker-deploy",
        environment="docker",
        params={},
        argv=[],
        command="make docker-deploy",
        actor="tester",
        started="2026-09-02T00:00:00Z",
    )
    return Run(**(base | kwargs))


def read(path):
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_a_run_that_is_not_a_deployment_writes_nothing(tmp_path):
    path = tmp_path / "events.jsonl"
    result = dora.emit_start(a_run(), path)
    assert not result.written
    assert not path.exists()


def test_a_deploy_writes_a_started_event(tmp_path):
    path = tmp_path / "events.jsonl"
    result = dora.emit_start(a_run(labels={"deploy": "true"}), path)
    assert result.written
    assert read(path)[0]["event"] == "build.started"


def test_a_cutover_is_labelled_as_one(tmp_path):
    path = tmp_path / "events.jsonl"
    dora.emit_start(a_run(labels={"cutover": "true"}), path)
    assert read(path)[0]["event"] == "cutover.started"


def test_a_failed_deploy_writes_a_failed_event(tmp_path):
    path = tmp_path / "events.jsonl"
    run = a_run(labels={"deploy": "true"}, state="failed", exit_code=2, duration_s=4.0)
    result = dora.emit_finish(run, path)
    assert result.written
    record = read(path)[0]
    assert record["event"] == "build.failed"
    assert record["exit_code"] == 2
    assert record["duration_s"] == 4.0


def test_a_successful_deploy_writes_a_succeeded_event(tmp_path):
    path = tmp_path / "events.jsonl"
    dora.emit_finish(a_run(labels={"deploy": "true"}, exit_code=0), path)
    assert read(path)[0]["event"] == "build.succeeded"


def test_the_recap_is_carried_into_the_finish_event(tmp_path):
    from ordane.record.summary import parse

    recap = (
        "PLAY RECAP ***\n"
        "web1  : ok=4    changed=2    unreachable=0    failed=0\n"
        "web2  : ok=1    changed=0    unreachable=0    failed=1\n"
    )
    run = a_run(labels={"deploy": "true"}, exit_code=2, summary=parse(recap).as_record())
    path = tmp_path / "events.jsonl"
    dora.emit_finish(run, path)
    record = read(path)[0]
    assert record["hosts"] == 2
    assert record["changed"] == 2
    assert record["failed"] == 1


def test_the_run_id_and_source_are_recorded_so_the_event_can_be_traced_back(tmp_path):
    path = tmp_path / "events.jsonl"
    dora.emit_start(a_run(labels={"deploy": "true"}), path)
    record = read(path)[0]
    assert record["source"] == "ordane"
    assert record["run_id"] == "20260902T000000Z-aaa"


def test_an_unwritable_log_is_reported_rather_than_raised(tmp_path):
    blocker = tmp_path / "blocked"
    blocker.write_text("i am a file, not a directory")
    result = dora.emit_start(a_run(labels={"deploy": "true"}), blocker / "events.jsonl")
    assert not result.written
    assert result.error


def test_both_ends_of_a_run_land_in_order(tmp_path):
    path = tmp_path / "events.jsonl"
    run = a_run(labels={"cutover": "true"})
    dora.emit_start(run, path)
    run.exit_code = 0
    run.finished = "2026-09-02T00:01:00Z"
    dora.emit_finish(run, path)
    assert [r["event"] for r in read(path)] == ["cutover.started", "cutover.succeeded"]
