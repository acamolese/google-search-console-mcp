"""Each rule gets a case that fires, a case just under the bar, and an edge case.

Datasets are built inline so the expected numbers can be worked out by hand and
written into the assertion.
"""

from __future__ import annotations

import random

import pytest

from google_search_console_mcp import insights
from google_search_console_mcp.insights.thresholds import Thresholds

TH = Thresholds(min_impressions=100, min_clicks=10, high_visibility_impressions=1000)


def q(query, clicks, impressions, position, ctr=None):
    return {
        "query": query,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if ctr is None and impressions else (ctr or 0.0),
        "position": position,
    }


def p(page, clicks, impressions, position, ctr=None):
    return {
        "page": page,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if ctr is None and impressions else (ctr or 0.0),
        "position": position,
    }


# -- quick_wins -------------------------------------------------------------


def test_quick_wins_sizes_the_gap_to_the_target_position():
    # 5,000 impressions at position 3 would earn 5000 * 0.100 = 500 clicks; it has 50.
    rows = [q("target", 50, 5000, 12.0)]
    found = insights.quick_wins(rows, TH)

    assert len(found) == 1
    assert found[0]["potential_clicks"] == 500
    assert found[0]["uplift"] == 450
    assert found[0]["target_position"] == 3


def test_quick_wins_ignores_queries_below_the_impression_threshold():
    assert insights.quick_wins([q("thin", 1, 99, 12.0)], TH) == []


def test_quick_wins_ignores_queries_already_at_the_top_or_far_out():
    rows = [q("first", 500, 5000, 1.2), q("buried", 1, 5000, 45.0)]
    assert insights.quick_wins(rows, TH) == []


def test_quick_wins_drops_queries_already_beating_the_target():
    # 200 clicks on 1,000 impressions is far above the 10% a position-3 result earns.
    assert insights.quick_wins([q("overperformer", 200, 1000, 8.0)], TH) == []


def test_quick_wins_ranks_by_uplift_not_impressions():
    # The bigger query has more impressions but is already close to its ceiling.
    rows = [q("big-but-fine", 900, 10000, 5.0), q("smaller-gap", 10, 4000, 15.0)]
    found = insights.quick_wins(rows, TH)

    assert [item["query"] for item in found] == ["smaller-gap", "big-but-fine"]
    assert found[0]["uplift"] == 390
    assert found[1]["uplift"] == 100


# -- ctr_gaps ---------------------------------------------------------------


def test_ctr_gaps_flags_a_page_clicked_far_below_its_position():
    # Position 3 expects 10%; 1% is a tenth of that.
    rows = [p("https://example.com/a", 20, 2000, 3.0)]
    found = insights.ctr_gaps(rows, TH)

    assert len(found) == 1
    assert found[0]["expected_ctr"] == 0.1
    assert found[0]["potential_clicks"] == 200
    assert found[0]["uplift"] == 180


def test_ctr_gaps_ignores_a_page_close_enough_to_expectation():
    # 7% against an expected 10% is above the 0.6 ratio.
    assert insights.ctr_gaps([p("https://example.com/b", 140, 2000, 3.0)], TH) == []


def test_ctr_gaps_ignores_low_visibility_pages():
    assert insights.ctr_gaps([p("https://example.com/c", 1, 999, 3.0)], TH) == []


def test_ctr_gaps_ignores_anything_off_the_first_page():
    assert insights.ctr_gaps([p("https://example.com/d", 1, 5000, 14.0)], TH) == []


def test_ctr_gaps_can_analyse_queries_instead_of_pages():
    found = insights.ctr_gaps([q("cheap widgets", 20, 2000, 3.0)], TH, entity="query")
    assert found[0]["query"] == "cheap widgets"


# -- cannibalization --------------------------------------------------------


def qp(query, page, clicks, impressions, position):
    return {
        "query": query,
        "page": page,
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "position": position,
    }


def test_cannibalization_flags_a_query_split_across_pages():
    rows = [
        qp("widgets", "https://example.com/a", 40, 1000, 4.0),
        qp("widgets", "https://example.com/b", 20, 800, 7.0),
        qp("widgets", "https://example.com/c", 5, 600, 11.0),
    ]
    found = insights.cannibalization(rows, TH)

    assert len(found) == 1
    assert found[0]["page_count"] == 3
    assert found[0]["clicks"] == 65
    assert found[0]["impressions"] == 2400
    assert [page["page"] for page in found[0]["pages"]][0] == "https://example.com/a"


def test_cannibalization_ignores_a_page_with_a_negligible_share():
    rows = [
        qp("widgets", "https://example.com/a", 60, 5000, 4.0),
        qp("widgets", "https://example.com/b", 1, 100, 40.0),  # 2% of impressions
    ]
    assert insights.cannibalization(rows, TH) == []


def test_cannibalization_ignores_queries_below_the_click_threshold():
    rows = [
        qp("tiny", "https://example.com/a", 3, 500, 4.0),
        qp("tiny", "https://example.com/b", 2, 500, 6.0),
    ]
    assert insights.cannibalization(rows, TH) == []


def test_cannibalization_ranks_by_impressions_times_pages():
    rows = [
        qp("small", "https://example.com/a", 30, 400, 4.0),
        qp("small", "https://example.com/b", 30, 400, 6.0),
        qp("big", "https://example.com/c", 30, 4000, 4.0),
        qp("big", "https://example.com/d", 30, 4000, 6.0),
    ]
    found = insights.cannibalization(rows, TH)
    assert [group["query"] for group in found] == ["big", "small"]


# -- traffic_drops ----------------------------------------------------------


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [
        # gone entirely
        (p("u", 0, 0, 0.0), p("u", 100, 2000, 5.0), "disappeared"),
        # position got materially worse
        (p("u", 30, 1900, 9.0), p("u", 100, 2000, 5.0), "ranking_loss"),
        # same position, far fewer impressions
        (p("u", 40, 800, 5.2), p("u", 100, 2000, 5.0), "demand_decline"),
        # same position and impressions, CTR collapsed
        (p("u", 20, 1950, 5.1), p("u", 100, 2000, 5.0), "ctr_collapse"),
        # a bit of everything, none decisive
        (p("u", 70, 1750, 5.4), p("u", 100, 2000, 5.0), "mixed"),
    ],
)
def test_traffic_drops_names_the_likely_cause(current, previous, expected):
    found = insights.traffic_drops([current], [previous], TH)
    assert len(found) == 1
    assert found[0]["diagnosis"] == expected


def test_traffic_drops_ignores_pages_that_were_never_significant():
    assert insights.traffic_drops([p("u", 0, 0, 0.0)], [p("u", 9, 100, 5.0)], TH) == []


def test_traffic_drops_ignores_a_shallow_decline():
    assert insights.traffic_drops([p("u", 90, 2000, 5.0)], [p("u", 100, 2000, 5.0)], TH) == []


def test_traffic_drops_orders_by_absolute_loss():
    current = [p("small", 10, 500, 6.0), p("big", 20, 3000, 6.0)]
    previous = [p("small", 40, 500, 5.0), p("big", 400, 3000, 5.0)]
    found = insights.traffic_drops(current, previous, TH)
    assert [row["page"] for row in found] == ["big", "small"]


# -- content_decay ----------------------------------------------------------


def test_content_decay_finds_a_page_declining_every_month():
    series = {"https://example.com/a": [("2026-03", 100), ("2026-04", 80), ("2026-05", 60), ("2026-06", 40)]}
    found = insights.content_decay(series, TH)

    assert len(found) == 1
    assert found[0]["peak_clicks"] == 100
    assert found[0]["last_clicks"] == 40
    assert found[0]["lost_clicks"] == 60
    assert found[0]["decay_pct"] == 60.0


def test_content_decay_ignores_a_month_that_recovers():
    series = {"https://example.com/a": [("2026-03", 100), ("2026-04", 80), ("2026-05", 95), ("2026-06", 40)]}
    assert insights.content_decay(series, TH) == []


def test_content_decay_ignores_pages_that_never_mattered():
    series = {"https://example.com/a": [("2026-03", 20), ("2026-04", 15), ("2026-05", 10), ("2026-06", 5)]}
    assert insights.content_decay(series, TH) == []


def test_content_decay_needs_enough_history():
    series = {"https://example.com/a": [("2026-05", 100), ("2026-06", 50)]}
    assert insights.content_decay(series, TH) == []


# -- alerts -----------------------------------------------------------------


def test_alerts_flags_a_big_position_loss_as_high():
    current = [q("widget", 5, 1000, 18.0)]
    previous = [q("widget", 90, 1000, 4.0)]
    found = insights.alerts(current, previous, [], [], TH)

    position_alerts = [item for item in found if item["type"] == "position_loss"]
    assert position_alerts[0]["severity"] == "high"
    assert position_alerts[0]["delta"] == 14.0


def test_alerts_flags_a_disappeared_page():
    found = insights.alerts([], [], [], [p("https://example.com/gone", 50, 900, 5.0)], TH)
    assert found[0]["type"] == "page_disappeared"
    assert found[0]["severity"] == "high"


def test_alerts_ignores_low_volume_noise():
    current = [q("rare", 0, 5, 30.0)]
    previous = [q("rare", 1, 5, 4.0)]
    assert insights.alerts(current, previous, [], [], TH) == []


def test_alerts_sorts_high_severity_first():
    current_pages = [p("https://example.com/a", 30, 900, 5.0), p("https://example.com/b", 5, 900, 5.0)]
    previous_pages = [p("https://example.com/a", 50, 900, 5.0), p("https://example.com/b", 50, 900, 5.0)]
    found = insights.alerts([], [], current_pages, previous_pages, TH)
    assert [item["severity"] for item in found] == ["high", "medium"]


# -- brand_split and themes -------------------------------------------------


def test_brand_split_uses_the_terms_it_is_given():
    rows = [q("acme shop", 100, 1000, 2.0), q("blue widgets", 20, 2000, 8.0)]
    split = insights.brand_split(rows, ["acme"])

    assert split["brand"]["clicks"] == 100
    assert split["non_brand"]["clicks"] == 20
    assert split["brand_clicks_pct"] == 83.3
    assert split["brand_terms_source"] == "explicit"


def test_brand_split_falls_back_to_the_domain_and_says_so():
    rows = [q("exampleco shop", 100, 1000, 2.0), q("widgets", 20, 2000, 8.0)]
    split = insights.brand_split(rows, [], site_url="sc-domain:exampleco.com")

    assert split["brand"]["clicks"] == 100
    assert split["brand_terms_source"] == "domain_label"
    assert split["brand_terms"] == ["exampleco"]


def test_brand_split_matches_across_spacing():
    rows = [q("acme  shop", 10, 100, 2.0)]
    assert insights.brand_split(rows, ["acme shop"])["brand"]["clicks"] == 10


def test_brand_split_handles_a_site_with_no_clicks():
    split = insights.brand_split([], ["acme"])
    assert split["brand_clicks_pct"] == 0.0


def test_themes_skips_stopwords_and_brand_terms():
    rows = [q("blue widget repair guide", 10, 100, 5.0), q("widget repair cost", 5, 80, 6.0)]
    found = insights.themes(rows, stopwords=["blue"], brand_terms=["guide"])

    labels = [item["theme"] for item in found]
    assert "widget" in labels
    assert "repair" in labels
    assert "blue" not in labels
    assert "guide" not in labels
    assert all(item["experimental"] for item in found)


def test_domain_label_strips_scheme_and_www():
    assert insights.domain_label("sc-domain:example.com") == "example"
    assert insights.domain_label("https://www.example.co.uk/") == "example"


# -- invariants -------------------------------------------------------------


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_rules_hold_their_invariants_on_random_data(seed):
    rng = random.Random(seed)  # noqa: S311 - deterministic test data
    queries = [
        q(f"query {i}", rng.randint(0, 500), rng.randint(1, 20000), rng.uniform(1, 40)) for i in range(200)
    ]
    pages = [
        p(f"https://example.com/{i}", rng.randint(0, 500), rng.randint(1, 20000), rng.uniform(1, 40))
        for i in range(200)
    ]
    th = Thresholds.from_rows(queries + pages)

    wins = insights.quick_wins(queries, th)
    assert all(item["uplift"] > 0 for item in wins)
    assert wins == sorted(wins, key=lambda item: item["uplift"], reverse=True)

    gaps = insights.ctr_gaps(pages, th)
    assert all(item["uplift"] >= 0 for item in gaps)
    assert all(item["ctr"] < item["expected_ctr"] for item in gaps)

    drops = insights.traffic_drops(pages, pages, th)
    assert drops == []  # comparing a period with itself can never be a drop
