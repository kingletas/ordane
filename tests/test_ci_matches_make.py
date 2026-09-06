"""What CI runs has to exist here, and `make ci` has to be the same thing.

A workflow that invokes a target this repository does not have fails ten
minutes after a push, on somebody else's machine, for a reason that was
knowable before it left. That is the failure this file exists to catch.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "check.yml"
MAKEFILE = ROOT / "Makefile"


def make_targets() -> set[str]:
    return set(re.findall(r"(?m)^([a-zA-Z][\w-]*):", MAKEFILE.read_text(encoding="utf-8")))


def workflow_steps() -> list[str]:
    spec = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    found = []
    for job in spec["jobs"].values():
        for step in job["steps"]:
            if "run" in step:
                found.append(step["run"])
    return found


def make_calls(commands: list[str]) -> set[str]:
    """Every `make <target>` a list of shell commands invokes."""
    called = set()
    for command in commands:
        for line in command.splitlines():
            for target in re.findall(r"\bmake\s+([a-zA-Z][\w-]*)", line):
                called.add(target)
    return called


def test_every_target_ci_invokes_exists():
    missing = sorted(make_calls(workflow_steps()) - make_targets())
    assert missing == [], f"the workflow calls targets this repository does not have: {missing}"


def test_make_ci_runs_what_ci_runs():
    """`make ci` is the local rehearsal, so it has to cover what CI runs."""
    body = MAKEFILE.read_text(encoding="utf-8")
    recipe = body[body.index("\nci:") :]
    recipe = recipe[: recipe.index("\n.PHONY")] if "\n.PHONY" in recipe else recipe
    for target in sorted(make_calls(workflow_steps())):
        assert target in recipe, f"`make ci` does not run `{target}`, which CI does"


def test_the_smoke_stays_out_of_ci():
    """It drives the real window, and one of its checks was measured flaky there.

    A gate that fails at random teaches people to press re-run rather than read it,
    which costs more than it catches. CI proves the packages install and run instead,
    which a runner does the same way every time.

    It still has to run headless here, which is what `xvfb-run` in `make ci` is for.
    """
    in_ci = [step for step in workflow_steps() if "smoke" in step]
    assert in_ci == [], f"the smoke is back in CI, where it was measured flaky: {in_ci}"
    assert "xvfb-run" in MAKEFILE.read_text(encoding="utf-8")


def test_ci_proves_both_packages_install():
    """A package that builds and cannot start is what a test suite cannot see."""
    body = WORKFLOW.read_text(encoding="utf-8")
    for proof in ("apt-get install -y ./dist/ordane", "flatpak install", "--version"):
        assert proof in body, f"CI no longer proves a package runs: {proof}"


def test_the_scan_finds_something():
    """Both checks above are vacuous if nothing is parsed out of the workflow."""
    called = make_calls(workflow_steps())
    assert called, "no `make` invocations were found in the workflow"
    assert "check" in called
