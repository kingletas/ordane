"""Five make targets need a control plane, and refuse rather than guess at one.

A default would be a path the reader never named, so what they get back is an
error about somewhere they have never heard of instead of the one line they
were missing. The refusal names the argument, gives an example that exists,
and points at the demo, which needs no argument at all.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GUARD = ROOT / "scripts" / "require-repo"
MAKEFILE = ROOT / "Makefile"

TARGETS = ("app", "serve", "status", "catalog", "doctor")


def refuse(target: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(GUARD), target, ""],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )


def test_every_target_refuses_with_the_same_block():
    for target in TARGETS:
        result = refuse(target)
        assert result.returncode == 2, (
            f"`{target}` without a control plane exited {result.returncode}, and a "
            "missing argument is 2 here"
        )
        assert f"make {target}" in result.stderr, f"the refusal does not name `{target}`"
        assert "REPO=" in result.stderr, "the refusal does not say what to pass"
        assert "make demo" in result.stderr, "the refusal does not point at the demo"


def test_the_example_it_offers_is_really_there():
    """An example nobody can run is worse than none, because it is tried first."""
    assert "REPO=examples/control-plane" in refuse("app").stderr
    assert (ROOT / "examples" / "control-plane").is_dir()


def test_a_control_plane_is_let_through_in_silence():
    """The quiet path, which a test of the refusal alone would never reach."""
    result = subprocess.run(
        [str(GUARD), "app", "examples/control-plane"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_repo_carries_no_default():
    """A default path is what removes the need for the check above."""
    body = MAKEFILE.read_text(encoding="utf-8")
    assignments = [line for line in body.splitlines() if line.startswith(("REPO ?=", "REPO ="))]
    assert assignments == ["REPO ?="], f"REPO has a default again: {assignments}"


def test_every_target_is_wired_to_the_guard():
    """The script decides nothing for a target that never calls it."""
    body = MAKEFILE.read_text(encoding="utf-8")
    for target in TARGETS:
        assert f"\n{target}: require-repo-{target}" in body, (
            f"`{target}` does not take the guard as its first prerequisite, so a "
            "missing REPO= reaches the tool instead"
        )


def test_make_itself_refuses():
    """The wiring above is a reading of the file; this is make actually running."""
    result = subprocess.run(
        ["make", "--no-print-directory", "catalog", "REPO="],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 2
    assert "make catalog needs a control plane" in result.stderr


def test_help_says_which_targets_need_one():
    result = subprocess.run(
        ["make", "--no-print-directory", "help"],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert result.returncode == 0
    for target in TARGETS:
        assert target in result.stdout
    assert "need REPO=" in result.stdout
