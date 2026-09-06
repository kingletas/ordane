import json

from ordane.record.store import Run, RunStore, new_id


def a_run(**kwargs):
    base = dict(
        id=new_id(),
        kind="target",
        name="ping",
        environment="docker",
        params={},
        argv=["make", "ping"],
        command="make ping",
        actor="tester",
        started="2026-09-01T00:00:00Z",
    )
    return Run(**(base | kwargs))


def test_a_run_round_trips_through_the_index(tmp_path):
    store = RunStore(tmp_path)
    run = a_run()
    store.append(run)
    assert [r.id for r in store.all()] == [run.id]


def test_a_later_record_supersedes_the_earlier_one(tmp_path):
    store = RunStore(tmp_path)
    run = a_run()
    store.append(run)
    run.state = "succeeded"
    run.exit_code = 0
    store.append(run)
    stored = store.all()
    assert len(stored) == 1
    assert stored[0].state == "succeeded"


def test_a_malformed_line_is_skipped_rather_than_fatal(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run())
    store.index.write_text(store.index.read_text() + "not json\n")
    assert len(store.all()) == 1


def test_runs_come_back_newest_first(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run(started="2026-09-01T00:00:00Z", name="first"))
    store.append(a_run(started="2026-09-02T00:00:00Z", name="second"))
    assert [r.name for r in store.all()] == ["second", "first"]


def test_ids_are_unique(tmp_path):
    assert len({new_id() for _ in range(200)}) == 200


def test_runs_are_scoped_to_their_repository(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run(repo="/repo/a", name="a-run"))
    store.append(a_run(repo="/repo/b", name="b-run"))
    assert [r.name for r in store.all("/repo/a")] == ["a-run"]
    assert len(store.all()) == 2


def test_a_run_with_no_repository_is_never_claimed_by_one(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run(name="orphan"))
    assert store.all("/repo/a") == []
    assert [r.name for r in store.all()] == ["orphan"]


def test_the_control_planes_in_the_history_are_listed(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run(repo="/repo/b"))
    store.append(a_run(repo="/repo/a"))
    store.append(a_run())
    assert store.planes() == ["/repo/a", "/repo/b"]


# --- a history that has to mean something on a second machine ---


def test_runs_are_scoped_by_the_control_plane_name(tmp_path):
    store = RunStore(tmp_path)
    store.prepare()
    store.append(a_run(id="1", repo="/anywhere", plane="you/control-plane"))
    store.append(a_run(id="2", repo="/anywhere", plane="kingletas/other"))
    kept = store.all(plane="you/control-plane")
    assert [r.id for r in kept] == ["1"]


def test_a_record_written_before_planes_had_names_is_still_found_by_its_path(tmp_path):
    """Nothing is dropped from a history written by an earlier version."""
    store = RunStore(tmp_path)
    store.prepare()
    store.append(a_run(id="old", repo="/home/you/plane"))
    assert [r.id for r in store.all("/home/you/plane", plane="anything")] == ["old"]


def test_an_old_record_does_not_leak_into_another_plane(tmp_path):
    store = RunStore(tmp_path)
    store.prepare()
    store.append(a_run(id="old", repo="/home/you/plane"))
    assert store.all("/home/you/elsewhere", plane="anything") == []


def test_a_run_records_where_and_which_installation_minted_its_id(tmp_path):
    run = a_run(id="1", host="thinkpad", installation="ab12cd34")
    store = RunStore(tmp_path)
    store.prepare()
    store.append(run)
    read = store.get("1")
    assert (read.host, read.installation) == ("thinkpad", "ab12cd34")


# --- the builder, which the environment name does not answer ---


def test_a_run_records_the_host_it_was_built_on(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run(builder="stage-builder"))
    assert store.all()[0].builder == "stage-builder"


def test_a_record_written_before_the_builder_existed_still_reads(tmp_path):
    """Append-only means yesterday's lines have to keep parsing."""
    store = RunStore(tmp_path)
    store.append(a_run())
    line = json.loads((tmp_path / "runs.jsonl").read_text(encoding="utf-8").splitlines()[0])
    del line["builder"]
    (tmp_path / "runs.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
    read = store.all()
    assert len(read) == 1
    assert read[0].builder == ""


# --- three runs in the same second, which a runbook now makes ordinary ---


def test_runs_that_share_a_second_come_back_in_the_order_they_happened(tmp_path):
    """`started` is one-second resolution, and a sequence runs three inside one."""
    store = RunStore(tmp_path)
    for name in ("precheck", "deploy", "postcheck"):
        store.append(
            a_run(id=f"20260905T120000Z-{name[:3]}", name=name, started="2026-09-05T12:00:00Z")
        )
    assert [r.name for r in store.all()] == ["postcheck", "deploy", "precheck"]


def test_a_later_record_updates_a_run_rather_than_moving_it(tmp_path):
    store = RunStore(tmp_path)
    first = a_run(id="20260905T120000Z-aaa", name="one", started="2026-09-05T12:00:00Z")
    second = a_run(id="20260905T120000Z-bbb", name="two", started="2026-09-05T12:00:00Z")
    store.append(first)
    store.append(second)
    first.state = "succeeded"
    store.append(first)
    assert [r.name for r in store.all()] == ["two", "one"]


# --- the steps of one launch ---


def test_every_step_of_a_launch_comes_back_oldest_first(tmp_path):
    store = RunStore(tmp_path)
    for index, name in enumerate(("checks", "check", "deploy", "verify")):
        store.append(
            a_run(
                id=f"20260906T12000{index}Z-x",
                name=name,
                started=f"2026-09-06T12:00:0{index}Z",
                sequence="launch-1",
            )
        )
    store.append(a_run(id="other", name="ping", started="2026-09-06T12:00:09Z"))
    assert [r.name for r in store.steps_of("launch-1")] == ["checks", "check", "deploy", "verify"]


def test_a_run_that_stood_alone_is_a_step_of_nothing(tmp_path):
    store = RunStore(tmp_path)
    store.append(a_run())
    assert store.steps_of("") == []
    assert store.steps_of("no-such-launch") == []


def test_a_launch_whose_steps_share_a_second_keeps_the_order_they_ran(tmp_path):
    """The operation is re-appended when it finishes; that must not move it."""
    store = RunStore(tmp_path)
    same = "2026-09-06T04:22:08Z"
    target = a_run(id="t1", kind="target", name="deploy", started=same, sequence="s")
    store.append(target)
    store.append(a_run(id="p1", kind="postcheck", name="verify", started=same, sequence="s"))
    target.state = "succeeded"
    store.append(target)
    assert [r.kind for r in store.steps_of("s")] == ["target", "postcheck"]
