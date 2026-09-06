"""The questions the shared stores answer that the local history cannot.

Each of these needs something the console does not have on disk: years that
predate it, or a path through the graph. **A panel that could be answered from
`runs.jsonl` does not belong here**: it would be a slower copy of the Health
view with a network dependency attached.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

FROM_INFLUX = "influx"
FROM_NEO4J = "neo4j"


@dataclass(frozen=True)
class Panel:
    """One question, the query that answers it, and how to read the answer."""

    key: str
    title: str
    why: str
    store: str
    query: str
    columns: tuple[tuple[str, str], ...]
    # A bar chart is drawn from these two columns where both are given.
    chart: tuple[str, str] | None = None


def bucket(name: str) -> str:
    return name.replace('"', "")


def panels(bucket_name: str = "runs") -> list[Panel]:
    """Five, and each one is here because nothing local can answer it."""
    inside = bucket(bucket_name)
    return [
        Panel(
            key="cadence",
            title="Releases a year",
            why="The run history starts when this console did. The release log goes back to 2020.",
            store=FROM_INFLUX,
            query=f'''from(bucket: "{inside}")
  |> range(start: 2020-01-01T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "release" and r._field == "released")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: 1y, fn: sum, timeSrc: "_start", createEmpty: false)
  |> keep(columns: ["_time", "_value"])''',
            columns=(("_time", "Year"), ("_value", "Releases")),
            chart=("_time", "_value"),
        ),
        Panel(
            key="lead_time",
            title="Lead time, a year at a time",
            why="Median days from a change being built to it reaching production.",
            store=FROM_INFLUX,
            query=f'''from(bucket: "{inside}")
  |> range(start: 2020-01-01T00:00:00Z)
  |> filter(fn: (r) => r._measurement == "release" and r._field == "lead_time_days")
  |> group()
  |> sort(columns: ["_time"])
  |> aggregateWindow(every: 1y, fn: median, timeSrc: "_start", createEmpty: false)
  |> keep(columns: ["_time", "_value"])''',
            columns=(("_time", "Year"), ("_value", "Days")),
            chart=("_time", "_value"),
        ),
        Panel(
            key="platform",
            title="What shipped between platform upgrades",
            why="A path through the release chain. No table has a path in it.",
            store=FROM_NEO4J,
            query="""MATCH (new:Release)-[a:ON]->(np:Platform), (old:Release)-[b:ON]->(op:Platform)
MATCH path = (new)-[:FOLLOWS*1..60]->(old)
WHERE a.upgrade AND b.upgrade AND new.at > old.at
WITH new, old, np, op, min(length(path)) AS between
ORDER BY new.at DESC
RETURN op.id + " to " + np.id AS platform,
       old.name + " to " + new.name AS releases,
       between AS releases_between
LIMIT 8""",
            columns=(
                ("platform", "Platform"),
                ("releases", "Releases"),
                ("releases_between", "In between"),
            ),
        ),
        Panel(
            key="hosts",
            title="Hosts that failed under a run",
            why="Which hosts a run reached comes out of the recap, so no row carries it.",
            store=FROM_NEO4J,
            query="""MATCH (a:Actor)-[:RAN]->(r:Run)-[t:TOUCHED]->(h:Host)
WHERE t.failed > 0
RETURN h.id AS host, count(r) AS runs, a.id AS who
ORDER BY runs DESC
LIMIT 8""",
            columns=(("host", "Host"), ("runs", "Runs"), ("who", "Run by")),
        ),
        Panel(
            key="builders",
            title="What went out through each builder",
            why="One builder can package releases for several environments, and for "
            "control planes this machine has never driven.",
            store=FROM_NEO4J,
            query="""MATCH (r:Run)-[:BUILT_ON]->(h:Host)
OPTIONAL MATCH (r)-[:AGAINST]->(e:Environment)
RETURN h.id AS builder,
       count(DISTINCT r) AS runs,
       count(DISTINCT e.id) AS environments
ORDER BY runs DESC
LIMIT 8""",
            columns=(
                ("builder", "Builder"),
                ("runs", "Runs"),
                ("environments", "Environments"),
            ),
        ),
        Panel(
            key="patches",
            title="What is patched, and how much of it anybody watched",
            why="A ledger seeded from disk is a claim about the past, not a record of one.",
            store=FROM_NEO4J,
            query="""MATCH (p:Patch)-[a:APPLIED_TO]->(e:Environment)
RETURN e.name AS environment,
       count(p) AS patches,
       sum(CASE WHEN a.assumed THEN 1 ELSE 0 END) AS assumed,
       sum(CASE WHEN a.assumed THEN 0 ELSE 1 END) AS observed
ORDER BY patches DESC""",
            columns=(
                ("environment", "Environment"),
                ("patches", "Applied"),
                ("assumed", "Assumed"),
                ("observed", "Observed"),
            ),
        ),
    ]


@dataclass
class Result:
    panel: Panel
    rows: list[dict] = field(default_factory=list)
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error

    @property
    def empty(self) -> bool:
        return self.ok and not self.rows


def ask(stores, one: Panel) -> Result:
    """One panel, answered or explained. Never raises into a view."""
    answer = stores.flux(one.query) if one.store == FROM_INFLUX else stores.cypher(one.query)
    return Result(panel=one, rows=answer.rows, error=answer.error)


def ask_all(stores, bucket_name: str = "runs") -> list[Result]:
    return [ask(stores, one) for one in panels(bucket_name)]


# --- reading a yearly series ---

# Below this much of the current year, a projection from it is arithmetic
# rather than a forecast, so none is offered.
PACE_FLOOR = 0.25


@dataclass(frozen=True)
class Point:
    """One year of a series, and whether that year has finished."""

    year: int
    value: float
    partial: bool


def year_of(stamp) -> int | None:
    """The calendar year an InfluxDB stamp falls in, or None when it is unreadable."""
    text = str(stamp or "")
    head = text[:4]
    return int(head) if head.isdigit() else None


def series(result, today: date | None = None) -> list[Point]:
    """A charted panel's rows as years, with the running year marked partial."""
    if result is None or not result.ok or result.panel.chart is None:
        return []
    now = today or date.today()
    label_column, value_column = result.panel.chart
    points = []
    for row in result.rows:
        year = year_of(row.get(label_column))
        if year is None:
            continue
        try:
            value = float(row.get(value_column))
        except (TypeError, ValueError):
            continue
        points.append(Point(year=year, value=value, partial=year >= now.year))
    return sorted(points, key=lambda one: one.year)


def elapsed(today: date | None = None) -> float:
    """How much of the current year has gone, as a fraction."""
    now = today or date.today()
    start = date(now.year, 1, 1)
    end = date(now.year + 1, 1, 1)
    return (now - start).days / (end - start).days


# --- the figures above the charts ---


@dataclass(frozen=True)
class Figure:
    """One headline number, with the sentence that gives it a size."""

    kicker: str
    value: str
    unit: str = ""
    detail: str = ""
    tint: str = ""


def _trim(value: float) -> str:
    return f"{value:g}"


def _cadence_figures(points: list[Point], today: date | None) -> list[Figure]:
    if not points:
        return []
    closed = [one for one in points if not one.partial]
    latest = points[-1]
    figures = []

    if latest.partial:
        detail = ""
        if closed:
            previous = closed[-1]
            detail = f"{_trim(previous.value)} in all of {previous.year}"
        gone = elapsed(today)
        if gone >= PACE_FLOOR:
            pace = round(latest.value / gone)
            detail = f"{detail} · on pace for {pace}" if detail else f"On pace for {pace}"
        figures.append(
            Figure(
                kicker=f"RELEASES IN {latest.year}",
                value=_trim(latest.value),
                detail=detail,
            )
        )
    else:
        figures.append(
            Figure(
                kicker=f"RELEASES IN {latest.year}",
                value=_trim(latest.value),
                detail="The year is complete.",
            )
        )

    total = sum(one.value for one in points)
    figures.append(
        Figure(
            kicker="RELEASES ON RECORD",
            value=_trim(total),
            detail=f"{points[0].year} to {points[-1].year}, before this console existed",
        )
    )

    return figures


def _lead_time_figure(points: list[Point]) -> list[Figure]:
    if not points:
        return []
    latest = points[-1]
    detail = f"{latest.year} to date"
    tint = ""
    closed = [one for one in points if not one.partial]
    if closed and closed[-1].year != latest.year:
        previous = closed[-1]
        detail = f"{latest.year} to date · {_trim(round(previous.value, 1))} d in {previous.year}"
        # A lead time that rose is worse news, which is what the tint says.
        if latest.value > previous.value:
            tint = "warn"
    return [
        Figure(
            kicker="MEDIAN LEAD TIME",
            value=_trim(round(latest.value, 1)),
            unit="d",
            detail=detail,
            tint=tint,
        )
    ]


def headline(results, today: date | None = None) -> list[Figure]:
    """The figures a store answered for; a store that did not answer adds none."""
    by_key = {one.panel.key: one for one in results}
    cadence = series(by_key.get("cadence"), today)
    lead = series(by_key.get("lead_time"), today)
    return _cadence_figures(cadence, today) + _lead_time_figure(lead)
