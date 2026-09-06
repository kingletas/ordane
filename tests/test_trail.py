"""The back and forward the mouse's side buttons drive."""

from ordane.desktop.trail import DEPTH, Trail


def _walked(*pages: str) -> Trail:
    trail = Trail()
    for page in pages:
        trail.visit(page)
    return trail


def test_a_fresh_window_has_nowhere_to_go():
    trail = Trail()
    assert not trail.can_go_back
    assert not trail.can_go_forward
    assert trail.back() is None


def test_one_page_is_not_somewhere_to_come_back_from():
    assert not _walked("dashboard").can_go_back


def test_back_returns_the_page_before_this_one():
    trail = _walked("dashboard", "actions", "runs")
    assert trail.back() == "actions"
    assert trail.back() == "dashboard"
    assert trail.back() is None


def test_forward_only_exists_after_going_back():
    trail = _walked("dashboard", "actions")
    assert not trail.can_go_forward
    trail.back()
    assert trail.forward() == "actions"


def test_visiting_from_the_middle_drops_what_was_ahead():
    """The same rule a browser has: a new page ends the future you had."""
    trail = _walked("dashboard", "actions", "runs")
    trail.back()
    trail.visit("estate")
    assert trail.pages == ["dashboard", "actions", "estate"]
    assert not trail.can_go_forward


def test_the_same_page_twice_is_one_visit():
    assert _walked("runs", "runs", "runs").pages == ["runs"]


def test_stepping_back_and_forward_does_not_record_the_step():
    trail = _walked("dashboard", "actions")
    trail.back()
    trail.forward()
    assert trail.pages == ["dashboard", "actions"]


def test_an_empty_page_name_is_not_a_page():
    assert _walked("dashboard", "").pages == ["dashboard"]


def test_the_trail_stays_a_list_rather_than_a_history_file():
    trail = Trail()
    for index in range(DEPTH + 20):
        trail.visit(f"page-{index}")
    assert len(trail.pages) == DEPTH
    assert trail.pages[-1] == f"page-{DEPTH + 19}"
