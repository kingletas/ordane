"""The dataset, written in the shapes other stores read.

No client library, no connection, no dependency: a store that wants this is
handed a file, so adding one means writing a loader and nothing else.

    jsonl    the facts, one object per line
    csv      the same, for a spreadsheet or a warehouse
    influx   line protocol, which InfluxDB ingests as it stands
    cypher   MERGE statements, which Neo4j runs as they stand
"""

from __future__ import annotations

import csv
import io
import json
from dataclasses import fields as dataclass_fields

from .dataset import Fact, Graph, Point, facts, graph, series

FORMATS = ("jsonl", "csv", "influx", "cypher")

WHAT_EACH_IS = {
    "jsonl": "one JSON object per run",
    "csv": "one row per run, with a header",
    "influx": "InfluxDB line protocol, one point per measurement",
    "cypher": "Neo4j MERGE statements, safe to run more than once",
}

# Influx tags may not carry these unescaped, and a tag that breaks the line
# takes the whole batch with it.
_TAG_ESCAPES = str.maketrans({",": r"\,", " ": r"\ ", "=": r"\="})


def render(runs: list, kind: str, releases=(), patches=(), plane: str = "") -> str:
    """The whole dataset in one format. Empty input gives empty output, not an error.

    `facts` and `csv` are runs only: a release and a run are not the same row,
    and widening one table until it holds both is how a table stops meaning
    anything. The series and the graph carry all three.
    """
    if kind == "jsonl":
        return as_jsonl(facts(runs))
    if kind == "csv":
        return as_csv(facts(runs))
    if kind == "influx":
        return as_line_protocol(series(runs, releases, patches, plane))
    if kind == "cypher":
        return as_cypher(graph(runs, releases, patches, plane))
    raise ValueError(f"unknown format {kind!r}; one of {', '.join(FORMATS)}")


def as_jsonl(rows: list[Fact]) -> str:
    return "".join(json.dumps(row.as_record(), separators=(",", ":")) + "\n" for row in rows)


def as_csv(rows: list[Fact]) -> str:
    names = [f.name for f in dataclass_fields(Fact)]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=names, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(row.as_record())
    return buffer.getvalue()


def as_line_protocol(points: list[Point]) -> str:
    """`run,plane=x,environment=y duration_s=12.4 1757068800000000000`

    Nanoseconds, because that is what the protocol expects and a store that
    guesses the precision guesses wrong on the first point that matters.
    """
    lines = []
    for point in points:
        tags = ",".join(
            f"{_tag(name)}={_tag(value)}" for name, value in sorted(point.tags.items()) if value
        )
        head = f"{_tag(point.measurement)},{tags}" if tags else _tag(point.measurement)
        stamp = int(point.at.timestamp() * 1_000_000_000)
        lines.append(f"{head} {point.field_name}={point.value} {stamp}")
    return "\n".join(lines) + ("\n" if lines else "")


def as_cypher(model: Graph) -> str:
    """`MERGE` rather than `CREATE`, so loading the same export twice is a no-op."""
    lines = []
    for node in model.nodes:
        lines.append(f"MERGE (n:{node.kind} {{id: {_literal(node.id)}}})" + _sets(node.properties))
    for edge in model.edges:
        # Both labels, not just the ids. An unlabelled `MATCH (a {id: …})`
        # matches every node with that id whatever its type, and MERGE then
        # makes the relationship once per match, so one id shared by two
        # kinds quietly becomes several relationships.
        start_kind, start_id = _split(edge.start)
        end_kind, end_id = _split(edge.end)
        lines.append(
            f"MATCH (a:{start_kind} {{id: {_literal(start_id)}}}), "
            f"(b:{end_kind} {{id: {_literal(end_id)}}}) "
            f"MERGE (a)-[r:{edge.kind}]->(b)" + _sets(edge.properties, "r")
        )
    return "\n".join(lines) + ("\n" if lines else "")


def _sets(properties: dict, alias: str = "n") -> str:
    if not properties:
        return ";"
    assignments = ", ".join(
        f"{alias}.{name} = {_literal(value)}" for name, value in sorted(properties.items())
    )
    return f" SET {assignments};"


def _split(key: str) -> tuple[str, str]:
    """`Run:20260905T…` back into the label and the id it was merged on."""
    kind, _, identifier = key.partition(":")
    return (kind, identifier) if identifier else ("", kind)


def _literal(value) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int | float):
        return str(value)
    return json.dumps(str(value))


def _tag(value: str) -> str:
    return str(value).translate(_TAG_ESCAPES)
