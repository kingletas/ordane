"""The dataset projections, and the shapes they are written in.

One source, three projections. Nothing here connects to anything: a projection
is data, and where it is sent is somebody else's decision.
"""

import csv
import io
import json
from datetime import UTC, datetime

import pytest

from ordane.insight import dataset, export
from ordane.record.store import Run
from ordane.record.summary import parse

RECAP = """
PLAY RECAP *****
web01 : ok=3 changed=2 unreachable=0 failed=0 skipped=0
web02 : ok=1 changed=0 unreachable=0 failed=1 skipped=0
"""


def a_run(**kwargs) -> Run:
    base = dict(
        id="20260905T100000Z-abc123",
        kind="target",
        name="deploy",
        environment="production",
        params={},
        argv=["ansible-playbook", "-i", "inv", "deploy.yml"],
        command="ansible-playbook -i inv deploy.yml",
        actor="ada@thinkpad",
        started="2026-09-05T10:00:00Z",
        finished="2026-09-05T10:02:00Z",
        state="succeeded",
        exit_code=0,
        duration_s=120.5,
        plane="you/control-plane",
        host="thinkpad",
        installation="ab12cd34",
        labels={"deploy": "true", "cutover": "true"},
        summary=parse(RECAP).as_record(),
    )
    return Run(**(base | kwargs))


# --- facts ---


def test_a_fact_carries_everything_needed_to_read_it_without_context():
    one = dataset.fact(a_run())
    assert one.plane == "you/control-plane"
    assert (one.hosts, one.changed, one.failed) == (2, 2, 1)
    assert one.deploy and one.cutover


def test_an_old_record_falls_back_to_its_path_for_the_plane():
    one = dataset.fact(a_run(plane="", repo="/home/you/plane"))
    assert one.plane == "/home/you/plane"


def test_a_dry_run_is_marked_as_one():
    assert dataset.fact(a_run(argv=["ansible-playbook", "p.yml", "--check"])).dry_run


def test_a_run_still_going_is_not_a_fact():
    """A duration that is still growing is not a measurement."""
    assert dataset.facts([a_run(state="running")]) == []


# --- series ---


def test_every_finished_run_produces_the_same_measurements():
    points = dataset.series([a_run()])
    assert {p.field_name for p in points} == {
        "duration_s",
        "hosts",
        "changed",
        "failed",
        "unreachable",
        "succeeded",
    }


def test_a_point_is_tagged_with_where_it_came_from():
    point = dataset.series([a_run()])[0]
    for name in dataset.DIMENSIONS:
        assert name in point.tags
    assert point.tags["outcome"] == "success"


def test_a_failure_is_tagged_as_one():
    point = dataset.series([a_run(exit_code=2, state="failed")])[0]
    assert point.tags["outcome"] == "failure"


def test_a_run_with_an_unreadable_time_is_left_out_rather_than_dated_now():
    assert dataset.series([a_run(finished="not a date", started="not a date")]) == []


# --- graph ---


def test_the_graph_has_one_node_per_thing_and_not_one_per_run():
    model = dataset.graph([a_run(), a_run(id="second")])
    planes = [n for n in model.nodes if n.kind == "ControlPlane"]
    assert len(planes) == 1
    assert len([n for n in model.nodes if n.kind == "Run"]) == 2


def test_the_hosts_a_run_touched_come_from_the_recap():
    """The one relationship that cannot be answered from a row."""
    model = dataset.graph([a_run()])
    touched = [e for e in model.edges if e.kind == "TOUCHED"]
    assert len(touched) == 2
    assert any(e.properties["failed"] == 1 for e in touched)


def test_the_same_environment_name_in_two_planes_is_two_nodes():
    model = dataset.graph([a_run(), a_run(id="b", plane="other/plane")])
    assert len([n for n in model.nodes if n.kind == "Environment"]) == 2


def test_a_run_still_going_is_not_in_the_graph():
    assert dataset.graph([a_run(state="running")]).nodes == []


# --- the shapes ---


def test_jsonl_is_one_object_per_run():
    lines = export.render([a_run()], "jsonl").strip().splitlines()
    assert json.loads(lines[0])["target"] == "deploy"


def test_csv_carries_every_field_as_a_column():
    rows = list(csv.DictReader(io.StringIO(export.render([a_run()], "csv"))))
    assert rows[0]["plane"] == "you/control-plane"
    assert set(rows[0]) == {f for f in dataset.Fact.__dataclass_fields__}


def test_line_protocol_has_a_measurement_tags_a_field_and_nanoseconds():
    line = export.render([a_run()], "influx").splitlines()[0]
    head, field, stamp = line.rsplit(" ", 2)
    assert head.startswith("run,")
    assert "=" in field
    assert len(stamp) == 19, "an Influx timestamp is nanoseconds"


def test_a_tag_with_a_comma_or_a_space_in_it_is_escaped():
    line = export.render([a_run(environment="two words,and")], "influx").splitlines()[0]
    assert r"two\ words\,and" in line


def test_cypher_merges_rather_than_creates_so_it_can_be_run_twice():
    statements = export.render([a_run()], "cypher").splitlines()
    assert all(s.startswith(("MERGE", "MATCH")) for s in statements)
    assert not any("CREATE" in s for s in statements)


def test_a_cypher_relationship_points_at_the_ids_its_nodes_were_merged_on():
    statements = export.render([a_run()], "cypher").splitlines()
    merged = {
        json.loads(s.split("{id: ")[1].split("}")[0]) for s in statements if s.startswith("MERGE")
    }
    for statement in (s for s in statements if s.startswith("MATCH")):
        for part in statement.split("{id: ")[1:3]:
            assert json.loads(part.split("}")[0]) in merged


def test_an_empty_history_produces_empty_output_rather_than_an_error():
    for kind in ("jsonl", "influx", "cypher"):
        assert export.render([], kind) == ""


def test_an_empty_csv_still_has_its_header_because_that_is_a_valid_csv():
    """A file with a header and no rows loads; a file with nothing in it does not."""
    assert export.render([], "csv").strip() == ",".join(dataset.Fact.__dataclass_fields__)


def test_a_format_nobody_offers_is_refused_by_name():
    with pytest.raises(ValueError, match="unknown format"):
        export.render([a_run()], "parquet")


def test_every_format_says_what_it_is():
    assert set(export.WHAT_EACH_IS) == set(export.FORMATS)


def test_a_moment_without_a_zone_is_read_as_utc():
    assert dataset._moment("2026-09-05T10:00:00") == datetime(2026, 9, 5, 10, 0, tzinfo=UTC)


# --- the invariant a graph store enforces silently, so this enforces it loudly ---


def endpoints_exist(model: dataset.Graph) -> list:
    ids = {f"{n.kind}:{n.id}" for n in model.nodes}
    return [e for e in model.edges if e.start not in ids or e.end not in ids]


def test_every_edge_points_at_a_node_that_exists():
    assert endpoints_exist(dataset.graph([a_run()])) == []


def test_a_run_with_nothing_filled_in_still_produces_a_whole_graph():
    """The first real export lost 14 of 54 relationships this way: a record with
    no control plane made edges point at a node nothing had created, and the
    store dropped them on load without a word."""
    bare = a_run(plane="", repo="", host="", actor="", environment="", name="")
    model = dataset.graph([bare])
    assert endpoints_exist(model) == []
    assert any(n.id == dataset.UNATTRIBUTED for n in model.nodes)


def test_an_unattributed_run_is_visible_rather_than_absent():
    model = dataset.graph([a_run(plane="", repo="")])
    planes = [n for n in model.nodes if n.kind == "ControlPlane"]
    assert [p.id for p in planes] == [dataset.UNATTRIBUTED]


# --- which host made the artefact, which no environment name answers ---


def test_a_run_carries_its_builder_into_every_shape():
    run = a_run(builder="stage-builder")
    assert dataset.fact(run).builder == "stage-builder"
    tagged = [p for p in dataset.series([run]) if p.tags.get("builder") == "stage-builder"]
    assert tagged


def test_the_graph_points_a_run_at_the_host_that_built_it():
    model = dataset.graph([a_run(builder="stage-builder")])
    built = [e for e in model.edges if e.kind == "BUILT_ON"]
    assert len(built) == 1
    assert built[0].end == "Host:stage-builder"
    assert "Host:stage-builder" in {f"{n.kind}:{n.id}" for n in model.nodes}


def test_a_run_with_no_builder_recorded_gets_no_edge_rather_than_an_empty_one():
    """An edge to nothing is what a graph store silently drops on load."""
    assert not [e for e in dataset.graph([a_run()]).edges if e.kind == "BUILT_ON"]


# --- the steps of one launch, which the clock used to be the only link between ---


def _launch(sequence: str) -> list[Run]:
    return [
        a_run(id="r1", kind="checks", name="checks", sequence=sequence),
        a_run(id="r2", kind="precheck", name="check", sequence=sequence),
        a_run(id="r3", kind="target", name="deploy", sequence=sequence),
        a_run(id="r4", kind="postcheck", name="verify", sequence=sequence),
    ]


def test_every_step_points_at_the_operation_it_ran_around():
    model = dataset.graph(_launch("s1"))
    steps = [(e.start, e.end, e.properties["kind"]) for e in model.edges if e.kind == "STEP_OF"]
    assert sorted(steps) == [
        ("Run:r1", "Run:r3", "checks"),
        ("Run:r2", "Run:r3", "precheck"),
        ("Run:r4", "Run:r3", "postcheck"),
    ]


def test_the_operation_does_not_point_at_itself():
    model = dataset.graph(_launch("s1"))
    assert not [e for e in model.edges if e.kind == "STEP_OF" and e.start == e.end]


def test_a_run_that_stood_alone_is_a_step_of_nothing():
    assert not [e for e in dataset.graph([a_run()]).edges if e.kind == "STEP_OF"]


def test_two_launches_do_not_cross():
    model = dataset.graph(_launch("s1") + [a_run(id="x1", kind="checks", sequence="s2")])
    crossed = [e for e in model.edges if e.kind == "STEP_OF" and e.start == "Run:x1"]
    assert crossed == []


def test_a_launch_whose_operation_is_missing_links_nothing_rather_than_guessing():
    """A partial history must not invent a centre for steps that have none."""
    partial = [one for one in _launch("s1") if one.kind != "target"]
    assert not [e for e in dataset.graph(partial).edges if e.kind == "STEP_OF"]


def test_the_sequence_is_on_the_flat_row_too():
    assert dataset.fact(a_run(sequence="s1")).sequence == "s1"
