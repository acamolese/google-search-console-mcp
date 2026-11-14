"""Regression tests for the 4.0 corrections: each one pins a case that used to mislead."""

from __future__ import annotations

from datetime import date

import pytest

from google_search_console_mcp import dates, insights
from google_search_console_mcp.errors import GSCError
from google_search_console_mcp.insights.thresholds import Thresholds

TH = Thresholds(min_impressions=100, min_clicks=10, high_visibility_impressions=1000)


def row(key, name, clicks, impressions, position):
    return {
        key: name,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": clicks / impressions if impressions else 0.0,
        "position": position,
    }


def qp(query, page, clicks, impressions, position):
    return {**row("query", query, clicks, impressions, position), "page": page}


# -- content decay and the month in progress ------------------------------------


def test_complete_months_leave_out_the_month_in_progress():
    ranges = dates.month_ranges("2026-11-14", 3, complete_only=True)
    assert [label for label, _s, _e in ranges] == ["2026-08", "2026-09", "2026-10"]
    assert ranges[-1][2] == "2026-10-31"


def test_complete_months_keep_a_month_that_ends_on_the_anchor():
    ranges = dates.month_ranges("2026-10-31", 2, complete_only=True)
    assert [label for label, _s, _e in ranges] == ["2026-09", "2026-10"]


def test_a_stable_page_is_not_decaying_when_the_partial_month_is_excluded():
    # 300 clicks a month, every month. With the half month of November in the
    # series it used to come out as a 56% decay.
    ranges = dates.month_ranges("2026-11-14", 6, complete_only=True)
    series = {"https://e.com/a": [(label, 300) for label, _s, _e in ranges]}
    assert insights.content_decay(series, TH) == []


# -- comparison baselines -------------------------------------------------------


def test_a_whole_month_compares_with_the_same_month_last_year():
    assert dates.year_ago_range("2026-10-01", "2026-10-31") == ("2025-10-01", "2025-10-31")
    assert dates.year_ago_range("2026-02-01", "2026-03-31") == ("2025-02-01", "2025-03-31")


def test_a_rolling_window_moves_back_52_weeks_to_keep_weekdays():
    start, end = dates.year_ago_range("2026-11-02", "2026-11-08")
    assert date.fromisoformat(start).weekday() == date(2026, 11, 2).weekday()
    assert (start, end) == ("2025-11-03", "2025-11-09")


def test_an_unknown_compare_mode_is_refused():
    with pytest.raises(GSCError, match="compare must be"):
        dates.baseline_range("2026-10-01", "2026-10-31", "quarter")


def test_a_baseline_outside_the_retention_window_is_flagged():
    assert dates.baseline_warning("2025-01-01", today=date(2026, 11, 14)) is not None
    assert dates.baseline_warning("2026-01-01", today=date(2026, 11, 14)) is None


def test_one_end_of_the_baseline_keeps_the_current_length():
    assert dates.range_of_span("2026-09-01", "", 7) == ("2026-09-01", "2026-09-07")
    assert dates.range_of_span("", "2026-09-07", 7) == ("2026-09-01", "2026-09-07")


# -- brand matching -------------------------------------------------------------


def test_brand_terms_match_whole_words_only():
    is_brand = insights.brand_matcher(["nova", "arte"])
    assert is_brand("nova orari")
    assert is_brand("negozio nova")
    assert not is_brand("innovazione digitale")
    assert not is_brand("partenza treni")


def test_brand_terms_tolerate_spaces_inside_them():
    is_brand = insights.brand_matcher(["exampleco"])
    assert is_brand("example co login")
    assert is_brand("ExampleCo")


def test_the_api_regex_has_word_edges_and_ignores_case():
    pattern = insights.brand_regex(["nova"])
    assert pattern.startswith("(?i)")
    assert "(^|\\W)" in pattern and "(\\W|$)" in pattern
    assert insights.brand_regex([]) is None


def test_the_brand_split_no_longer_claims_words_that_contain_the_term():
    rows = [row("query", "nova orari", 50, 500, 2.0), row("query", "innovazione", 50, 500, 4.0)]
    split = insights.brand_split(rows, ["nova"])
    assert split["brand"]["clicks"] == 50
    assert split["non_brand"]["clicks"] == 50


# -- cannibalisation --------------------------------------------------------------


def test_brand_queries_are_not_cannibalisation():
    rows = [
        qp("exampleco", "https://e.com/", 300, 3000, 4.2),
        qp("exampleco", "https://e.com/contact", 200, 2000, 5.0),
    ]
    assert [item["query"] for item in insights.cannibalization(rows, TH)] == ["exampleco"]
    assert insights.cannibalization(rows, TH, brand_terms=["exampleco"]) == []


def test_one_page_firmly_in_the_top_three_is_not_cannibalisation():
    rows = [qp("shoes", "https://e.com/a", 900, 5000, 1.5), qp("shoes", "https://e.com/b", 10, 1000, 8.0)]
    assert insights.cannibalization(rows, TH) == []


def test_a_split_with_no_clicks_at_all_is_still_reported():
    rows = [qp("boots", "https://e.com/a", 0, 800, 14.0), qp("boots", "https://e.com/b", 0, 700, 15.0)]
    found = insights.cannibalization(rows, TH)
    assert [item["query"] for item in found] == ["boots"]


# -- drops and alerts ------------------------------------------------------------


def test_a_page_with_impressions_but_no_clicks_has_not_disappeared():
    now = row("page", "u", 0, 1500, 9.0)
    before = row("page", "u", 100, 2000, 5.0)
    found = insights.traffic_drops([now], [before], TH)
    assert found[0]["diagnosis"] == "ranking_loss"


def test_a_page_gone_from_the_results_has_disappeared():
    found = insights.traffic_drops([], [row("page", "u", 100, 2000, 5.0)], TH)
    assert found[0]["diagnosis"] == "disappeared"


def test_a_page_missing_from_a_truncated_period_is_not_reported_as_lost():
    found = insights.traffic_drops([], [row("page", "u", 100, 2000, 5.0)], TH, current_complete=False)
    assert found == []


def test_alerts_do_not_call_a_page_below_the_row_cut_vanished():
    previous = [row("page", "u", 100, 2000, 5.0)]
    assert insights.alerts([], [], [], previous)[0]["type"] == "page_disappeared"
    assert insights.alerts([], [], [], previous, current_pages_complete=False) == []


def test_alert_rules_are_fixed_and_published():
    assert insights.ALERT_RULES["position_loss"] == 5
    assert insights.ALERT_RULES["page_min_clicks"] == 20
