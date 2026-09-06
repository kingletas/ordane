from ordane.insight import runs as runs_module
from ordane.record.store import Run


def a_run(state="succeeded", cutover=False):
    return Run(
        id="x",
        kind="target",
        name="deploy",
        environment="docker",
        params={},
        command="make deploy",
        argv=["make", "deploy"],
        started="2026-09-05T10:00:00Z",
        actor="test",
        repo="/nowhere",
        state=state,
        labels={"cutover": "true"} if cutover else {},
    )


def test_all_keeps_everything():
    everything = [a_run(), a_run("failed"), a_run("running")]
    assert len(runs_module.apply(everything, runs_module.ALL)) == 3


def test_failed_covers_a_run_that_never_started_as_well_as_one_that_broke():
    assert len(runs_module.apply([a_run("failed"), a_run("error"), a_run()], "failed")) == 2


def test_running_is_not_a_kind_of_failure():
    assert runs_module.apply([a_run("running")], "failed") == []


def test_customer_visible_means_a_cutover_not_a_danger_level():
    kept = runs_module.apply([a_run(cutover=True), a_run()], runs_module.CUSTOMER)
    assert len(kept) == 1


def test_every_filter_says_what_an_empty_result_means():
    for one in runs_module.FILTERS:
        assert one.empty and one.empty.endswith(".")


def test_an_unknown_key_falls_back_to_everything():
    assert runs_module.by_key("nonsense").key == runs_module.ALL
