"""The declared settings have to arrive in the child, or the block is decoration.

This is the check the unit tests cannot make: the runner reads the config for
itself at launch, so the only proof that a declaration takes effect is a real
process reporting its own environment back.
"""

from __future__ import annotations

import time
from pathlib import Path

from ordane.core.command import Command
from ordane.record.runner import Runner
from ordane.record.store import RunStore


def _ran(repo: Path, state: Path, argv: list[str]):
    store = RunStore(state)
    store.prepare()
    runner = Runner(store, repo, state / "events.jsonl")
    active = runner.start(
        kind="target",
        name="show",
        environment="local",
        params={},
        command=Command.build(argv),
    )
    deadline = time.monotonic() + 20
    while not active.finished and time.monotonic() < deadline:
        time.sleep(0.05)
    assert active.finished, "the run never ended"
    return store, active


def test_a_declared_setting_reaches_the_child(tmp_path):
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / ".ordane.yml").write_text(
        "ansible:\n  ANSIBLE_ROLES_PATH: /declared/roles\n", encoding="utf-8"
    )
    store, active = _ran(repo, tmp_path / "state", ["printenv", "ANSIBLE_ROLES_PATH"])
    assert "/declared/roles" in store.output(active.id)


def test_the_run_records_what_was_forced(tmp_path):
    """A run that behaved differently because of a setting says so on its record."""
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / ".ordane.yml").write_text("ansible:\n  ANSIBLE_TIMEOUT: 60\n", encoding="utf-8")
    store, active = _ran(repo, tmp_path / "state", ["true"])
    assert store.get(active.id).settings == {"ANSIBLE_TIMEOUT": "60"}


def test_a_plane_that_declares_nothing_records_nothing(tmp_path):
    repo = tmp_path / "plane"
    repo.mkdir()
    store, active = _ran(repo, tmp_path / "state", ["true"])
    assert store.get(active.id).settings == {}


def test_an_edited_config_is_read_at_the_next_launch(tmp_path):
    """The runner is built once. Reading at launch is what stops it going stale."""
    repo = tmp_path / "plane"
    repo.mkdir()
    config = repo / ".ordane.yml"
    state = tmp_path / "state"

    config.write_text("ansible:\n  ANSIBLE_ROLES_PATH: /first\n", encoding="utf-8")
    store, first = _ran(repo, state, ["printenv", "ANSIBLE_ROLES_PATH"])
    assert "/first" in store.output(first.id)

    config.write_text("ansible:\n  ANSIBLE_ROLES_PATH: /second\n", encoding="utf-8")
    store, second = _ran(repo, state, ["printenv", "ANSIBLE_ROLES_PATH"])
    assert "/second" in store.output(second.id)


def test_a_broken_block_does_not_stop_a_run_that_was_already_allowed(tmp_path):
    """`load_quietly` is deliberate: the doctor and the config dialog report the
    error, and a launch already past the gate does not die inside the runner."""
    repo = tmp_path / "plane"
    repo.mkdir()
    (repo / ".ordane.yml").write_text("ansible:\n  ANSIBLE_CONFIG: ./ours.cfg\n", encoding="utf-8")
    store, active = _ran(repo, tmp_path / "state", ["true"])
    assert store.get(active.id).exit_code == 0
    assert store.get(active.id).settings == {}


def test_nothing_a_run_starts_may_page(tmp_path):
    """A pty makes `ansible-config dump` and `ansible-doc` page, and a pager waits
    for a keypress nobody can give: the run hangs with a blank screen."""
    repo = tmp_path / "plane"
    repo.mkdir()
    store, active = _ran(repo, tmp_path / "state", ["printenv", "PAGER"])
    assert store.output(active.id).strip() == "cat"
