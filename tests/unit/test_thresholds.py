"""Thresholds must scale with the property, and never block a small site."""

from __future__ import annotations

import pytest

from google_search_console_mcp.insights.thresholds import (
    CTR_BEYOND_FIRST_PAGE,
    DEFAULT_CTR_CURVE,
    Thresholds,
    percentile,
)


def rows(count: int, scale: int = 10):
    return [{"impressions": index * scale, "clicks": index} for index in range(count)]


def test_percentile_interpolates():
    assert percentile([1, 2, 3, 4], 50) == 2.5
    assert percentile([10], 90) == 10
    assert percentile([], 70) == 0.0


def test_thresholds_grow_with_the_dataset():
    small = Thresholds.from_rows(rows(20))
    medium = Thresholds.from_rows(rows(200))
    large = Thresholds.from_rows(rows(5000))

    assert small.min_impressions < medium.min_impressions < large.min_impressions
    assert small.high_visibility_impressions <= large.high_visibility_impressions


def test_a_tiny_site_still_gets_workable_floors():
    tiny = Thresholds.from_rows([{"impressions": 3, "clicks": 1}])

    assert tiny.min_impressions == 50
    assert tiny.min_clicks == 10
    assert tiny.high_visibility_impressions == 500


def test_no_rows_at_all_does_not_raise():
    empty = Thresholds.from_rows([])
    assert empty.min_impressions == 50


def test_overrides_always_win():
    overridden = Thresholds.from_rows(rows(5000), {"min_impressions": 7, "high_visibility_impressions": 9})
    assert overridden.min_impressions == 7
    assert overridden.high_visibility_impressions == 9
    # An unmentioned threshold keeps its computed value.
    assert overridden.min_clicks > 10


def test_a_custom_ctr_curve_replaces_the_default():
    custom = Thresholds().with_overrides({"ctr_curve": {"1": 0.5, "2": 0.3}})
    assert custom.expected_ctr(1) == 0.5
    assert custom.expected_ctr(2) == 0.3
    assert custom.expected_ctr(3) == CTR_BEYOND_FIRST_PAGE


def test_empty_overrides_change_nothing():
    base = Thresholds.from_rows(rows(100))
    assert base.with_overrides(None) == base
    assert base.with_overrides({}) == base


@pytest.mark.parametrize(
    ("position", "expected"),
    [
        (1, DEFAULT_CTR_CURVE[1]),
        (3.4, DEFAULT_CTR_CURVE[3]),
        (10, DEFAULT_CTR_CURVE[10]),
        (10.6, CTR_BEYOND_FIRST_PAGE),
        (30, CTR_BEYOND_FIRST_PAGE),
        (0, CTR_BEYOND_FIRST_PAGE),
    ],
)
def test_the_ctr_curve_collapses_past_the_first_page(position, expected):
    assert Thresholds().expected_ctr(position) == expected
