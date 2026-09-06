"""Fills a state directory with a demo history, so every measure has a source.

The demo opened on a console that had never run anything: two of the four
delivery measures and all three objectives said `Setup needed`, which is honest
and shows nobody what the page looks like when it is working.

Everything here is written through the console's own run store and its own
DORA emitter rather than as hand-made JSON: a fixture that bypasses the writer
is a fixture that drifts from it.

Usage:
  uv run python scripts/seed-demo.py STATE_DIR [REPO]

Dates are relative to now, so the newest run is always a couple of days old
however long it is since anybody looked at this.
"""

from __future__ import annotations

import shutil
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from ordane.core import config as config_module
from ordane.core import inventory as inventory_module
from ordane.record import dora
from ordane.record.store import Run, RunStore
from ordane.record.summary import HostResult, Summary

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REPO = ROOT / "examples" / "control-plane"

PLANE = "ordane/example"
ACTOR = "release@demo"
HOSTS = 6

# The releases that ship. Each is (days ago, hours past midnight, target,
# exit code, seconds it took): chosen so that every measure and objective on
# the Health page has something to say:
#
#   20 cutovers, 2 of them failed  → 90% success, under a 95% objective
#   2 of them over 45 minutes      → 90% inside it, which meets a 90% objective
#   both failures followed by a fix → a restore time with two samples in it
DEPLOYS = (
    (88, 9, "deploy", 0, 1980),
    (84, 14, "activate", 0, 1420),
    (79, 10, "deploy", 0, 2240),
    (74, 16, "deploy", 0, 1760),
    (70, 11, "activate", 0, 2610),
    (65, 9, "deploy", 2, 940),
    (65, 11, "deploy", 0, 2050),
    (58, 15, "deploy", 0, 1890),
    (52, 10, "activate", 0, 3120),
    (47, 13, "deploy", 0, 2380),
    (41, 9, "deploy", 0, 1660),
    (36, 17, "activate", 0, 2290),
    (30, 11, "deploy", 0, 2510),
    (24, 8, "deploy", 1, 1120),
    (24, 12, "deploy", 0, 2170),
    (19, 14, "activate", 0, 2860),
    (14, 10, "deploy", 0, 1980),
    (9, 15, "deploy", 0, 2120),
    (5, 11, "activate", 0, 1540),
    (2, 13, "deploy", 0, 2260),
)

# Everything else that gets run, so the history is not twenty deploys in a row.
# None of it is a deployment, so none of it moves a delivery measure.
ROUTINE = (
    (86, 8, "check", "docker", 0, 4, 0),
    (72, 9, "ping", "docker", 0, 3, 0),
    (63, 16, "flush-cache", "staging", 0, 41, 1),
    (50, 10, "maintenance-on", "staging", 0, 62, 2),
    (50, 11, "maintenance-off", "staging", 0, 78, 3),
    (33, 9, "ping", "docker", 0, 3, 0),
    (21, 14, "check", "docker", 0, 5, 0),
    (12, 10, "flush-cache", "staging", 0, 38, 1),
    (4, 9, "ping", "docker", 0, 3, 0),
)

RELEASES = (
    "Kingfisher-0",
    "Lantern-1",
    "Meridian-2",
    "Nocturne-3",
    "Obsidian-4",
)


def stamp(days_ago: int, hour: int) -> datetime:
    midnight = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return midnight - timedelta(days=days_ago) + timedelta(hours=hour)


def recap(environment: str, changed: int, failed: int = 0) -> dict:
    """A plausible PLAY RECAP, so a row can say what a run actually touched."""
    hosts = [
        HostResult(host=f"web-{index + 1}.{environment}", ok=12, changed=changed, failed=0)
        for index in range(HOSTS)
    ]
    if failed:
        hosts[-1] = HostResult(host=f"web-{HOSTS}.{environment}", ok=4, changed=0, failed=failed)
    return Summary(hosts=hosts, tasks=18, plays=3, has_recap=True).as_record()


def run_of(
    *,
    name: str,
    environment: str,
    started: datetime,
    exit_code: int,
    seconds: int,
    labels: dict[str, str],
    params: dict[str, str],
    changed: int,
    builder: str = "",
) -> Run:
    finished = started + timedelta(seconds=seconds)
    failed = 0 if exit_code == 0 else 1
    return Run(
        id=f"{started.strftime('%Y%m%dT%H%M%SZ')}-demo{seconds:04d}",
        kind="target",
        name=name,
        environment=environment,
        params=params,
        argv=["make", name, f"environment={environment}"],
        command=f"make {name} environment={environment}",
        actor=ACTOR,
        started=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        plane=PLANE,
        host="build-01",
        branch="main",
        commit=f"{abs(hash(started)) % 0x10000000:07x}",
        dirty=False,
        builder=builder,
        state="succeeded" if exit_code == 0 else "failed",
        finished=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_s=float(seconds),
        exit_code=exit_code,
        labels=labels,
        summary=recap(environment, changed if exit_code == 0 else 0, failed),
    )


def seed(state_dir: Path, repo: Path) -> Path:
    shutil.rmtree(state_dir, ignore_errors=True)
    store = RunStore(state_dir)
    store.prepare()
    events = state_dir / "deployments.jsonl"
    config = config_module.load_quietly(repo)

    # Read rather than typed: the demo should record the builder the same way a
    # real run does, from the environment's own inventory.
    builders = {}
    for environment in ("staging", "docker"):
        found = inventory_module.read(repo, f"inventory/{environment}")
        group = found.group("builder") if found.known else None
        builders[environment] = ", ".join(group.hosts) if group else ""

    made = []
    for index, (days, hour, name, code, seconds) in enumerate(DEPLOYS):
        release = RELEASES[index % len(RELEASES)]
        made.append(
            run_of(
                name=name,
                environment="staging",
                started=stamp(days, hour),
                exit_code=code,
                seconds=seconds,
                labels=config.labels_for(name),
                params={"release": release} if name == "activate" else {},
                changed=4,
                builder=builders.get("staging", ""),
            )
        )
    for days, hour, name, environment, code, seconds, changed in ROUTINE:
        made.append(
            run_of(
                name=name,
                environment=environment,
                started=stamp(days, hour),
                exit_code=code,
                seconds=seconds,
                labels=config.labels_for(name),
                params={},
                changed=changed,
                builder=builders.get(environment, ""),
            )
        )

    for run in sorted(made, key=lambda one: one.started):
        store.append(run)
        # The console writes both ends of a deployment; the reporter only ever
        # wrote the one that succeeded.
        dora.emit_start(run, events)
        dora.emit_finish(run, events)
    return events


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: seed-demo.py STATE_DIR [REPO]")
    state_dir = Path(sys.argv[1]).expanduser().resolve()
    repo = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else DEFAULT_REPO
    events = seed(state_dir, repo)
    print(f"seeded {len(DEPLOYS) + len(ROUTINE)} runs into {state_dir}")
    print(f"deployment events in {events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
