"""The two records this console does not write, read so they can be projected too.

The run history covers what this console launched. It is a small part of what
happened: there are years of releases before it existed, and a patch ledger the
control plane keeps itself. Both are already on disk in the repository, both
are append-only, and neither is written here: they are read exactly as the
reporter and the playbooks left them.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path

# Where each lives in a control plane that follows the estate's layout. Both
# are overridable, because a repository is not obliged to look like this one.
RELEASES = "docs/dora/backfill.jsonl"
RELEASES_CSV = "docs/dora/history.csv"
PATCHES = "patches/ledger.jsonl"


@dataclass(frozen=True)
class Release:
    """One cutover, as the reporter recorded it."""

    name: str
    at: str
    environment: str
    # `Eagle@2022-11-03`. A release name is not unique over six years: this
    # estate has shipped two called Eagle, so the reporter writes a key and
    # the graph is built on it rather than on the name.
    key: str = ""
    outcome: str = ""
    version: str = ""
    platform: str = ""
    platform_upgrade: bool = False
    is_rollback: bool = False
    previous: str = ""
    commit_count: int = 0
    lead_time_days: float | None = None
    actor: str = ""
    theme: str = ""

    @property
    def identity(self) -> str:
        """What makes this release this one, rather than another of the name."""
        return self.key or f"{self.name}@{self.at[:10]}"

    @property
    def succeeded(self) -> bool:
        return self.outcome == "success"


@dataclass(frozen=True)
class PatchEvent:
    """One patch, applied to or removed from one environment, at one moment."""

    patch: str
    at: str
    environment: str
    state: str = "present"
    actor: str = ""
    # True where the ledger was seeded rather than observed: the patch was on
    # disk and assumed applied. It is a claim about the past, not a record of
    # one, and anything counting it should be able to leave it out.
    assumed: bool = False
    hosts_ok: int = 0
    hosts_total: int = 0

    @property
    def applied(self) -> bool:
        return self.state == "present"


@dataclass(frozen=True)
class Backfill:
    releases: list[Release] = field(default_factory=list)
    patches: list[PatchEvent] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def empty(self) -> bool:
        return not self.releases and not self.patches


def read(repo: Path, releases: str = RELEASES, patches: str = PATCHES) -> Backfill:
    """Everything a control plane already knows, or a note saying it does not."""
    notes: list[str] = []
    found_releases = read_releases(repo / releases)
    if not found_releases:
        found_releases = read_release_csv(repo / RELEASES_CSV)
        if found_releases:
            notes.append(
                f"releases came from {RELEASES_CSV}, which carries less than the event log"
            )
    if not found_releases:
        notes.append(f"no release history at {releases} or {RELEASES_CSV}")

    found_patches = read_patches(repo / patches)
    if not found_patches:
        notes.append(f"no patch ledger at {patches}")
    return Backfill(releases=found_releases, patches=found_patches, notes=notes)


def read_releases(path: Path) -> list[Release]:
    """The reporter's own event log, which carries the chain between releases."""
    return [
        Release(
            name=str(record.get("release", "")),
            at=str(record.get("ts", "")),
            environment=str(record.get("env_name", "")),
            key=str(record.get("release_key", "") or ""),
            outcome=str(record.get("outcome", "")),
            version=_clean(record.get("version")),
            platform=_clean(record.get("platform")),
            platform_upgrade=bool(record.get("platform_upgrade")),
            is_rollback=bool(record.get("is_rollback")),
            previous=str(record.get("previous_release", "") or ""),
            commit_count=_int(record.get("commit_count")),
            lead_time_days=_float(record.get("lead_time_days")),
            actor=str(record.get("actor", "") or ""),
            theme=str(record.get("theme", "") or ""),
        )
        for record in _jsonl(path)
        if record.get("release")
    ]


def read_release_csv(path: Path) -> list[Release]:
    """The rolled-up CSV, for a control plane that keeps only that.

    It has no `previous_release`, so the chain between releases is rebuilt from
    the order they happened in: which is the same answer wherever one
    environment releases one at a time, and is not claimed to be more.
    """
    if not path.is_file():
        return []
    rows = []
    with path.open(encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("release")]
    rows.sort(key=lambda row: row.get("date", ""))

    previous: dict[str, str] = {}
    releases = []
    for row in rows:
        environment = str(row.get("env_name", ""))
        releases.append(
            Release(
                name=str(row.get("release", "")),
                at=f"{row.get('date', '')}T00:00:00Z",
                environment=environment,
                key=f"{row.get('release', '')}@{row.get('date', '')}",
                outcome=str(row.get("outcome", "")),
                version=_clean(row.get("version")),
                platform=_clean(row.get("platform")),
                platform_upgrade=_bool(row.get("platform_upgrade")),
                is_rollback=_bool(row.get("is_rollback")),
                previous=previous.get(environment, ""),
                commit_count=_int(row.get("commit_count")),
                lead_time_days=_float(row.get("lead_time_days")),
                actor=str(row.get("actor", "") or ""),
                theme=str(row.get("theme", "") or ""),
            )
        )
        previous[environment] = releases[-1].identity
    return releases


def read_patches(path: Path) -> list[PatchEvent]:
    return [
        PatchEvent(
            patch=str(record.get("patch", "")),
            at=str(record.get("ts", "")),
            environment=str(record.get("env_name", "")),
            state=str(record.get("state", "present")),
            actor=str(record.get("actor", "") or ""),
            assumed=bool(record.get("assumed")),
            hosts_ok=_int(record.get("hosts_ok")),
            hosts_total=_int(record.get("hosts_total")),
        )
        for record in _jsonl(path)
        if record.get("patch")
    ]


def _jsonl(path: Path) -> list[dict]:
    """Every readable line. A malformed one is skipped, not fatal: these files
    are appended to by other tools and one bad line must not cost the rest."""
    if not path.is_file():
        return []
    records = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if isinstance(record, dict):
            records.append(record)
    return records


def _clean(value) -> str:
    """The reporter writes an em dash where it has no value."""
    text = str(value or "").strip()
    return "" if text in ("—", "-", "none", "null") else text


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _bool(value) -> bool:
    return str(value).strip().lower() in ("true", "1", "yes")
