"""The lock that stops two consoles running the same thing at once.

`Runner.busy_with` saw only its own process, so two windows on one machine
could both deploy the same environment. These are the cases that matters in.
"""

import json
import os

import pytest

from ordane.core import identity
from ordane.core.identity import Actor
from ordane.record import lock as lock_module

# The real hostname, because a lock from another machine is deliberately not
# cleared and these cases are about this one.
HERE = identity.who().host
ME = Actor(user="ada", uid=1000, host=HERE)
SOMEBODY_ELSE = Actor(user="sam", uid=1001, host=HERE)

PLANE = "you/control-plane"


def a_lock(tmp_path, scope=lock_module.BY_TARGET):
    return lock_module.Locks(tmp_path, scope)


def test_nothing_holds_a_lock_that_has_never_been_taken(tmp_path):
    assert a_lock(tmp_path).held_by(PLANE, "production", "deploy") is None


def test_taking_it_makes_it_held(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    held = locks.held_by(PLANE, "production", "deploy")
    assert held is not None
    assert f"ada@{HERE}" in held.describe()


def test_the_same_thing_twice_is_refused_and_says_who_has_it(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="09:00")
    with pytest.raises(lock_module.Locked) as refused:
        locks.take(
            plane=PLANE,
            environment="production",
            target="deploy",
            actor=SOMEBODY_ELSE,
            started="09:01",
        )
    assert f"ada@{HERE}" in str(refused.value)
    assert "deploy on production" in str(refused.value)


def test_a_different_runbook_against_the_same_environment_is_allowed(tmp_path):
    """The ruling: different runbooks may run together, the same one may not."""
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    locks.take(plane=PLANE, environment="production", target="ping", actor=ME, started="now")


def test_the_same_runbook_against_a_different_environment_is_allowed(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    locks.take(plane=PLANE, environment="staging", target="deploy", actor=ME, started="now")


def test_the_same_name_in_a_different_control_plane_is_a_different_lock(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    locks.take(
        plane="other/plane", environment="production", target="deploy", actor=ME, started="x"
    )


def test_a_control_plane_may_lock_the_whole_environment_instead(tmp_path):
    locks = a_lock(tmp_path, scope=lock_module.BY_ENVIRONMENT)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    with pytest.raises(lock_module.Locked):
        locks.take(plane=PLANE, environment="production", target="ping", actor=ME, started="now")


def test_releasing_it_lets_the_next_one_through(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    locks.release(PLANE, "production", "deploy")
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")


def test_a_lock_whose_process_is_gone_is_cleared_rather_than_held_forever(tmp_path):
    locks = a_lock(tmp_path)
    path = locks.path(PLANE, "production", "deploy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "actor": f"ada@{HERE}",
                "host": HERE,
                "target": "deploy",
                "environment": "production",
                "started": "yesterday",
                "pid": 999_999_999,
            }
        ),
        encoding="utf-8",
    )
    assert locks.held_by(PLANE, "production", "deploy") is None


def test_a_lock_from_another_machine_stands_because_its_pid_means_nothing_here(tmp_path):
    """Clearing a lock that is not stale is a second deploy, so it is not cleared."""
    locks = a_lock(tmp_path)
    path = locks.path(PLANE, "production", "deploy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "actor": "sam@buildbox",
                "host": "buildbox",
                "target": "deploy",
                "environment": "production",
                "started": "09:00",
                "pid": 999_999_999,
            }
        ),
        encoding="utf-8",
    )
    held = locks.held_by(PLANE, "production", "deploy")
    assert held is not None
    assert "on buildbox" in held.describe()


def test_a_malformed_lock_file_is_treated_as_no_lock(tmp_path):
    locks = a_lock(tmp_path)
    path = locks.path(PLANE, "production", "deploy")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")
    assert locks.held_by(PLANE, "production", "deploy") is None


def test_a_name_with_a_slash_in_it_does_not_become_a_directory(tmp_path):
    locks = a_lock(tmp_path)
    path = locks.path("owner/repo", "prod/uction", "deploy")
    assert path.parent == locks.root
    assert "/" not in path.name.replace(".json", "").replace(str(locks.root), "")


def test_it_is_this_process_that_holds_it(tmp_path):
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")
    assert locks.held_by(PLANE, "production", "deploy").pid == os.getpid()


# --- work handed to the lock, which is the point of the shape ---


def test_holding_a_lock_releases_it_when_the_block_ends(tmp_path):
    locks = a_lock(tmp_path)
    with locks.holding(
        plane=PLANE, environment="production", target="deploy", actor=ME, started="now"
    ):
        assert locks.held_by(PLANE, "production", "deploy") is not None
    assert locks.held_by(PLANE, "production", "deploy") is None


def test_and_releases_it_when_the_block_raises(tmp_path):
    """The whole reason work is handed to the lock rather than the other way."""
    locks = a_lock(tmp_path)
    with pytest.raises(ZeroDivisionError):
        with locks.holding(
            plane=PLANE, environment="production", target="deploy", actor=ME, started="now"
        ):
            raise ZeroDivisionError
    assert locks.held_by(PLANE, "production", "deploy") is None


def test_a_release_that_cannot_happen_is_reported_rather_than_raised(tmp_path, monkeypatch):
    """The end of a failed run must not become a second failure."""
    locks = a_lock(tmp_path)
    locks.take(plane=PLANE, environment="production", target="deploy", actor=ME, started="now")

    def refuse(*_args, **_kwargs):
        raise PermissionError("read-only")

    monkeypatch.setattr(lock_module.Path, "unlink", refuse)
    assert locks.release(PLANE, "production", "deploy") is False


def test_a_run_that_fails_while_finishing_still_drops_its_lock(tmp_path):
    """`_finish` does several things that can fail; the release is in a finally."""
    from ordane.record.redact import Redactor
    from ordane.record.runner import ActiveRun
    from ordane.record.store import Run, RunStore

    released: list[bool] = []
    store = RunStore(tmp_path / "state")
    store.prepare()
    run = Run(
        id="x",
        kind="target",
        name="deploy",
        environment="production",
        params={},
        argv=["true"],
        command="true",
        actor="tester",
        started="2026-09-05T10:00:00Z",
    )
    active = ActiveRun(run, store, Redactor(None), None, on_finish=lambda: released.append(True))

    def explode(_captured):
        raise RuntimeError("the recap would not parse")

    import ordane.record.runner as runner_module

    original = runner_module.parse_summary
    runner_module.parse_summary = explode
    try:
        with pytest.raises(RuntimeError):
            active._finish(0.0)
    finally:
        runner_module.parse_summary = original

    assert released == [True], "the lock outlived a run that failed while finishing"


# --- anybody at all, which is what a ref switch has to ask ---


def test_a_quiet_control_plane_has_nobody_holding_it(tmp_path):
    assert lock_module.Locks(tmp_path).anyone_holding("a/plane") is None


def test_a_run_on_any_environment_is_somebody_holding_it(tmp_path):
    locks = lock_module.Locks(tmp_path)
    locks.take(
        plane="a/plane",
        environment="staging",
        target="deploy",
        actor=ME,
        started="2026-09-05T10:00:00Z",
    )
    holder = locks.anyone_holding("a/plane")
    assert holder is not None
    assert holder.environment == "staging"


def test_another_control_plane_is_not_this_one(tmp_path):
    locks = lock_module.Locks(tmp_path)
    locks.take(
        plane="other/plane",
        environment="staging",
        target="deploy",
        actor=ME,
        started="2026-09-05T10:00:00Z",
    )
    assert locks.anyone_holding("a/plane") is None


def test_a_dead_holder_is_cleared_rather_than_believed(tmp_path):
    locks = lock_module.Locks(tmp_path)
    path = locks.take(
        plane="a/plane",
        environment="staging",
        target="deploy",
        actor=ME,
        started="2026-09-05T10:00:00Z",
    )
    record = json.loads(path.read_text(encoding="utf-8"))
    record["pid"] = 2**22
    path.write_text(json.dumps(record), encoding="utf-8")
    assert locks.anyone_holding("a/plane") is None
    assert not path.exists()
