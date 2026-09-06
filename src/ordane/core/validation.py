"""Checks a control plane can run against itself, in a container it declares.

This is not an execution node. The run stays on this machine, as you; what the
container pins is the environment, meaning which Ansible, which collections and
which Python. Otherwise a run uses whatever `ansible` is on the PATH, which is
the one thing a reproducible release cannot depend on.

What it buys is validation with no host in the room: a syntax check, an
inventory that parses, a role that resolves.
"""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import host

# Long enough for a molecule scenario, short enough that a wedged container
# does not hold a window until somebody notices.
TIMEOUT_SECONDS = 900

# Where the repository is mounted. Fixed rather than configurable: a check that
# has to know the host's path is one that only runs on one machine.
WORKDIR = "/work"

DEFAULT_ENGINE = ("docker",)

# A stopped engine should be answered in a moment, not waited on by a window.
_ENGINE_TIMEOUT = 3.0
_ANSWERED: dict[str, bool] = {}

# An image reference, as a registry writes one. Checked rather than escaped,
# because a name that needs escaping is not a name.
_IMAGE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}$")


@dataclass(frozen=True)
class Check:
    """One thing a control plane asks of itself, and the command that asks it."""

    name: str
    argv: tuple[str, ...]

    @property
    def display(self) -> str:
        return " ".join(self.argv)


@dataclass(frozen=True)
class Suite:
    """The image the checks run in, and the checks. Both come from the repository."""

    image: str = ""
    checks: tuple[Check, ...] = ()
    engine: tuple[str, ...] = DEFAULT_ENGINE

    @property
    def declared(self) -> bool:
        return bool(self.image and self.checks)


@dataclass(frozen=True)
class Result:
    """What one check did, and what it printed doing it."""

    check: Check
    ok: bool
    output: str = ""
    seconds: float = 0.0
    skipped: str = ""

    @property
    def state(self) -> str:
        if self.skipped:
            return "skipped"
        return "passed" if self.ok else "failed"


@dataclass
class Report:
    results: list[Result] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and all(one.ok or one.skipped for one in self.results)

    @property
    def failed(self) -> list[Result]:
        return [one for one in self.results if not one.ok and not one.skipped]

    @property
    def summary(self) -> str:
        if self.error:
            return self.error
        passed = sum(1 for one in self.results if one.ok and not one.skipped)
        return f"{passed} of {len(self.results)} passed"


def read(raw) -> Suite:
    """The suite a control plane declared, or an empty one."""
    if not isinstance(raw, dict):
        return Suite()
    checks = []
    for entry in raw.get("checks") or []:
        if not isinstance(entry, dict):
            continue
        argv = entry.get("run")
        if not isinstance(argv, list | tuple) or not argv:
            continue
        checks.append(
            Check(
                name=str(entry.get("name") or argv[0]),
                argv=tuple(str(one) for one in argv),
            )
        )
    engine = raw.get("engine")
    if isinstance(engine, str):
        # `engine: podman --remote` is how a person writes it. Read as a list of
        # characters it would run `p`, and discarded it would silently be docker.
        runs_it = tuple(shlex.split(engine))
    elif isinstance(engine, list | tuple):
        runs_it = tuple(str(one) for one in engine)
    else:
        runs_it = ()
    return Suite(
        image=str(raw.get("image", "") or ""),
        checks=tuple(checks),
        engine=runs_it or DEFAULT_ENGINE,
    )


def available(suite: Suite) -> str:
    """Why the suite cannot run, or nothing. Never a reason a deploy cannot."""
    if not suite.image:
        return "No validation image is declared in the configuration."
    if not _IMAGE.match(suite.image):
        return "That image reference is not one a registry would write."
    if not suite.checks:
        return "No checks are declared in the configuration."
    engine = suite.engine[0]
    if host.which(engine) is None:
        return f"{engine} is not on the PATH, so nothing can be run in a container."
    if not _engine_answers(engine):
        return f"{engine} is installed but not answering, so it is probably not running."
    return ""


def _engine_answers(engine: str) -> bool:
    """Whether the engine will actually accept work, cached for the session.

    A binary on the PATH is not a running daemon. Without this a stopped engine
    reported every check as FAILED, which reads as the checks being broken
    rather than as nothing having run them.
    """
    if engine in _ANSWERED:
        return _ANSWERED[engine]
    try:
        done = subprocess.run(  # noqa: S603
            host.argv([engine, "version", "--format", "{{.Server.Version}}"]),
            capture_output=True,
            timeout=_ENGINE_TIMEOUT,
            check=False,
        )
        answered = done.returncode == 0
    except (OSError, subprocess.SubprocessError):
        answered = False
    _ANSWERED[engine] = answered
    return answered


def argv_for(repo: Path, suite: Suite, check: Check) -> list[str]:
    """The container invocation, which is the same shape for every check.

    Read-only, no network, and as this user rather than root: a check that
    needs to write to the repository or reach a host is not a check.
    """
    return [
        *suite.engine,
        "run",
        "--rm",
        "--network",
        "none",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{repo}:{WORKDIR}:ro",
        "--workdir",
        WORKDIR,
        "--",
        suite.image,
        *check.argv,
    ]


def run_one(repo: Path, suite: Suite, check: Check) -> Result:
    """One check, in the container. Never raises: a report is not a run."""
    started = time.monotonic()
    try:
        finished = subprocess.run(  # noqa: S603
            argv_for(repo, suite, check),
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return Result(check, ok=False, output=f"Gave up after {TIMEOUT_SECONDS} seconds.")
    except OSError as exc:
        return Result(check, ok=False, output=str(exc))
    took = round(time.monotonic() - started, 2)
    output = (finished.stdout or "") + (finished.stderr or "")
    return Result(check, ok=finished.returncode == 0, output=output.strip(), seconds=took)


def run(repo: Path, suite: Suite, on_result=None) -> Report:
    """Every check, in order, reporting each as it finishes."""
    why = available(suite)
    if why:
        return Report(error=why)
    report = Report()
    for check in suite.checks:
        result = run_one(repo, suite, check)
        report.results.append(result)
        if on_result is not None:
            on_result(result)
    return report
