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

# The tasks a deploy walks through, so the lane chart in the run view has a
# shape to draw. Written as Ansible actually prints them and parsed back by the
# same reader a real run goes through — a fixture that bypasses the parser is
# a fixture that drifts from it.
TASKS = (
    "Gathering Facts",
    "Fetch the release",
    "Stop the service",
    "Sync files",
    "Start the service",
    "Verify the health endpoint",
)

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

# What a repository that pings every half hour looks like, which is the case
# the run-density rules exist for. Marked `schedule` because nobody pressed a
# button for any of them: that is what lets them fold into one summary row,
# and it is a fixture standing in for a cron nothing here runs yet.
SCHEDULED_HOURS = 48
SCHEDULED_EVERY_MINUTES = 30

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


def hosts_of(environment: str, count: int = HOSTS) -> list[str]:
    return [f"web-{index + 1}.{environment}" for index in range(count)]


def recap(environment: str, changed: int, failed: int = 0, count: int = HOSTS) -> dict:
    """A plausible PLAY RECAP, so a row can say what a run actually touched."""
    names = hosts_of(environment, count)
    hosts = [
        HostResult(host=name, ok=12, changed=changed if index < changed else 0, failed=0)
        for index, name in enumerate(names)
    ]
    if failed:
        hosts[-1] = HostResult(host=names[-1], ok=4, changed=0, failed=failed)
    return Summary(hosts=hosts, tasks=len(TASKS), plays=1, has_recap=True).as_record()


def transcript(environment: str, hosts: list[str], changed: int, failed: int) -> str:
    """What Ansible prints, for a run that touched these hosts."""
    lines = [f"PLAY [{environment}] " + "*" * 40, ""]
    for index, task in enumerate(TASKS):
        lines.append(f"TASK [{task}] " + "*" * 40)
        for position, host in enumerate(hosts):
            broken = failed and host == hosts[-1] and index == len(TASKS) - 2
            if broken:
                lines.append(
                    f'fatal: [{host}]: FAILED! => {{"changed": false, '
                    f'"msg": "the health endpoint answered 502 after 30s"}}'
                )
            elif index == 0:
                lines.append(f"ok: [{host}]")
            elif changed and position < changed:
                lines.append(f"changed: [{host}]")
            elif index in (1, 2) and position >= changed:
                lines.append(f"skipping: [{host}]")
            else:
                lines.append(f"ok: [{host}]")
        lines.append("")
    lines.append("PLAY RECAP " + "*" * 40)
    for host in hosts:
        broke = failed and host == hosts[-1]
        lines.append(
            f"{host} : ok={4 if broke else 12} changed={0 if broke else changed} "
            f"unreachable=0 failed={1 if broke else 0} skipped=2 rescued=0 ignored=0"
        )
    return "\n".join(lines) + "\n"


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
    origin: str = "hand",
    suffix: str = "",
    count: int = HOSTS,
) -> Run:
    finished = started + timedelta(seconds=seconds)
    failed = 0 if exit_code == 0 else 1
    return Run(
        id=f"{started.strftime('%Y%m%dT%H%M%SZ')}-demo{seconds:04d}{suffix}",
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
        origin=origin,
        state="succeeded" if exit_code == 0 else "failed",
        finished=finished.strftime("%Y-%m-%dT%H:%M:%SZ"),
        duration_s=float(seconds),
        exit_code=exit_code,
        labels=labels,
        summary=recap(environment, changed if exit_code == 0 else 0, failed, count),
    )


def _scheduled(config, builders: dict[str, str]) -> list[Run]:
    """Two days of half-hourly pings, so the roll-up has something to roll up.

    Forty-eight of every fifty runs on a repository like this say the same
    thing. Listed one per line the history stops being information, which is
    exactly what the density rules are for — and a demo that never shows them
    is a demo of a quiet repository.
    """
    made: list[Run] = []
    minutes = SCHEDULED_HOURS * 60
    for step in range(minutes // SCHEDULED_EVERY_MINUTES):
        started = datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(
            minutes=step * SCHEDULED_EVERY_MINUTES + 20
        )
        # One of them found something to change, so the ribbon is not flat and
        # the row that changed keeps its own line.
        moved = step in (7, 31)
        made.append(
            run_of(
                name="ping" if step % 3 else "check",
                environment="docker",
                started=started,
                exit_code=0,
                seconds=3 + (step % 4),
                labels=config.labels_for("ping"),
                params={},
                changed=1 if moved else 0,
                builder=builders.get("docker", ""),
                origin="schedule",
                suffix=f"s{step:03d}",
                count=2,
            )
        )
    return made


def seed(state_dir: Path, repo: Path) -> tuple[Path, int]:
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

    made.extend(_scheduled(config, builders))

    for run in sorted(made, key=lambda one: one.started):
        store.append(run)
        # The output a run printed, written the way the runner writes it, so
        # the lane chart and the log are read back through the real parser.
        store.output_path(run.id).write_text(
            transcript(
                run.environment,
                [one.host for one in run.result.hosts],
                run.result.changed and len([o for o in run.result.hosts if o.changed]),
                1 if run.exit_code else 0,
            ),
            encoding="utf-8",
        )
        # The console writes both ends of a deployment; the reporter only ever
        # wrote the one that succeeded.
        dora.emit_start(run, events)
        dora.emit_finish(run, events)
    return events, len(made)


def main() -> int:
    if len(sys.argv) < 2:
        sys.exit("usage: seed-demo.py STATE_DIR [REPO]")
    state_dir = Path(sys.argv[1]).expanduser().resolve()
    repo = Path(sys.argv[2]).expanduser().resolve() if len(sys.argv) > 2 else DEFAULT_REPO
    events, count = seed(state_dir, repo)
    print(f"seeded {count} runs into {state_dir}")
    print(f"deployment events in {events}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
