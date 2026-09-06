"""The Estate view's arithmetic, and the labelling defect that made it lie.

Every year on the two charts was drawn one year late: `aggregateWindow` stamps
a window with the instant it ended, so the bucket covering 2025 arrived called
`2026-01-01`. The first test here is the one that would have caught it.
"""

from datetime import date

from ordane.insight import estate
from ordane.presentation import scale


def _panels():
    return {one.key: one for one in estate.panels("runs")}


def _result(key: str, rows, error: str = ""):
    return estate.Result(panel=_panels()[key], rows=rows, error=error)


def _years(pairs):
    return [{"_time": f"{year}-01-01T00:00:00Z", "_value": str(value)} for year, value in pairs]


# --- the query itself ---


def test_both_yearly_windows_are_labelled_by_the_year_they_cover():
    for key in ("cadence", "lead_time"):
        query = _panels()[key].query
        assert 'timeSrc: "_start"' in query, f"{key} would label 2025 as 2026"


def test_the_range_starts_on_a_year_boundary():
    """A window that starts mid-year buckets two calendar years into one bar."""
    for key in ("cadence", "lead_time"):
        assert "range(start: 2020-01-01T00:00:00Z)" in _panels()[key].query


# --- reading a series ---


def test_a_series_reads_years_and_marks_the_running_one():
    points = estate.series(
        _result("cadence", _years([(2024, 12), (2025, 15), (2026, 8)])),
        today=date(2026, 9, 5),
    )
    assert [one.year for one in points] == [2024, 2025, 2026]
    assert [one.partial for one in points] == [False, False, True]


def test_an_unreadable_stamp_is_left_out_rather_than_dated_zero():
    points = estate.series(
        _result("cadence", [{"_time": "not a date", "_value": "3"}] + _years([(2025, 15)])),
        today=date(2026, 9, 5),
    )
    assert [one.year for one in points] == [2025]


def test_a_panel_that_did_not_answer_has_no_series():
    assert estate.series(_result("cadence", [], error="no route to host")) == []


# --- the figures above the charts ---


def test_the_headline_sizes_the_year_against_the_last_full_one():
    figures = estate.headline(
        [_result("cadence", _years([(2025, 15), (2026, 8)]))],
        today=date(2026, 9, 5),
    )
    releases = figures[0]
    assert releases.kicker == "RELEASES IN 2026"
    assert releases.value == "8"
    assert "15 in all of 2025" in releases.detail
    # 8 releases by 5 September is a pace of about 12 for the year.
    assert "on pace for 12" in releases.detail


def test_no_pace_is_offered_from_a_few_weeks_of_a_year():
    figures = estate.headline(
        [_result("cadence", _years([(2025, 15), (2026, 1)]))],
        today=date(2026, 2, 1),
    )
    assert "on pace" not in figures[0].detail


def test_the_record_counts_the_whole_series():
    figures = estate.headline(
        [_result("cadence", _years([(2024, 12), (2025, 15), (2026, 8)]))],
        today=date(2026, 9, 5),
    )
    by_kicker = {one.kicker: one for one in figures}
    assert by_kicker["RELEASES ON RECORD"].value == "35"
    assert "2024 to 2026" in by_kicker["RELEASES ON RECORD"].detail


def test_the_strip_stays_short_enough_to_read_in_one_line():
    """Three figures, not a wall of them: a strip nobody reads is not a summary."""
    figures = estate.headline(
        [
            _result("cadence", _years([(2025, 15), (2026, 8)])),
            _result("lead_time", _years([(2025, 7.3), (2026, 9.3)])),
        ],
        today=date(2026, 9, 5),
    )
    assert len(figures) == 3


def test_a_lead_time_that_rose_is_the_one_that_gets_the_tint():
    rose = estate.headline(
        [_result("lead_time", _years([(2025, 7.3), (2026, 9.28)]))],
        today=date(2026, 9, 5),
    )
    assert rose[0].value == "9.3"
    assert "7.3 d in 2025" in rose[0].detail
    assert rose[0].unit == "d"
    assert rose[0].tint == "warn"

    fell = estate.headline(
        [_result("lead_time", _years([(2025, 11.2), (2026, 9.28)]))],
        today=date(2026, 9, 5),
    )
    assert fell[0].tint == ""


def test_a_store_that_did_not_answer_contributes_no_figures():
    assert estate.headline([_result("cadence", [], error="timed out")]) == []


def test_the_year_gone_is_a_fraction_of_the_calendar():
    assert 0.67 < estate.elapsed(date(2026, 9, 5)) < 0.69
    assert estate.elapsed(date(2026, 1, 1)) == 0.0


# --- the axis ---


def test_the_axis_climbs_in_numbers_a_person_counts_in():
    assert scale.ceiling(15) == (15.0, 5.0)
    assert scale.ceiling(8) == (10.0, 5.0)
    assert scale.ceiling(24.1) == (30.0, 10.0)
    assert scale.ceiling(0.9) == (1.0, 0.5)


def test_an_empty_series_still_gives_the_axis_a_top():
    assert scale.ceiling(0) == (1.0, 1.0)
