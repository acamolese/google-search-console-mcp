"""Date resolution is done server-side, so it has to be right without a client."""

from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from google_search_console_mcp import dates
from google_search_console_mcp.errors import GSCError

TODAY = date(2026, 8, 21)


@pytest.mark.parametrize(
    ("period", "expected"),
    [
        ("last_7_days", ("2026-08-15", "2026-08-21")),
        ("last_28_days", ("2026-07-25", "2026-08-21")),
        ("last_3_months", ("2026-05-24", "2026-08-21")),
        ("last_month", ("2026-07-01", "2026-07-31")),
        ("this_month", ("2026-08-01", "2026-08-21")),
        ("last_16_months", ("2025-04-21", "2026-08-21")),
    ],
)
def test_named_periods(period, expected):
    start, end, label = dates.resolve_range(period=period, today=TODAY)
    assert (start, end) == expected
    assert label == period


def test_the_default_is_the_last_28_days():
    assert dates.resolve_range(today=TODAY) == ("2026-07-25", "2026-08-21", "last_28_days")


def test_days_wins_over_the_default_and_period_wins_over_days():
    assert dates.resolve_range(days=7, today=TODAY)[:2] == ("2026-08-15", "2026-08-21")
    assert dates.resolve_range(days=7, period="last_28_days", today=TODAY)[:2] == (
        "2026-07-25",
        "2026-08-21",
    )


def test_explicit_dates_win_over_everything():
    start, end, label = dates.resolve_range(
        date_from="2026-03-01", date_to="2026-03-31", days=7, period="last_7_days", today=TODAY
    )
    assert (start, end, label) == ("2026-03-01", "2026-03-31", "custom")


def test_a_lone_date_to_anchors_a_28_day_window():
    assert dates.resolve_range(date_to="2026-03-31", today=TODAY)[:2] == ("2026-03-04", "2026-03-31")


def test_a_lone_date_from_runs_to_today():
    assert dates.resolve_range(date_from="2026-08-01", today=TODAY)[:2] == ("2026-08-01", "2026-08-21")


@freeze_time("2026-08-21T09:00:00Z")
def test_today_comes_from_the_clock_when_not_passed():
    assert dates.resolve_range()[:2] == ("2026-07-25", "2026-08-21")


def test_a_bad_date_format_names_the_field():
    with pytest.raises(GSCError) as excinfo:
        dates.resolve_range(date_from="21/08/2026", today=TODAY)
    assert "date_from" in str(excinfo.value)
    assert "YYYY-MM-DD" in str(excinfo.value)


def test_an_inverted_range_is_rejected():
    with pytest.raises(GSCError, match="is after"):
        dates.resolve_range(date_from="2026-08-21", date_to="2026-08-01", today=TODAY)


def test_a_future_start_is_rejected():
    with pytest.raises(GSCError, match="in the future"):
        dates.resolve_range(date_from="2026-09-01", date_to="2026-09-30", today=TODAY)


def test_beyond_sixteen_months_is_rejected_and_names_the_earliest_date():
    with pytest.raises(GSCError) as excinfo:
        dates.resolve_range(date_from="2024-01-01", today=TODAY)
    assert "2025-04-21" in str(excinfo.value)


def test_an_unknown_period_lists_the_valid_ones():
    with pytest.raises(GSCError) as excinfo:
        dates.resolve_range(period="last_year", today=TODAY)
    assert "last_28_days" in str(excinfo.value)


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        ("2026-07-25", "2026-08-21", ("2026-06-27", "2026-07-24")),
        ("2026-03-01", "2026-03-31", ("2026-01-29", "2026-02-28")),
        ("2026-01-01", "2026-01-31", ("2025-12-01", "2025-12-31")),
        ("2026-08-21", "2026-08-21", ("2026-08-20", "2026-08-20")),
    ],
)
def test_the_previous_range_has_the_same_length(start, end, expected):
    assert dates.previous_range(start, end) == expected


def test_leap_day_arithmetic():
    # 2028 is a leap year: February has 29 days.
    assert dates.resolve_range(date_from="2028-02-01", date_to="2028-02-29", today=date(2028, 3, 1))[:2] == (
        "2028-02-01",
        "2028-02-29",
    )
    # 31 days back from 29 February 2028 lands on 30 January, not the 31st.
    assert dates.previous_range("2028-03-01", "2028-03-31") == ("2028-01-30", "2028-02-29")


def test_months_ago_clamps_to_the_last_valid_day():
    # 16 months before 31 August is 30 April, not the 31st.
    assert dates.earliest_available(date(2026, 8, 31)) == date(2025, 4, 30)


def test_month_ranges_end_on_the_anchor():
    ranges = dates.month_ranges("2026-08-21", 3)
    assert ranges == [
        ("2026-06", "2026-06-01", "2026-06-30"),
        ("2026-07", "2026-07-01", "2026-07-31"),
        ("2026-08", "2026-08-01", "2026-08-21"),
    ]


def test_hourly_data_is_limited_to_ten_days():
    dates.validate_hourly_range("2026-08-15", "2026-08-21", today=TODAY)
    with pytest.raises(GSCError, match="10 days"):
        dates.validate_hourly_range("2026-08-01", "2026-08-21", today=TODAY)
