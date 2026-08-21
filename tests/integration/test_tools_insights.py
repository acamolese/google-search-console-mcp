"""The insight tools, driven through the server against a mocked API."""

from __future__ import annotations

import json

import httpx
import respx
from freezegun import freeze_time

from google_search_console_mcp.client import WEBMASTERS_BASE
from tests.conftest import call_tool, load_fixture

SITE = "sc-domain:example.com"
QUERY_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
SITES_URL = f"{WEBMASTERS_BASE}/sites"


def api_rows(*specs):
    return {
        "rows": [
            {
                "keys": list(keys) if isinstance(keys, (list, tuple)) else [keys],
                "clicks": clicks,
                "impressions": impressions,
                "ctr": round(clicks / impressions, 4) if impressions else 0,
                "position": position,
            }
            for keys, clicks, impressions, position in specs
        ]
    }


def meta_of(text: str) -> dict:
    header = text.split("\n")[0].removeprefix("# meta ").split(" ")
    return dict(part.split("=", 1) for part in header if "=" in part)


def body_of(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.split("\n")[2:] if line]


@respx.mock
async def test_quick_wins_reports_the_uplift_and_the_thresholds(server, wired_client):
    payload = api_rows(
        ("target", 50, 5000, 12.0),
        ("already good", 900, 5000, 1.5),
        ("too thin", 1, 30, 15.0),
    )
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    text, _ = await call_tool(server, "gsc_quick_wins", {"site_url": SITE, "period": "last_28_days"})

    meta = meta_of(text)
    assert meta["source"] == "insights.quick_wins"
    assert "min_impressions" in meta
    assert meta["analysed"] == "3"

    rows = body_of(text)
    assert rows[0][0] == "target"
    assert rows[0][7] == "450"  # uplift


@respx.mock
async def test_quick_wins_asks_for_the_long_tail_not_the_top_slice(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=api_rows()))

    await call_tool(server, "gsc_quick_wins", {"site_url": SITE})

    assert json.loads(route.calls[0].request.content)["rowLimit"] == 5000


@respx.mock
async def test_ctr_gaps_can_switch_between_pages_and_queries(server, wired_client):
    payload = api_rows((["https://example.com/a"], 20, 2000, 3.0))
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    text, _ = await call_tool(server, "gsc_ctr_gaps", {"site_url": SITE, "entity": "page"})
    assert json.loads(route.calls[0].request.content)["dimensions"] == ["page"]
    assert body_of(text)[0][0] == "https://example.com/a"
    assert meta_of(text)["entity"] == "page"

    await call_tool(server, "gsc_ctr_gaps", {"site_url": SITE, "entity": "query"})
    assert json.loads(route.calls[1].request.content)["dimensions"] == ["query"]


@respx.mock
async def test_ctr_gaps_rejects_an_unknown_entity(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=api_rows()))
    text, _ = await call_tool(server, "gsc_ctr_gaps", {"site_url": SITE, "entity": "device"})

    assert route.call_count == 0
    assert "page" in text and "query" in text


@respx.mock
async def test_cannibalization_flattens_the_competing_pages_into_one_row(server, wired_client):
    payload = api_rows(
        (["widgets", "https://example.com/a"], 40, 1000, 4.0),
        (["widgets", "https://example.com/b"], 20, 800, 7.0),
        (["shoes", "https://example.com/c"], 30, 900, 3.0),
    )
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    text, _ = await call_tool(server, "gsc_cannibalization", {"site_url": SITE})

    rows = body_of(text)
    assert len(rows) == 1
    assert rows[0][0] == "widgets"
    assert rows[0][1] == "2"
    assert "https://example.com/a" in rows[0][4]
    assert meta_of(text)["truncated"] == "false"


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_traffic_drops_compares_against_the_previous_window(server, wired_client):
    current = api_rows((["https://example.com/a"], 20, 800, 5.2))
    previous = api_rows((["https://example.com/a"], 100, 2000, 5.0))

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        return httpx.Response(200, json=current if body["startDate"] == "2026-07-25" else previous)

    respx.post(QUERY_URL).mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_traffic_drops", {"site_url": SITE})

    meta = meta_of(text)
    assert meta["previous_range"] == "2026-06-27..2026-07-24"
    rows = body_of(text)
    assert rows[0][0] == "https://example.com/a"
    assert rows[0][11] == "demand_decline"


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_content_decay_reads_one_query_per_month(server, wired_client):
    months = {
        "2026-03": 100,
        "2026-04": 90,
        "2026-05": 70,
        "2026-06": 55,
        "2026-07": 40,
        "2026-08": 30,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        month = json.loads(request.content)["startDate"][:7]
        clicks = months.get(month, 10)
        return httpx.Response(200, json=api_rows((["https://example.com/a"], clicks, 1000, 6.0)))

    route = respx.post(QUERY_URL).mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_content_decay", {"site_url": SITE, "months": 6})

    assert route.call_count == 6
    rows = body_of(text)
    assert rows[0][0] == "https://example.com/a"
    assert rows[0][2] == "100"  # peak clicks
    assert rows[0][4] == "30"  # last month
    assert meta_of(text)["months"] == "6"


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_alerts_reads_queries_and_pages_for_both_windows(server, wired_client):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        current = body["startDate"] == "2026-08-15"
        if body["dimensions"] == ["query"]:
            return httpx.Response(
                200,
                json=api_rows((["widget"], 5, 1000, 18.0) if current else (["widget"], 90, 1000, 4.0)),
            )
        return httpx.Response(
            200,
            json=api_rows(
                (["https://example.com/a"], 5, 900, 5.0)
                if current
                else (["https://example.com/a"], 60, 900, 5.0)
            ),
        )

    route = respx.post(QUERY_URL).mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_alerts", {"site_url": SITE, "window_days": 7})

    assert route.call_count == 4
    assert meta_of(text)["previous_range"] == "2026-08-08..2026-08-14"
    kinds = {row[1] for row in body_of(text)}
    assert "position_loss" in kinds
    assert "clicks_drop" in kinds


@respx.mock
@freeze_time("2026-08-21T09:00:00Z")
async def test_the_portfolio_flags_the_properties_worth_looking_at(server, wired_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    totals = {
        ("sc-domain:example.com", True): 100,
        ("sc-domain:example.com", False): 100,
        ("https://shop.example.com/", True): 40,
        ("https://shop.example.com/", False): 100,
        ("https://blog.example.com/", True): 80,
        ("https://blog.example.com/", False): 100,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        import urllib.parse

        site = urllib.parse.unquote(str(request.url).split("/sites/")[1].split("/searchAnalytics")[0])
        current = json.loads(request.content)["startDate"] == "2026-07-25"
        clicks = totals[(site, current)]
        return httpx.Response(200, json=api_rows(([], clicks, clicks * 20, 8.0)))

    respx.post(url__regex=rf"{WEBMASTERS_BASE}/sites/.+/searchAnalytics/query").mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_portfolio", {})

    meta = meta_of(text)
    assert meta["rows"] == "3"
    assert meta["critical"] == "1"
    assert meta["warning"] == "1"

    rows = body_of(text)
    assert rows[0][0] == "https://shop.example.com/"
    assert rows[0][8] == "critical"
    assert rows[-1][8] == "ok"


@respx.mock
async def test_a_property_that_fails_does_not_sink_the_portfolio(server, wired_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    def handler(request: httpx.Request) -> httpx.Response:
        if "shop.example.com" in str(request.url):
            return httpx.Response(403, json=load_fixture("errors", "403_permission.json"))
        return httpx.Response(200, json=api_rows(([], 100, 2000, 8.0)))

    respx.post(url__regex=rf"{WEBMASTERS_BASE}/sites/.+/searchAnalytics/query").mock(side_effect=handler)

    text, _ = await call_tool(server, "gsc_portfolio", {})

    rows = body_of(text)
    assert len(rows) == 3
    assert rows[0][8] == "error"
    assert "403" in rows[0][9]


@respx.mock
async def test_thresholds_can_be_overridden_per_call(server, wired_client):
    # 40 impressions sits under the 50-impression floor, so the default run finds nothing.
    payload = api_rows(("small", 2, 40, 12.0))
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=payload))

    default_text, _ = await call_tool(server, "gsc_quick_wins", {"site_url": SITE})
    assert meta_of(default_text)["min_impressions"] == "50"
    assert meta_of(default_text)["rows"] == "0"

    lowered_text, _ = await call_tool(
        server,
        "gsc_quick_wins",
        {"site_url": SITE, "thresholds": {"min_impressions": 10}, "no_cache": True},
    )
    assert meta_of(lowered_text)["min_impressions"] == "10"
    assert meta_of(lowered_text)["rows"] == "1"


@respx.mock
async def test_insight_tools_can_answer_in_json(server, wired_client):
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=api_rows(("target", 50, 5000, 12.0))))

    text, _ = await call_tool(server, "gsc_quick_wins", {"site_url": SITE, "response_format": "json"})

    payload = json.loads(text)
    assert payload["meta"]["source"] == "insights.quick_wins"
    assert payload["rows"][0]["query"] == "target"
