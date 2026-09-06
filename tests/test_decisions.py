"""What somebody changed, which the run history has never held.

A ref switch can widen the list of environments this console will launch
against. It was reported at the time and written down nowhere, so the next
person saw a control plane that allowed production and no history of how.
"""

import json

from ordane.record import decisions


def _store(tmp_path):
    return decisions.DecisionStore(tmp_path)


def test_a_switch_that_widened_the_gate_is_written_down(tmp_path):
    store = _store(tmp_path)
    store.record(
        kind=decisions.REF,
        plane="a/plane",
        summary="Switched to release, which allows production",
        detail={"ref": "release", "widened": ["production"]},
    )
    taken = store.all()
    assert len(taken) == 1
    assert taken[0].kind == "ref"
    assert taken[0].widened == ["production"]
    assert taken[0].actor and taken[0].host


def test_newest_first_so_the_last_change_is_the_first_thing_read(tmp_path):
    store = _store(tmp_path)
    for at, summary in (("2026-01-01T00:00:00Z", "older"), ("2026-06-01T00:00:00Z", "newer")):
        line = decisions.Decision(
            at=at, kind="ref", actor="t", plane="a/plane", summary=summary
        ).as_record()
        with (tmp_path / decisions.FILE_NAME).open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(line) + "\n")
    assert [one.summary for one in store.all()] == ["newer", "older"]


def test_one_control_plane_does_not_see_another_s_decisions(tmp_path):
    store = _store(tmp_path)
    store.record(kind=decisions.REF, plane="mine", summary="mine")
    store.record(kind=decisions.REF, plane="theirs", summary="theirs")
    assert [one.summary for one in store.all("mine")] == ["mine"]


def test_a_kind_nobody_declared_is_filed_rather_than_refused(tmp_path):
    store = _store(tmp_path)
    store.record(kind="something-else", plane="a/plane", summary="x")
    assert store.all()[0].kind in decisions.KINDS


def test_a_line_that_will_not_parse_is_skipped_rather_than_losing_the_rest(tmp_path):
    store = _store(tmp_path)
    store.record(kind=decisions.REF, plane="a/plane", summary="kept")
    with (tmp_path / decisions.FILE_NAME).open("a", encoding="utf-8") as handle:
        handle.write("{ not json\n")
    assert [one.summary for one in store.all()] == ["kept"]


def test_reading_a_history_that_does_not_exist_is_empty_rather_than_an_error(tmp_path):
    assert _store(tmp_path / "nothing-here").all() == []


def test_instrumentation_never_blocks_the_decision_it_records(tmp_path):
    """A read-only state directory must not stop somebody switching a ref."""
    unwritable = tmp_path / "runs.jsonl"
    unwritable.write_text("", encoding="utf-8")
    store = decisions.DecisionStore(unwritable)
    store.record(kind=decisions.REF, plane="a/plane", summary="x")
    assert store.all() == []
