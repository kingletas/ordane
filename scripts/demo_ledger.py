"""Writes invented deploy ledgers, chained the way a deploy playbook chains them.

Every name, host, commit and checksum here is made up. The dates are relative
to now so the newest deploy is always recent.

The hash of each record is computed by the console's own reader, so a ledger
written here is one the reader can verify, and a test holds the reader to a
record the playbook's tool wrote.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ordane.insight.ledger import GENESIS, record_hash

ALEX = {
    "git_email": "alex@example.com",
    "os_user": "alex",
    "control_host": "ops-laptop",
    "remote_user": "deploy",
}
PRIYA = {
    "git_email": "priya@example.com",
    "os_user": "priya",
    "control_host": "priya-x1",
    "remote_user": "deploy",
}
JORDAN = {
    "git_email": "jordan@example.com",
    "os_user": "jordan",
    "control_host": "ops-laptop",
    "remote_user": "deploy",
}

SAM = ("sam@example.com", "SHA256:q8Zk3vN0pX7dLr2mYt5aWc9bEf1gHj4uKs6oIl8nRe0")
RENEE = ("renee@example.com", "SHA256:Hc4pW9sLq2Zt7xVb1nRk6mYd3fJg8aUe5oKi0lTs2wQ")

# (days ago, hour, who deploys, approver or None, window, how it ends, verified by)
# How it ends: `live`, `backup-failed`, `cut-short`, or `built`.
STAGING = (
    (26, 10, ALEX, SAM, False, "live", PRIYA),
    (19, 14, PRIYA, SAM, True, "live", None),
    (12, 11, JORDAN, RENEE, True, "backup-failed", None),
    (12, 13, JORDAN, RENEE, True, "live", ALEX),
    (6, 9, ALEX, RENEE, False, "cut-short", None),
    (6, 10, ALEX, RENEE, False, "live", None),
    (1, 15, PRIYA, SAM, True, "live", JORDAN),
)

DOCKER = (
    (9, 16, ALEX, None, False, "live", None),
    (3, 12, JORDAN, None, False, "built", None),
    (0, 9, PRIYA, None, True, "live", None),
)


def write(directory: Path) -> list[Path]:
    """Writes `staging.audit.jsonl` and `docker.audit.jsonl` into a directory, replacing them."""
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for environment, plan in (("staging", STAGING), ("docker", DOCKER)):
        path = directory / f"{environment}.audit.jsonl"
        records: list[dict] = []
        for index, deploy in enumerate(plan):
            records += _deploy(environment, index, *deploy)
        _chain(path, records)
        written.append(path)
    return written


def _deploy(environment, index, days_ago, hour, actor, approver, window, ending, verifier):
    local = datetime.now().astimezone().replace(minute=0, second=0, microsecond=0)
    start = (local - timedelta(days=days_ago)).replace(hour=hour).astimezone(UTC)
    release = f"{start:%Y%m%d}_{int(start.timestamp())}_{environment}"
    commit = _hex(f"{environment}-commit-{index}", 40)
    artefact = _hex(f"{environment}-archive-{index}", 64)
    clock = [start]

    def at(minutes: float = 0) -> str:
        clock[0] = clock[0] + timedelta(minutes=minutes)
        return clock[0].strftime("%Y-%m-%dT%H:%M:%SZ")

    # Each deploy takes a little longer or less than the last, so the spread a
    # reader sees is a spread rather than one figure repeated.
    def stretch(minutes: float) -> float:
        return round(minutes * (0.7 + 0.25 * ((index * 3 + days_ago) % 5)), 2)

    def record(event: str, minutes: float, who=actor, **detail) -> dict:
        return {
            "event": event,
            "env_name": environment,
            "release": release,
            "actor": who,
            "recorded_at": at(stretch(minutes)),
            **detail,
        }

    goes_live = ending != "built"
    found = [
        record(
            "deploy.started",
            0,
            branch="release/2.4" if index % 2 else "main",
            reused_release=False,
            goes_live=goes_live,
            playbook_commit=_hex(f"playbook-{index}", 40),
        )
    ]
    if approver:
        signer, key = approver
        found.append(
            record(
                "approval.verified",
                0.4,
                commit=commit,
                tag=f"approved/{start:%Y-%m-%d}",
                signer=signer,
                signing_key=key,
            )
        )
    found.append(
        record(
            "build.succeeded",
            6.5,
            commit=commit,
            artefact_sha256=artefact,
            builder=f"{environment}-builder1",
        )
    )
    if not goes_live:
        found.append(record("deploy.finished", 1.2, outcome="success"))
        return found
    found.append(
        record("cutover.started", 2.1, maintenance_window=window, artefact_sha256=artefact)
    )
    if ending == "backup-failed":
        found.append(
            record(
                "backup.failed",
                4.0,
                reason="window",
                error="snapshot-magento-database: the snapshot did not finish within 3600 seconds",
            )
        )
        return found
    if window:
        found.append(
            record(
                "backup.succeeded",
                3.2,
                reason="window",
                backup_id=f"db-snapshot-{clock[0]:%Y%m%d-%H%M}",
            )
        )
        found.append(record("maintenance.enabled", 0.3))
    if ending == "cut-short":
        return found
    found.append(
        record(
            "cutover.succeeded",
            4.8 if window else 1.1,
            maintenance_window=window,
            setup_upgrade_ran=window,
            backup_id=f"db-snapshot-{start:%Y%m%d-%H%M}" if window else "",
        )
    )
    found.append(
        record(
            "warmup.completed",
            2.6,
            requested=240,
            ok=236 if index % 3 else 240,
            percent=98.3 if index % 3 else 100.0,
        )
    )
    found.append(record("deploy.finished", 0.2, outcome="success"))
    if verifier:
        found.append(
            record("deploy.verified", 38, who=verifier, outcome="passed", upgrade_expected=window)
        )
    return found


def _chain(path: Path, payloads: list[dict]) -> None:
    previous = GENESIS
    lines = []
    for seq, payload in enumerate(payloads, 1):
        record = {"schema": 1, "seq": seq, "prev_hash": previous, **payload}
        record["hash"] = record_hash(record)
        previous = record["hash"]
        lines.append(json.dumps(record, sort_keys=True, ensure_ascii=False))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _hex(seed: str, size: int) -> str:
    return hashlib.sha256(seed.encode()).hexdigest()[:size]
