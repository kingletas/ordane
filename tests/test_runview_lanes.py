"""The lane chart is redrawn only when the shape of the run changes.

A live run asks the view to refresh once a second. Rebuilding the block for
that appended a second copy of it every tick, so a run watched for twenty
seconds carried twenty stacked copies of its own hosts — and the card grew
until the output pane was drawn on top of the recap above it.
"""

from __future__ import annotations

import pytest

gi = pytest.importorskip("gi")
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")

from gi.repository import Adw, Gtk  # noqa: E402

from ordane.record import lanes as lanes_module  # noqa: E402
from ordane.record.store import Run  # noqa: E402

# Two tasks, because one column is a list of outcomes rather than a shape and
# is deliberately not drawn.
FIRST = """
PLAY [production] ****

TASK [Gathering Facts] ****
ok: [web-01]
ok: [web-02]

TASK [Fetch the release] ****
ok: [web-01]
ok: [web-02]
"""

SECOND = (
    FIRST
    + """
TASK [Sync files] ****
changed: [web-01]
"""
)

ONE_TASK = """
PLAY [production] ****

TASK [Gathering Facts] ****
ok: [web-01]
ok: [web-02]
"""

ASKED = """shop-m2-prod-admin | SUCCESS => {"ping": "pong"}
shop-m2-prod-cron | SUCCESS => {"ping": "pong"}
shop-m2-stage-builder | UNREACHABLE! => {"unreachable": true}
"""


def a_run(state: str = "running") -> Run:
    return Run(
        id="r1",
        kind="target",
        name="deploy",
        environment="production",
        params={},
        argv=["make", "deploy"],
        command="make deploy",
        actor="ada",
        started="2026-09-08T16:05:00Z",
        state=state,
    )


def a_view():
    Adw.init()
    from ordane.desktop.runview import RunView

    return RunView(lambda _id: None)


def children(widget: Gtk.Widget) -> list:
    found = []
    child = widget.get_first_child()
    while child is not None:
        found.append(child)
        child = child.get_next_sibling()
    return found


def test_refreshing_an_unchanged_run_does_not_stack_a_second_chart():
    view = a_view()
    view.show(a_run(), FIRST)
    assert len(children(view._lanes)) == 1

    for _ in range(20):
        view._fill_lanes(view._run)
    assert len(children(view._lanes)) == 1, "the chart was appended once a tick"


def test_a_new_task_redraws_the_chart_rather_than_adding_one():
    view = a_view()
    view.show(a_run(), FIRST)
    assert len(view._lane_cells) == 2
    assert len(view._lane_shape[1]) == 2

    view._buffer.set_text(SECOND)
    view._fill_lanes(view._run)
    assert len(children(view._lanes)) == 1
    assert len(view._lane_shape[1]) == 3, "the third task never reached the chart"


def test_a_cell_that_lands_is_updated_in_place():
    view = a_view()
    view.show(a_run(), FIRST)
    before = dict(view._lane_cells)

    view._buffer.set_text(SECOND)
    view._fill_lanes(view._run)
    assert view._lane_cells["web-01"] is not before["web-01"], "the shape changed"

    kept = dict(view._lane_cells)
    view._buffer.set_text(SECOND + "changed: [web-02]\n")
    view._fill_lanes(view._run)
    assert view._lane_cells["web-02"] is kept["web-02"], "the same shape was rebuilt"
    assert view._lane_cells["web-02"]._states[-1] == lanes_module.CHANGED


def test_a_tick_that_reads_no_new_output_does_no_work():
    view = a_view()
    view.show(a_run(), FIRST)
    marker = view._lane_cells["web-01"]
    for _ in range(5):
        view._fill_lanes(view._run)
    assert view._lane_cells["web-01"] is marker


def test_showing_a_second_run_does_not_inherit_the_first_one_s_chart():
    view = a_view()
    view.show(a_run(), FIRST)
    assert view._lane_cells

    view.show(a_run(state="succeeded"), "")
    assert not view._lane_cells
    assert children(view._lanes) == []


def test_a_run_with_nothing_to_draw_hides_the_chart_rather_than_showing_an_empty_one():
    view = a_view()
    view.show(a_run(state="succeeded"), "it printed no recap and no tasks\n")
    assert not view._lanes.get_visible()


def test_a_run_of_one_task_draws_no_chart_at_all():
    """One column is a full-width bar per host carrying one bit each, which is
    what the outcome pill above it already says."""
    view = a_view()
    view.show(a_run(state="succeeded"), ONE_TASK)
    assert not view._lanes.get_visible()
    assert not view._lane_cells


def test_a_question_asked_of_a_host_group_draws_no_chart_either():
    """`ansible -m ping` prints one answer per host and no task headers, so the
    grid it makes is one column wide."""
    view = a_view()
    view.show(a_run(state="failed"), ASKED)
    assert not view._lanes.get_visible()


def test_every_host_name_occupies_the_same_column():
    """A pixel minimum is only a floor: a longer name simply took more than it,
    and every bar then started somewhere different."""
    view = a_view()
    view.show(a_run(), FIRST.replace("web-02", "web-02.a-very-long-name.example"))
    widths = {
        cell.get_parent().get_first_child().get_width_chars() for cell in view._lane_cells.values()
    }
    assert len(widths) == 1, f"the host column is not one width: {widths}"
