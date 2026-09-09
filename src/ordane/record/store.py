"""Records every run as JSONL plus a redacted output file.

The schema mirrors the DORA event log's so the two can be read together.
"""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from .summary import Summary

SCHEMA = 2


@dataclass
class Run:
    id: str
    kind: str
    name: str
    environment: str
    params: dict[str, str]
    argv: list[str]
    command: str
    actor: str
    started: str
    # The absolute path this ran from. Kept because it is true and useful
    # locally; never the thing a shared history is keyed on.
    repo: str = ""
    # What this control plane is called, portably. The key everything scopes on.
    plane: str = ""
    # Where it ran, and which installation minted the id.
    host: str = ""
    installation: str = ""
    # What was checked out when this was launched. The commit is the only way
    # a lead time can ever be computed from a run rather than from a report,
    # and a deploy from a dirty tree is one nobody can reproduce.
    branch: str = ""
    commit: str = ""
    dirty: bool = False
    # The host the release was built on, read from the environment's inventory
    # at launch. One builder can serve several environments, so which one made
    # an artefact is not answerable from the environment name.
    builder: str = ""
    # Which launch this was a step of. A runbook runs its checks, its precheck,
    # the operation and its postcheck as four records, and without this the
    # only thing relating them is the clock.
    sequence: str = ""
    # Who asked for it: `hand`, `repeat`, `step` or `schedule`. It decides
    # whether a row folds into a summary, because a run somebody pressed the
    # button for is one they will look for afterwards. A record written before
    # this field existed reads as `hand`, which is what every one of them was.
    origin: str = "hand"
    # The ANSIBLE_* settings this control plane declared, applied to this run.
    # A run that behaved differently because of them says so on its own record.
    settings: dict[str, str] = field(default_factory=dict)
    state: str = "running"
    finished: str = ""
    duration_s: float = 0.0
    exit_code: int | None = None
    schema: int = SCHEMA
    labels: dict[str, str] = field(default_factory=dict)
    summary: dict = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0

    @property
    def result(self) -> Summary:
        """What Ansible reported, parsed from the run's own output."""
        return Summary.from_record(self.summary)

    def as_record(self) -> dict:
        return asdict(self)


def new_id() -> str:
    """A sortable identifier: the timestamp, then enough randomness to be unique."""
    return f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(3)}"


def now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class RunStore:
    """Append-only run history under one directory."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.output_dir = root / "output"
        self.index = root / "runs.jsonl"

    def prepare(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.index.touch(exist_ok=True)

    def output_path(self, run_id: str) -> Path:
        return self.output_dir / f"{run_id}.log"

    def append(self, run: Run) -> None:
        """Writes one immutable record. A finished run is a second line, not an edit."""
        self.prepare()
        with self.index.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(run.as_record(), separators=(",", ":")) + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def all(self, repo: Path | str | None = None, plane: str = "") -> list[Run]:
        """Runs newest first, later records superseding earlier ones.

        The history is one file per repository, so a view that did not scope to its own
        would judge another control plane's runs as its own. A record written before runs
        carried a repository is never claimed by one.
        """
        if not self.index.is_file():
            return []
        order: dict[str, int] = {}
        latest: dict[str, Run] = {}
        for line in self.index.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            known = {f for f in Run.__dataclass_fields__}
            key = record.get("id", "")
            # First seen wins the position: a later line for the same run is an
            # update to it, not a new thing that happened after everything else.
            order.setdefault(key, len(order))
            latest[key] = Run(**{k: v for k, v in record.items() if k in known})
        # `started` has one-second resolution, so three runs of one runbook can
        # share it, and then the order was whatever a random id suffix decided.
        # The file is append-only, so the line it arrived on is the true order.
        runs = sorted(latest.values(), key=lambda r: (r.started, order.get(r.id, 0)), reverse=True)
        if repo is None and not plane:
            return runs
        wanted = str(repo) if repo is not None else ""
        # A record written before control planes had names carries only a path,
        # so it is matched on that. Nothing is dropped from an old history.
        return [
            r
            for r in runs
            if (plane and r.plane == plane) or (wanted and not r.plane and r.repo == wanted)
        ]

    def steps_of(self, sequence: str) -> list[Run]:
        """Every run of one launch, oldest first. Empty for a run that stood alone."""
        if not sequence:
            return []
        # Reversed from `all` rather than sorted again: the steps of a launch
        # share a second, and re-sorting on `started` alone throws away the
        # append order that is the only thing separating them.
        return [one for one in reversed(self.all()) if one.sequence == sequence]

    def get(self, run_id: str) -> Run | None:
        return next((r for r in self.all() if r.id == run_id), None)

    def planes(self) -> list[str]:
        """Every control plane the history holds runs for, by name or by path."""
        return sorted({r.plane or r.repo for r in self.all() if r.plane or r.repo})

    def output(self, run_id: str) -> str:
        path = self.output_path(run_id)
        return path.read_text(encoding="utf-8", errors="replace") if path.is_file() else ""
