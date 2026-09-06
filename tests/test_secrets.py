"""A parameter declared `secret: true`, followed everywhere it could leak.

The flag reached one HTML input and nothing else: the value went into the
command preview, the run index and the parameters as it was typed. These are
the four places it must not appear.
"""

from ordane.core.catalog import Catalog, Environment, Target
from ordane.core.command import Command, for_target, secret_values
from ordane.core.config import Config, Param
from ordane.presentation.language import MASK

# The value a test types into a secret field. `noqa` because a scanner cannot
# tell a fixture from a leak, and this file is entirely about not leaking.
TOKEN = "hunter2-and-then-some"  # noqa: S105  # pragma: allowlist secret


def a_target(**params) -> Target:
    return Target(name="admin-user-remove", description="", params=params)


def a_catalog() -> Catalog:
    return Catalog(
        targets=[],
        environments=[Environment(name="docker", usable=True)],
        playbooks=[],
        shortcuts=[],
    )


def built(secret: bool) -> Command:
    target = a_target(
        users=Param(name="users", allow_other=True),
        token=Param(name="token", allow_other=True, secret=secret),
    )
    return for_target(
        target=target,
        environment="docker",
        params={"users": "alice", "token": TOKEN},
        config=Config(),
        catalog=a_catalog(),
    )


def test_the_value_still_reaches_the_command_that_actually_runs():
    assert any(TOKEN in part for part in built(secret=True).argv)


def test_but_not_the_one_that_is_written_down():
    command = built(secret=True)
    assert not any(TOKEN in part for part in command.safe_argv)
    assert MASK in command.safe_display


def test_nor_the_parameters_that_are_written_down():
    command = built(secret=True)
    kept = command.safe_params({"users": "alice", "token": TOKEN})
    assert kept["token"] == MASK
    assert kept["users"] == "alice"


def test_a_parameter_that_is_not_secret_is_left_alone():
    command = built(secret=False)
    assert command.redact == []
    assert command.safe_display == command.display


def test_the_value_is_handed_to_the_output_redactor():
    assert built(secret=True).redact == [TOKEN]


def test_a_value_too_short_to_mask_safely_is_not_masked():
    """Replacing every `a` in a command line destroys the record rather than
    protecting it, and a two-character secret is not one."""
    command = Command.build(["make", "x", "k=ab"], redact=["ab"])
    assert command.safe_display == command.display


def test_secret_values_are_read_from_the_target_rather_than_guessed():
    target = a_target(token=Param(name="token", secret=True), users=Param(name="users"))
    assert secret_values(target, {"token": TOKEN, "users": "alice"}) == [TOKEN]


def test_an_empty_secret_is_not_a_value_to_mask():
    target = a_target(token=Param(name="token", secret=True))
    assert secret_values(target, {"token": ""}) == []


# --- the wiring, which is where the defect actually was ---


def test_a_started_run_records_the_masked_command_and_not_the_real_one(tmp_path):
    """The masking was never wrong; nothing called it. This is that check."""
    import time

    from ordane.core.command import Command
    from ordane.record.runner import Runner
    from ordane.record.store import RunStore

    store = RunStore(tmp_path / "state")
    store.prepare()
    runner = Runner(store, tmp_path, tmp_path / "events.jsonl")
    command = Command.build(["echo", f"token={TOKEN}"], redact=[TOKEN])

    active = runner.start(
        kind="target",
        name="echo",
        environment="docker",
        params={"token": TOKEN},
        command=command,
    )
    deadline = time.monotonic() + 10
    while not active.finished and time.monotonic() < deadline:
        time.sleep(0.05)

    written = (store.index).read_text(encoding="utf-8")
    assert TOKEN not in written, "the secret reached the run index"
    assert MASK in written

    recorded = store.get(active.id)
    assert TOKEN not in recorded.command
    assert TOKEN not in " ".join(recorded.argv)
    assert recorded.params["token"] == MASK
    assert TOKEN not in store.output(active.id), "the secret reached the stored output"
