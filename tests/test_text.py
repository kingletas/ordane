from datetime import UTC, datetime

from ordane.presentation.text import (  # noqa: I001
    clock,
    day,
    elide,
    moment,
    plural,
    sentence,
    since,
    took,
    verb,
)

NOW = datetime(2026, 9, 5, 18, 0, tzinfo=UTC)


def test_a_count_never_reads_as_a_form_field():
    assert plural(1, "environment") == "1 environment"
    assert plural(3, "environment") == "3 environments"
    assert plural(2, "match") == "2 matches"


def test_a_verb_agrees_with_its_count():
    assert verb(1, "is") == "is"
    assert verb(2, "is") == "are"


def test_a_list_reads_as_a_sentence():
    assert sentence(["a"]) == "a"
    assert sentence(["a", "b"]) == "a and b"
    assert sentence(["a", "b", "c"]) == "a, b and c"
    assert sentence([]) == ""


def test_elide_keeps_a_line_from_running_away():
    assert elide("x" * 200, 10) == "xxxxxxxxx…"


def test_today_is_said_as_today():
    assert moment("2026-09-05T13:27:01Z", NOW).startswith("today at ")


def test_yesterday_is_said_as_yesterday():
    assert moment("2026-09-04T09:04:00Z", NOW).startswith("yesterday at ")


def test_a_date_beyond_the_week_is_given_in_full():
    assert "Jul" in moment("2026-07-02T09:04:00Z", NOW)


def test_an_unparseable_stamp_is_returned_untouched_rather_than_guessed():
    assert moment("not a date", NOW) == "not a date"


def test_a_sub_second_run_is_not_reported_as_zero():
    assert took(0.02) == "under a second"
    assert took(None) == ""
    assert took(0) == ""


def test_longer_runs_read_in_the_units_a_person_would_use():
    assert took(12.4) == "12s"
    assert took(200) == "3m 20s"
    assert took(3900) == "1h 05m"


def test_a_day_heading_reads_as_a_day():
    assert day("2026-09-05T13:27:01Z", NOW) == "Today"
    assert day("2026-09-04T09:04:00Z", NOW) == "Yesterday"
    assert day("2026-09-02T09:04:00Z", NOW) == "Wednesday"
    assert day("2026-07-02T09:04:00Z", NOW) == "2 July"
    assert day("2025-07-02T09:04:00Z", NOW) == "2 July 2025"


def test_an_undated_run_gets_a_heading_rather_than_a_crash():
    assert day("not a date", NOW) == "Undated"


def test_a_row_under_a_day_heading_shows_only_a_time():
    assert clock("2026-09-05T13:27:01Z").count(":") == 1


def test_elapsed_seconds_come_back_for_a_readable_stamp():
    assert since("2026-09-05T17:59:00Z", NOW) == 60.0


def test_a_stamp_in_the_future_does_not_go_negative():
    assert since("2026-09-05T18:05:00Z", NOW) == 0.0


def test_an_unreadable_stamp_has_no_elapsed_time_rather_than_zero():
    assert since("not a date", NOW) is None
