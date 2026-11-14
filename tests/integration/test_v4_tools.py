"""4.0 behaviour through the server: anchored windows, baselines, filters, the brand split."""

from __future__ import annotations

import json

import httpx
import pytest
import respx
from freezegun import freeze_time

from google_search_console_mcp import client as client_module
from google_search_console_mcp.audit import run_audit
from google_search_console_mcp.client import WEBMASTERS_BASE
from google_search_console_mcp.config import Settings
from google_search_console_mcp.errors import GSCError
from tests.conftest import call_tool, load_fixture

SITE = "sc-domain:example.com"
QUERY_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
SITES_URL = f"{WEBMASTERS_BASE}/sites"


def meta_of(text: str) -> dict:
    header = text.split("\n")[0].removeprefix("# meta ")
    out = {}
    for part in header.split(" "):
        if "=" in part:
            key, value = part.split("=", 1)
            out[key] = value
    return out


def body_of(text: str) -> list[list[str]]:
    return [line.split("\t") for line in text.split("\n")[2:] if line]


def date_rows(*days):
    return {
        "rows": [{"keys": [day], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 5} for day in days]
    }


def page_rows(*specs):
    return {
        "rows": [
            {"keys": [page], "clicks": c, "impressions": i, "ctr": c / i if i else 0, "position": pos}
            for page, c, i, pos in specs
        ]
    }


# -- the client ------------------------------------------------------------------


@respx.mock
async def test_a_long_retry_after_fails_fast_with_a_hint(gsc_client, no_real_sleep):
    respx.get(SITES_URL).mock(
        return_value=httpx.Response(
            429, json=load_fixture("errors", "429_too_many.json"), headers={"Retry-After": "600"}
        )
    )
    with pytest.raises(GSCError) as excinfo:
        await gsc_client.list_sites()
    assert "600 seconds" in str(excinfo.value)
    assert no_real_sleep == []


@respx.mock
async def test_the_last_final_day_is_the_newest_date_returned(gsc_client):
    route = respx.post(QUERY_URL).mock(
        return_value=httpx.Response(200, json=date_rows("2026-11-09", "2026-11-10", "2026-11-08"))
    )
    assert await gsc_client.latest_final_date(SITE, "2026-11-14") == "2026-11-10"
    body = json.loads(route.calls[0].request.content)
    assert body["dataState"] == "final"
    assert body["dimensions"] == ["date"]


@respx.mock
async def test_no_final_data_gives_no_anchor(gsc_client):
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={}))
    assert await gsc_client.latest_final_date(SITE, "2026-11-14") is None


@respx.mock
async def test_the_cache_state_covers_every_request_of_the_call(gsc_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))
    client_module.start_cache_log()
    await gsc_client.list_sites()
    await gsc_client.list_sites()
    assert gsc_client.last_cache_state == "mixed"


# -- anchored windows and baselines ------------------------------------------------


@respx.mock
@freeze_time("2026-11-14T09:00:00Z")
async def test_traffic_drops_end_on_the_last_day_with_final_data(server, wired_client):
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("dimensions") == ["date"]:
            return httpx.Response(200, json=date_rows("2026-11-09", "2026-11-10"))
        seen.append((body["startDate"], body["endDate"]))
        return httpx.Response(200, json=page_rows(("https://e.com/a", 10, 100, 5.0)))

    respx.post(QUERY_URL).mock(side_effect=handler)
    text, _ = await call_tool(server, "gsc_traffic_drops", {"site_url": SITE, "days": 7})

    meta = meta_of(text)
    assert meta["data_through"] == "2026-11-10"
    assert meta["range"] == "2026-11-04..2026-11-10"
    assert meta["previous_range"] == "2026-10-28..2026-11-03"
    assert ("2026-11-04", "2026-11-10") in seen


@respx.mock
@freeze_time("2026-11-14T09:00:00Z")
async def test_an_explicit_end_date_is_left_alone(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=page_rows()))
    text, _ = await call_tool(
        server, "gsc_traffic_drops", {"site_url": SITE, "date_from": "2026-10-01", "date_to": "2026-10-31"}
    )
    assert "data_through" not in meta_of(text)
    assert all(json.loads(call.request.content).get("dimensions") != ["date"] for call in route.calls)


@respx.mock
@freeze_time("2026-11-14T09:00:00Z")
async def test_year_over_year_compares_with_the_same_month(server, wired_client):
    respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json=page_rows()))
    text, _ = await call_tool(
        server,
        "gsc_traffic_drops",
        {"site_url": SITE, "date_from": "2026-10-01", "date_to": "2026-10-31", "compare": "year"},
    )
    meta = meta_of(text)
    assert meta["previous_range"] == "2025-10-01..2025-10-31"
    assert meta["compare"] == "year"


@respx.mock
@freeze_time("2026-11-14T09:00:00Z")
async def test_overview_reports_its_anchor_and_baseline(server, wired_client):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body.get("dimensions") == ["date"]:
            return httpx.Response(200, json=date_rows("2026-11-10"))
        return httpx.Response(
            200, json={"rows": [{"clicks": 10, "impressions": 100, "ctr": 0.1, "position": 4}]}
        )

    respx.post(QUERY_URL).mock(side_effect=handler)
    _text, structured = await call_tool(
        server, "gsc_performance_overview", {"site_url": SITE, "compare": "year"}
    )
    data = structured.get("result", structured) if isinstance(structured, dict) else structured
    assert data["data_through"] == "2026-11-10"
    assert data["compare"] == "year"


# -- filters and parameters ---------------------------------------------------------


@respx.mock
async def test_filters_reach_the_analysis_tools(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={"rows": []}))
    text, _ = await call_tool(
        server,
        "gsc_quick_wins",
        {
            "site_url": SITE,
            "period": "last_28_days",
            "filters": [{"dimension": "page", "operator": "contains", "expression": "/blog/"}],
        },
    )
    body = json.loads(route.calls[0].request.content)
    assert body["dimensionFilterGroups"][0]["filters"][0]["expression"] == "/blog/"
    assert meta_of(text)["filters"] == "page:contains:/blog/"


@pytest.mark.parametrize(
    ("arguments", "message"),
    [
        ({"filters": [{"operator": "contains", "expression": "x"}]}, "no `dimension`"),
        (
            {"filters": [{"dimension": "query", "expression": "x"}], "filter_group_type": "or"},
            "only accepts 'and'",
        ),
        ({"filters": [{"dimension": "date", "expression": "2026"}]}, "date_from and date_to"),
    ],
)
async def test_bad_filters_are_refused_before_any_request(server, wired_client, arguments, message):
    with respx.mock:
        route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={}))
        text, _ = await call_tool(server, "gsc_query", {"site_url": SITE, **arguments})
        assert message in text
        assert route.call_count == 0


async def test_an_unknown_threshold_is_refused(server, wired_client):
    with respx.mock:
        respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={"rows": []}))
        text, _ = await call_tool(
            server,
            "gsc_quick_wins",
            {"site_url": SITE, "period": "last_28_days", "thresholds": {"min_clicks_": 3}},
        )
    assert "Unknown threshold" in text


async def test_compare_periods_refuses_a_date_dimension(server, wired_client):
    with respx.mock:
        route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={}))
        text, _ = await call_tool(server, "gsc_compare_periods", {"site_url": SITE, "dimension": "date"})
        assert "Valid values here" in text
        assert route.call_count == 0


@respx.mock
async def test_the_portfolio_says_how_many_properties_exist(server, wired_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))
    respx.post(url__regex=r".*/searchAnalytics/query").mock(
        return_value=httpx.Response(200, json={"rows": []})
    )
    text, _ = await call_tool(server, "gsc_portfolio", {"limit": 1, "date_to": "2026-10-31"})
    meta = meta_of(text)
    assert int(meta["total_properties"]) >= 1
    assert meta["rows"] == "1"


# -- brand split --------------------------------------------------------------------


@respx.mock
@freeze_time("2026-11-14T09:00:00Z")
async def test_brand_split_counts_brand_non_brand_and_undisclosed_clicks(server, wired_client):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        groups = body.get("dimensionFilterGroups") or []
        operator = groups[0]["filters"][-1]["operator"] if groups else None
        clicks = {None: 100, "includingRegex": 30, "excludingRegex": 50}[operator]
        return httpx.Response(
            200, json={"rows": [{"clicks": clicks, "impressions": clicks * 10, "ctr": 0.1, "position": 5}]}
        )

    route = respx.post(QUERY_URL).mock(side_effect=handler)
    text, _ = await call_tool(
        server, "gsc_brand_split", {"site_url": SITE, "brand_terms": ["exampleco"], "months": 2}
    )

    assert route.call_count == 6
    rows = body_of(text)
    assert [r[0] for r in rows] == ["2026-09", "2026-10"]
    assert rows[0][1:5] == ["100", "30", "50", "20"]
    assert rows[0][7] == "20"
    assert meta_of(text)["period"] == "complete_months"


async def test_brand_split_needs_a_term(server, wired_client):
    text, _ = await call_tool(server, "gsc_brand_split", {"site_url": SITE, "brand_terms": [" "]})
    assert "at least one" in text


# -- the audit ----------------------------------------------------------------------


class _AuditClient:
    """Enough of the client for run_audit, with knobs for the failure cases."""

    def __init__(self, *, inspect_error=False):
        self.inspect_error = inspect_error
        self.bodies = []

    async def search_analytics(self, site_url, body):
        self.bodies.append(body)
        groups = body.get("dimensionFilterGroups")
        if groups:
            operator = groups[0]["filters"][0]["operator"]
            return {
                "rows": [{"keys": [], "clicks": 40 if operator == "includingRegex" else 50, "impressions": 1}]
            }
        if not body.get("dimensions"):
            return {"rows": [{"keys": [], "clicks": 100, "impressions": 1000, "ctr": 0.1, "position": 5}]}
        if body.get("dimensions") == ["page"]:
            return {
                "rows": [
                    {
                        "keys": ["https://example.com/a"],
                        "clicks": 50,
                        "impressions": 500,
                        "ctr": 0.1,
                        "position": 3,
                    }
                ]
            }
        return {"rows": []}

    async def list_sitemaps(self, site_url):
        return []

    async def inspect_many(self, site_url, urls):
        if self.inspect_error:
            return [{"url": url, "error": "Error 429: quota"} for url in urls]
        return [{"url": url, "result": {"indexStatusResult": {"verdict": "PASS"}}} for url in urls]


async def _audit(client, language="en"):
    return await run_audit(
        client,
        SITE,
        "2026-09-01",
        "2026-09-28",
        language=language,
        brand_terms=["exampleco"],
        write_file=False,
        settings=Settings(),
    )


async def test_failed_inspections_are_skipped_not_reported_as_problems():
    result = await _audit(_AuditClient(inspect_error=True))
    assert "indexing_problems" not in result.summary["issue_keys"]
    skipped = [item for item in result.summary["skipped_sections"] if item["section"] == "indexing"]
    assert skipped and skipped[0]["unchecked"] == 1
    assert "Error 429" not in result.html
    assert "URL Inspection failed for some pages" in result.html


async def test_the_brand_share_comes_from_every_query():
    result = await _audit(_AuditClient())
    brand = result.summary["brand"]
    assert brand["basis"] == "all_queries"
    assert brand["brand_pct"] == 40.0
    assert brand["non_brand_pct"] == 50.0
    assert brand["anonymized_pct"] == 10.0


async def test_the_report_explains_its_method_in_italian():
    result = await _audit(_AuditClient(), language="it")
    assert "Come leggere questo report" in result.html
    assert "query che Google non rende visibili" in result.html
