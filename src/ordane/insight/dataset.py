"""One record, projected into the shapes a shared store can read.

The run history is already an append-only event log: which is the one shape
that replicates. So this adds no second store to disagree with the first: it
reads what happened and projects it three ways.

    facts    one flat row per run, for a table or a warehouse
    series   one point per measurement, for a time-series store
    graph    nodes and edges, for a graph store

Nothing here connects to anything. A projection is data; where it is sent is
somebody else's decision, and making it one is what stops this becoming a
service that has to be running for the console to work.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from ..record.store import Run

# The dimensions every projection carries. A measurement without them cannot be
# read back by anyone who did not already know where it came from.
# `host` is the machine a run was launched from; `builder` is the one the
# artefact was made on, and they are almost never the same.
DIMENSIONS = ("plane", "environment", "target", "actor", "host", "builder", "kind", "state")

# What a thing with no name is called. An empty id produced a node nothing
# created and edges pointing at it, which a graph store then silently dropped
# on load: 14 of 54 relationships, in the first real export. A gap has to be
# visible to be a gap.
UNATTRIBUTED = "(unattributed)"

# What a graph is made of here. Deliberately few: a schema with a node type
# nobody queries is a schema somebody has to keep true for no reason.
NODE_TYPES = (
    "ControlPlane",
    "Environment",
    "Target",
    "Actor",
    "Host",
    "Run",
    "Release",
    "Patch",
    "Platform",
)


@dataclass(frozen=True)
class Fact:
    """One run, flattened. Everything a row needs to mean something on its own."""

    run_id: str
    occurred_at: str
    plane: str
    environment: str
    target: str
    actor: str
    host: str
    installation: str
    kind: str
    state: str
    builder: str
    sequence: str
    exit_code: int | None
    duration_s: float
    hosts: int
    changed: int
    failed: int
    unreachable: int
    deploy: bool
    cutover: bool
    dry_run: bool

    def as_record(self) -> dict:
        return dict(self.__dict__)


@dataclass(frozen=True)
class Point:
    """One measurement at one moment, tagged with where it came from."""

    measurement: str
    field_name: str
    value: float
    at: datetime
    tags: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class Node:
    kind: str
    id: str
    properties: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Edge:
    kind: str
    start: str
    end: str
    properties: dict = field(default_factory=dict)


@dataclass(frozen=True)
class Graph:
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


def fact(run: Run) -> Fact:
    """One run as a row, with the recap flattened into it."""
    result = run.result
    return Fact(
        run_id=run.id,
        occurred_at=run.finished or run.started,
        plane=run.plane or run.repo,
        environment=run.environment,
        target=run.name,
        actor=run.actor,
        host=run.host,
        installation=run.installation,
        kind=run.kind,
        state=run.state,
        builder=run.builder,
        sequence=run.sequence,
        exit_code=run.exit_code,
        duration_s=run.duration_s,
        hosts=len(result.hosts),
        changed=result.changed,
        failed=result.failed,
        unreachable=sum(h.unreachable for h in result.hosts),
        deploy=run.labels.get("deploy") == "true",
        cutover=run.labels.get("cutover") == "true",
        dry_run="--check" in run.argv or "EXTRA=--check" in run.argv,
    )


def facts(runs: list[Run]) -> list[Fact]:
    return [fact(run) for run in runs if run.state != "running"]


def release_points(releases, plane: str) -> list[Point]:
    """Years of cutovers this console never launched, as points.

    The run history starts when the console did. The release log goes back to
    2020, and a delivery measure that ignores it is measuring the tool rather
    than the estate.
    """
    points: list[Point] = []
    for release in releases:
        at = _moment(release.at)
        if at is None:
            continue
        tags = {
            "plane": plane,
            "environment": release.environment,
            "release": release.name,
            "platform": release.platform,
            "actor": release.actor,
            "outcome": release.outcome or ("success" if release.succeeded else ""),
        }
        measures = [
            ("released", 1.0),
            ("succeeded", 1.0 if release.succeeded else 0.0),
            ("rollback", 1.0 if release.is_rollback else 0.0),
            ("platform_upgrade", 1.0 if release.platform_upgrade else 0.0),
            ("commit_count", float(release.commit_count)),
        ]
        if release.lead_time_days is not None:
            measures.append(("lead_time_days", float(release.lead_time_days)))
        points += [Point("release", name, value, at, tags) for name, value in measures]
    return points


def patch_points(events, plane: str) -> list[Point]:
    """Every recorded change to what is patched where."""
    points: list[Point] = []
    for event in events:
        at = _moment(event.at)
        if at is None:
            continue
        tags = {
            "plane": plane,
            "environment": event.environment,
            "patch": event.patch,
            "state": event.state,
            "actor": event.actor,
            # A seeded ledger entry is a claim about the past rather than a
            # record of one, and anything counting must be able to exclude it.
            "assumed": "true" if event.assumed else "false",
        }
        points.append(Point("patch", "applied", 1.0 if event.applied else 0.0, at, tags))
        if event.hosts_total:
            points.append(Point("patch", "hosts", float(event.hosts_total), at, tags))
    return points


def series(runs: list[Run], releases=(), patches=(), plane: str = "") -> list[Point]:
    """Every number a finished run produced, as points.

    Only finished runs: a duration that is still growing is not a measurement,
    and a store that receives one has to be told to forget it later.
    """
    points: list[Point] = []
    for one in facts(runs):
        at = _moment(one.occurred_at)
        if at is None:
            continue
        tags = {name: getattr(one, name) or "" for name in DIMENSIONS}
        tags["outcome"] = "success" if one.exit_code == 0 else "failure"
        for name, value in (
            ("duration_s", one.duration_s),
            ("hosts", one.hosts),
            ("changed", one.changed),
            ("failed", one.failed),
            ("unreachable", one.unreachable),
            ("succeeded", 1.0 if one.exit_code == 0 else 0.0),
        ):
            points.append(Point("run", name, float(value), at, tags))
    points += release_points(releases, plane)
    points += patch_points(patches, plane)
    return points


def graph(runs: list[Run], releases=(), patches=(), plane: str = "") -> Graph:
    """What ran, where, by whom and on which hosts: as things and relationships.

    The edge worth having is `TOUCHED`: it is the only one that cannot be
    answered from a row, because the hosts a run reached come out of the recap
    rather than out of what was launched.
    """
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []

    def remember(kind: str, identifier: str, properties: dict | None = None) -> str:
        """A node, always. Every edge this returns a key for has somewhere to point."""
        identifier = identifier.strip() or UNATTRIBUTED
        key = f"{kind}:{identifier}"
        if key not in nodes:
            nodes[key] = Node(kind=kind, id=identifier, properties=properties or {})
        return key

    for run in runs:
        if run.state == "running":
            continue
        one = fact(run)
        plane = remember("ControlPlane", one.plane)
        environment = remember(
            "Environment", f"{one.plane}/{one.environment}", {"name": one.environment}
        )
        target = remember("Target", f"{one.plane}/{one.target}", {"name": one.target})
        actor = remember("Actor", one.actor)
        machine = remember("Host", one.host)
        this_run = remember(
            "Run",
            one.run_id,
            {
                "state": one.state,
                "at": one.occurred_at,
                "duration_s": one.duration_s,
                "exit_code": one.exit_code,
            },
        )

        edges.append(Edge("BELONGS_TO", environment, plane))
        edges.append(Edge("BELONGS_TO", target, plane))
        edges.append(Edge("RAN", actor, this_run))
        edges.append(Edge("OF", this_run, target))
        edges.append(Edge("AGAINST", this_run, environment))
        edges.append(Edge("FROM", this_run, machine))
        if run.builder:
            # Which host made the artefact, which the environment does not say:
            # one builder can package releases for several environments.
            built = remember("Host", run.builder)
            edges.append(Edge("BUILT_ON", this_run, built))
        for host in run.result.hosts:
            reached = remember("Host", host.host)
            edges.append(
                Edge(
                    "TOUCHED",
                    this_run,
                    reached,
                    {"changed": host.changed, "failed": host.failed + host.unreachable},
                )
            )

    _add_steps(runs, nodes, edges)
    _add_releases(remember, edges, releases, plane)
    _add_patches(remember, edges, patches, plane)
    return Graph(nodes=list(nodes.values()), edges=edges)


def _add_steps(runs: list[Run], nodes: dict, edges: list) -> None:
    """Points every step of a launch at the operation it ran around.

    A runbook writes four records: its checks, its precheck, the operation and its
    postcheck. The operation is what anybody looks for, so the others point at it,
    which makes what was checked before this deploy one hop rather than a guess from
    the clock.
    """
    operations = {one.sequence: one.id for one in runs if one.sequence and one.kind == "target"}
    for run in runs:
        centre = operations.get(run.sequence)
        if not centre or centre == run.id:
            continue
        start, end = f"Run:{run.id}", f"Run:{centre}"
        if start in nodes and end in nodes:
            edges.append(Edge("STEP_OF", start, end, {"kind": run.kind}))


def _add_releases(remember, edges: list, releases, plane: str) -> None:  # noqa: C901
    """The chain of what shipped, which is the graph the release log already is.

    `FOLLOWS` is the one edge here worth traversing: *what came between these
    two releases* is a path, and no table answers it.
    """
    # `previous_release` names a release; two releases can share a name, so the
    # chain is resolved through the key each one is actually stored under.
    previous_keys: dict[tuple[str, str], str] = {}
    for release in releases:
        where = plane or release.environment
        previous_keys.setdefault((where, release.name), f"{where}/{release.identity}")
        previous_keys[(where, release.identity)] = f"{where}/{release.identity}"

    for release in releases:
        where = plane or release.environment
        control = remember("ControlPlane", where if plane else UNATTRIBUTED)
        environment = remember(
            "Environment", f"{where}/{release.environment}", {"name": release.environment}
        )
        this = remember(
            "Release",
            f"{where}/{release.identity}",
            {
                "name": release.name,
                "at": release.at,
                "outcome": release.outcome,
                "commit_count": release.commit_count,
                "rollback": release.is_rollback,
            },
        )
        edges.append(Edge("BELONGS_TO", environment, control))
        edges.append(Edge("TO", this, environment))
        earlier = previous_keys.get((where, release.previous))
        if earlier:
            edges.append(Edge("FOLLOWS", this, remember("Release", earlier)))
        if release.platform:
            edges.append(
                Edge(
                    "ON",
                    this,
                    remember("Platform", release.platform),
                    {"upgrade": release.platform_upgrade},
                )
            )
        if release.actor:
            edges.append(Edge("RELEASED", remember("Actor", release.actor), this))


def _add_patches(remember, edges: list, events, plane: str) -> None:
    """What is patched where, and when it changed."""
    for event in events:
        where = plane or event.environment
        environment = remember(
            "Environment", f"{where}/{event.environment}", {"name": event.environment}
        )
        patch = remember("Patch", event.patch)
        edges.append(
            Edge(
                "APPLIED_TO" if event.applied else "REMOVED_FROM",
                patch,
                environment,
                {"at": event.at, "assumed": event.assumed, "by": event.actor},
            )
        )


def _moment(stamp: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)
