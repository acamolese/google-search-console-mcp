"""The analytics tools, driven through the MCP server against a mocked API."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from freezegun import freeze_time

from google_search_console_mcp.client import WEBMASTERS_BASE
from tests.conftest import call_tool

QUERY_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
SITE = "sc-domain:example.com"


def rows(*specs):
    return {
        "rows": [
            {
                "keys": list(spec[0]) if isinstance(spec[0], (list, tuple)) else [spec[0]],
                "clicks": spec[1],
                "impressions": spec[2],
                "ctr": spec[3],
                "position": spec[4],
            }
            for spec in specs
        ]
    }


def sent_body(route, index: int = 0) -> dict:
    return json.loads(route.calls[index].request.content)


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_the_default_range_is_the_last_28_days(server, wired_client):
    payload = rows(("shoes", 10, 100, 0.1, 3.2))
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    text, _ = await call_tool(server, "gsc_query", {"site_url": SITE})

    body = sent_body(route)
    assert body["startDate"] == "2026-07-25"
    assert body["endDate"] == "2026-08-21"
    assert body["dimensions"] == ["query"]
    assert body["dataState"] == "all"
    assert body["type"] == "web"
    assert body["rowLimit"] == 100
    assert "range=2026-07-25..2026-08-21" in text
    assert "period=last_28_days" in text


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_a_named_period_is_resolved_server_side(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    await call_tool(server, "gsc_query", {"site_url": SITE, "period": "last_month"})

    assert sent_body(route)["startDate"] == "2026-07-01"
    assert sent_body(route)["endDate"] == "2026-07-31"


@respx.mock
async def test_filters_are_passed_through_unchanged(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    await call_tool(
        server,
        "gsc_query",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "filters": [
                {"dimension": "page", "operator": "includingRegex", "expression": "^/blog/.*"},
                {"dimension": "country", "operator": "equals", "expression": "ita"},
            ],
        },
    )

    groups = sent_body(route)["dimensionFilterGroups"]
    assert groups == [
        {
            "groupType": "and",
            "filters": [
                {"dimension": "page", "operator": "includingRegex", "expression": "^/blog/.*"},
                {"dimension": "country", "operator": "equals", "expression": "ita"},
            ],
        }
    ]


@respx.mock
async def test_an_unknown_filter_operator_is_rejected_before_any_request(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    text, _ = await call_tool(
        server,
        "gsc_query",
        {
            "site_url": SITE,
            "filters": [{"dimension": "page", "operator": "startsWith", "expression": "/x"}],
        },
    )

    assert route.call_count == 0
    assert "includingRegex" in text


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_the_hour_dimension_forces_the_hourly_data_state(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    await call_tool(server, "gsc_query", {"site_url": SITE, "dimensions": "hour", "days": 3})

    body = sent_body(route)
    assert body["dimensions"] == ["HOUR"]
    assert body["dataState"] == "HOURLY_ALL"


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_the_hour_dimension_rejects_a_range_older_than_ten_days(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    text, _ = await call_tool(server, "gsc_query", {"site_url": SITE, "dimensions": "hour", "days": 20})

    assert route.call_count == 0
    assert "10 days" in text


@respx.mock
async def test_a_row_limit_above_the_cap_is_reduced_and_reported(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows()))

    text, _ = await call_tool(
        server,
        "gsc_query",
        {"site_url": SITE, "date_from": "2026-08-01", "date_to": "2026-08-21", "row_limit": 5000},
    )

    assert sent_body(route)["rowLimit"] == 1000
    assert "row_limit_capped_from=5000" in text


@respx.mock
async def test_has_more_and_next_start_row_appear_when_the_page_is_full(server, wired_client):
    full_page = rows(*[(f"q{i}", 1, 10, 0.1, 5.0) for i in range(3)])
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=full_page))

    text, _ = await call_tool(
        server,
        "gsc_query",
        {"site_url": SITE, "date_from": "2026-08-01", "date_to": "2026-08-21", "row_limit": 3},
    )

    assert "has_more=true" in text
    assert "next_start_row=3" in text


@respx.mock
async def test_json_output_carries_meta_and_rows(server, wired_client):
    respx.post(QUERY_URL).mock(
        return_value=httpx.Response(200, json=rows(("camicie uomo", 1203, 54021, 0.0222695, 6.43)))
    )

    text, _ = await call_tool(
        server,
        "gsc_query",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "response_format": "json",
        },
    )

    payload = json.loads(text)
    assert payload["meta"]["rows"] == 1
    assert payload["rows"][0] == {
        "query": "camicie uomo",
        "clicks": 1203,
        "impressions": 54021,
        "ctr": 0.0223,
        "position": 6.4,
    }


@respx.mock
async def test_a_missing_site_url_explains_the_two_property_formats(server, wired_client):
    text, _ = await call_tool(server, "gsc_query", {"site_url": "  "})
    assert "sc-domain:example.com" in text


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_the_overview_compares_with_the_previous_period(server, wired_client):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["startDate"] == "2026-07-25":
            return httpx.Response(200, json=rows((["x"], 18230, 812000, 0.02245, 11.2)))
        return httpx.Response(200, json=rows((["x"], 20110, 790500, 0.02544, 10.8)))

    respx.post(QUERY_URL).mock(side_effect=handler)

    _text, structured = await call_tool(server, "gsc_performance_overview", {"site_url": SITE})

    assert structured["current"]["clicks"] == 18230
    assert structured["previous"]["clicks"] == 20110
    assert structured["previous_range"] == ["2026-06-27", "2026-07-24"]
    assert structured["delta"]["clicks_pct"] == pytest.approx(-9.3)
    assert structured["delta"]["position_delta"] == pytest.approx(0.4)


@respx.mock
async def test_the_overview_can_skip_the_comparison(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=rows((["x"], 5, 50, 0.1, 4.0))))

    _text, structured = await call_tool(
        server,
        "gsc_performance_overview",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "compare_previous": False,
        },
    )

    assert route.call_count == 1
    assert structured["previous"] is None


@respx.mock
async def test_an_empty_overview_returns_zeros_rather_than_failing(server, wired_client):
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={}))

    _text, structured = await call_tool(
        server,
        "gsc_performance_overview",
        {"site_url": SITE, "date_from": "2026-08-01", "date_to": "2026-08-21"},
    )

    assert structured["current"]["clicks"] == 0
    assert structured["delta"]["clicks_pct"] is None


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_compare_periods_joins_the_two_tables_and_ranks_by_delta(server, wired_client):
    current = rows(
        ("stable", 100, 1000, 0.1, 5.0),
        ("winner", 300, 2000, 0.15, 3.0),
        ("loser", 20, 900, 0.02, 12.0),
        ("new", 40, 400, 0.1, 8.0),
    )
    previous = rows(
        ("stable", 100, 1000, 0.1, 5.0),
        ("winner", 90, 1500, 0.06, 6.0),
        ("loser", 250, 1800, 0.14, 4.0),
        ("gone", 70, 700, 0.1, 9.0),
    )

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=current if body["startDate"] == "2026-07-25" else previous)

    respx.post(QUERY_URL).mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_compare_periods", {"site_url": SITE})

    lines = text.split("\n")
    assert "previous_range=2026-06-27..2026-07-24" in lines[0]
    assert "winners=2" in lines[0]
    assert "losers=2" in lines[0]

    body_rows = [line.split("\t") for line in lines[2:]]
    # Worst first, best last.
    assert body_rows[0][0] == "loser"
    assert body_rows[0][3] == "-230"
    assert body_rows[-1][0] == "winner"
    assert body_rows[-1][3] == "210"

    gone = next(row for row in body_rows if row[0] == "gone")
    assert gone[1] == "0"  # absent from the current period
    assert gone[2] == "70"


@respx.mock
async def test_compare_periods_can_drop_low_impression_rows(server, wired_client):
    payload = rows(("tiny", 1, 5, 0.2, 9.0), ("big", 100, 5000, 0.02, 4.0))
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    text, _ = await call_tool(
        server,
        "gsc_compare_periods",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "min_impressions": 100,
        },
    )

    assert "tiny" not in text
    assert "big" in text
