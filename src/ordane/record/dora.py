"""Emits deployment events into the control plane's own DORA log.

The playbooks emit `*.succeeded` at their phase boundaries, and the reporter
infers a failure from a `*.started` with no matching `*.succeeded`. Two of the
three deploy paths emit no `*.started` at all, so a failed run currently writes
nothing and cannot be told apart from one that never happened. A console run
has an exit code either way, so it writes both ends.

Instrumentation must never be the reason a release is lost: every failure here
is swallowed and reported to the caller rather than raised.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .store import Run

SCHEMA = 1
SOURCE = "ordane"

# Only a run the config marks as a deploy or a cutover is a deployment event.
STARTED = "started"
SUCCEEDED = "succeeded"
FAILED = "failed"


@dataclass(frozen=True)
class Emission:
    written: bool
    event: str = ""
    path: Path | None = None
    error: str = ""


def phase_for(run: Run) -> str:
    """`cutover` for a run that flips a release, `build` otherwise."""
    return "cutover" if run.labels.get("cutover") == "true" else "build"


def is_deployment(run: Run) -> bool:
    return run.labels.get("deploy") == "true" or run.labels.get("cutover") == "true"


def _event(run: Run, outcome: str) -> dict:
    result = run.result
    record = {
        "schema": SCHEMA,
        "ts": run.finished or run.started,
        "event": f"{phase_for(run)}.{outcome}",
        "env_name": run.environment,
        "release": run.params.get("release", ""),
        "previous_release": "",
        "is_rollback": False,
        "actor": run.actor,
        "branch": run.params.get("branch_name", ""),
        "playbook": run.name,
        "source": SOURCE,
        "run_id": run.id,
    }
    if outcome != STARTED:
        record["duration_s"] = run.duration_s
        record["exit_code"] = run.exit_code
        if result.has_recap:
            record["hosts"] = len(result.hosts)
            record["changed"] = result.changed
            record["failed"] = result.failed
    return record


def emit(run: Run, path: Path, outcome: str) -> Emission:
    """Appends one event, or reports why it could not."""
    if not is_deployment(run):
        return Emission(written=False, error="not a deployment run")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        record = _event(run, outcome)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:
        return Emission(written=False, error=str(exc))
    return Emission(written=True, event=record["event"], path=path)


def emit_start(run: Run, path: Path) -> Emission:
    return emit(run, path, STARTED)


def emit_finish(run: Run, path: Path) -> Emission:
    """The half that does not exist today for a lower-environment deploy."""
    outcome = SUCCEEDED if run.exit_code == 0 else FAILED
    return emit(run, path, outcome)
