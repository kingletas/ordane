"""The run that stops and waits, which could not be run from here at all.

A playbook needing `--ask-vault-pass` sat on a prompt nothing could see and
nothing could answer. The runner already allocates a pty, which is exactly what
a prompt needs, so this is about noticing one without inventing one.
"""

from ordane.record import runner
from ordane.record.redact import Redactor
from ordane.record.store import Run, RunStore, new_id


def _a_run() -> Run:
    return Run(
        id=new_id(),
        kind="target",
        name="deploy",
        environment="staging",
        params={},
        argv=["make", "deploy"],
        command="make deploy",
        actor="tester",
        started="2026-09-05T00:00:00Z",
    )


# --- a run that stops and waits for a password ---


def test_ansible_s_own_prompts_are_recognised():
    for text, expected in (
        ("Vault password: ", "Vault password:"),
        ("Vault password (prod): ", "Vault password (prod):"),
        ("BECOME password: ", "BECOME password:"),
        ("SUDO password[defaults to SSH password]: ", "SUDO password[defaults to SSH password]:"),
    ):
        assert runner._prompt_in(text) == expected


def test_a_playbook_printing_the_word_password_is_not_a_prompt():
    """A bare `password:` in output would put the interface into a state nobody asked for."""
    for text in (
        "ok: [web1] => password: hunter2",
        "changed: [web1]",
        "TASK [Set the password] ****",
        "",
        "   ",
    ):
        assert runner._prompt_in(text) == ""


def test_nothing_can_be_answered_when_nothing_is_asking(tmp_path):
    active = runner.ActiveRun(_a_run(), RunStore(tmp_path), Redactor())
    assert not active.asking
    assert active.answer("hunter2000") is False


# --- what `finished` promises to anything watching a run ---


def test_a_finished_run_can_be_read_back_the_moment_it_says_it_is_finished(tmp_path):
    """`finished` used to flip while the record was still being written.

    The state was set in the middle of concluding a run and the store was
    appended to a few lines later, so a caller that polled `finished` and then
    read the record saw the run as it was before it ended: no exit code, no
    output. It made the suite fail at random, which is the kind of gate people
    learn to re-run rather than read.
    """
    import time

    from ordane.core.command import Command
    from ordane.record.runner import Runner

    repo = tmp_path / "plane"
    repo.mkdir()
    store = RunStore(tmp_path / "state")
    store.prepare()
    driver = Runner(store, repo, tmp_path / "state" / "events.jsonl")

    for attempt in range(25):
        active = driver.start(
            kind="target",
            name="show",
            environment="local",
            params={},
            command=Command.build(["true"]),
        )
        deadline = time.monotonic() + 20
        while not active.finished and time.monotonic() < deadline:
            time.sleep(0.005)
        assert active.finished, f"attempt {attempt} never ended"

        record = store.get(active.id)
        assert record is not None, f"attempt {attempt}: no record at all"
        assert record.state != "running", (
            f"attempt {attempt}: finished, and the record still says running"
        )
        assert record.exit_code == 0, f"attempt {attempt}: exit code {record.exit_code!r}"


def test_a_cancel_does_not_wait_on_the_child_s_good_manners(tmp_path, monkeypatch):
    """A process that ignores the signal used to hold everything waiting on the run.

    The kill was reached only from `_conclude`, which runs once the output ends,
    so a child that kept the terminal open kept `finished` false and left the
    environment locked for as long as it chose.
    """
    import time

    from ordane.core.command import Command
    from ordane.record.runner import Runner

    monkeypatch.setattr(runner, "TERM_GRACE_SECONDS", 1)

    repo = tmp_path / "plane"
    repo.mkdir()
    store = RunStore(tmp_path / "state")
    store.prepare()
    driver = Runner(store, repo, tmp_path / "state" / "events.jsonl")

    # Ignores the interrupt and holds the terminal open, which is what an
    # Ansible run trapping SIGINT to finish its handlers looks like. It says so
    # first: signalled before the handler is installed, it dies of the signal
    # and proves nothing.
    stubborn = (
        "import signal, sys, time; signal.signal(signal.SIGINT, signal.SIG_IGN); "
        "print('holding', flush=True); time.sleep(120)"
    )
    active = driver.start(
        kind="target",
        name="stubborn",
        environment="local",
        params={},
        command=Command.build(["python3", "-c", stubborn]),
    )
    deadline = time.monotonic() + 30
    while "holding" not in active.buffered() and time.monotonic() < deadline:
        time.sleep(0.01)
    assert "holding" in active.buffered(), "the run never reached the point of ignoring signals"

    assert active.cancel(), "the run was not there to cancel"
    deadline = time.monotonic() + 30
    while not active.finished and time.monotonic() < deadline:
        time.sleep(0.01)

    assert active.finished, "a cancelled run that ignored the signal never ended"
    assert driver.busy_with("local") is None, "the environment is still locked"
