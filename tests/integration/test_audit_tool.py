"""The audit tool must keep working on the async client, and stay parallel."""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import httpx
import respx

from google_search_console_mcp.client import INSPECTION_BASE, WEBMASTERS_BASE
from tests.conftest import call_tool, load_fixture

SITE = "sc-domain:example.com"
QUERY_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
SITEMAPS_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/sitemaps"
INSPECT_URL = f"{INSPECTION_BASE}/urlInspection/index:inspect"

SIMULATED_LATENCY = 1.0


def row(keys, clicks, impressions, ctr, position):
    return {
        "keys": list(keys),
        "clicks": clicks,
        "impressions": impressions,
        "ctr": ctr,
        "position": position,
    }


def analytics_payload(request: httpx.Request) -> dict:
    """A small but realistic site: one brand query, one page-two opportunity."""
    dimensions = json.loads(request.content).get("dimensions", [])
    if not dimensions:
        return {"rows": [row([], 500, 20000, 0.025, 9.4)]}
    if dimensions == ["query"]:
        return {
            "rows": [
                row(["example brand"], 120, 900, 0.13, 1.4),
                row(["blue widgets"], 30, 4000, 0.0075, 12.5),
            ]
        }
    if dimensions == ["page"]:
        return {"rows": [row([f"https://example.com/p{i}"], 40 - i, 900, 0.04, 8.0) for i in range(10)]}
    if dimensions == ["device"]:
        return {
            "rows": [
                row(["MOBILE"], 300, 14000, 0.021, 10.1),
                row(["DESKTOP"], 200, 6000, 0.033, 8.2),
            ]
        }
    if dimensions == ["country"]:
        return {"rows": [row(["ita"], 480, 19000, 0.025, 9.3)]}
    if dimensions == ["date"]:
        return {"rows": [row([f"2026-08-{day:02d}"], 20, 700, 0.028, 9.0) for day in range(1, 22)]}
    return {"rows": [row(["blue widgets", "https://example.com/p1"], 10, 500, 0.02, 11.0)]}


def mock_everything(latency: float = 0.0):
    async def analytics(request: httpx.Request) -> httpx.Response:
        if latency:
            await asyncio.sleep(latency)
        return httpx.Response(200, json=analytics_payload(request))

    async def inspect(request: httpx.Request) -> httpx.Response:
        if latency:
            await asyncio.sleep(latency)
        return httpx.Response(200, json=load_fixture("inspection_pass.json"))

    async def sitemaps(request: httpx.Request) -> httpx.Response:
        if latency:
            await asyncio.sleep(latency)
        return httpx.Response(200, json=load_fixture("sitemaps.json"))

    return {
        "analytics": respx.post(QUERY_URL).mock(side_effect=analytics),
        "inspect": respx.post(INSPECT_URL).mock(side_effect=inspect),
        "sitemaps": respx.get(SITEMAPS_URL).mock(side_effect=sitemaps),
    }


@respx.mock
async def test_the_audit_writes_a_report_and_returns_its_path(server, wired_client, tmp_path):
    mock_everything()

    text, _ = await call_tool(
        server,
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "output_dir": str(tmp_path),
        },
    )

    payload = json.loads(text)
    report = tmp_path / "example_com_2026-08-01_2026-08-21.html"

    assert payload["report_path"] == str(report)
    assert payload["range"] == ["2026-08-01", "2026-08-21"]
    assert payload["previous"] == ["2026-07-11", "2026-07-31"]
    assert report.exists()

    html = report.read_text(encoding="utf-8")
    assert "example.com" in html
    assert "<html" in html


@respx.mock
async def test_the_audit_resolves_a_named_period_like_the_other_tools(server, wired_client, tmp_path):
    mock_everything()

    text, _ = await call_tool(
        server,
        "gsc_audit",
        {"site_url": SITE, "period": "last_month", "output_dir": str(tmp_path)},
    )

    payload = json.loads(text)
    assert payload["period"] == "last_month"
    assert payload["range"][0].endswith("-01")


@respx.mock
async def test_the_audit_runs_its_calls_in_parallel(server, wired_client, tmp_path, no_real_sleep):
    """19 sequential calls at 1s each would take 19s; parallel collection must not."""
    mock_everything(latency=SIMULATED_LATENCY)

    started = time.monotonic()
    await call_tool(
        server,
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "output_dir": str(tmp_path),
        },
    )
    elapsed = time.monotonic() - started

    # Two rounds of latency (analytics batch, then the inspections) plus overhead.
    assert elapsed < 8


@respx.mock
async def test_ten_inspections_with_one_second_latency_finish_quickly(server, wired_client):
    async def slow(request: httpx.Request) -> httpx.Response:
        await asyncio.sleep(SIMULATED_LATENCY)
        return httpx.Response(200, json=load_fixture("inspection_pass.json"))

    respx.post(INSPECT_URL).mock(side_effect=slow)

    started = time.monotonic()
    text, _ = await call_tool(
        server,
        "gsc_indexing_issues",
        {"site_url": SITE, "pages": [f"https://example.com/{n}" for n in range(10)]},
    )
    elapsed = time.monotonic() - started

    assert "rows=10" in text
    # Concurrency 5 means two waves of one second, not ten.
    assert elapsed < 5


@respx.mock
async def test_the_audit_can_return_the_document_inline(server, wired_client, monkeypatch):
    mock_everything()

    result = await server.call_tool(
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "output": "inline",
        },
    )
    content = getattr(result, "content", None) or (result[0] if isinstance(result, tuple) else result)

    summary = json.loads(content[0].text)
    assert "report_path" not in summary

    resource = content[1].resource
    # The field is camelCase on mcp 1.x and snake_case on 2.x.
    mime = getattr(resource, "mimeType", None) or resource.mime_type
    assert mime == "text/html"
    assert str(resource.uri).startswith("gsc-report://example_com/")
    assert resource.text.startswith("<!DOCTYPE html>")


@respx.mock
async def test_both_writes_the_file_and_returns_the_document(server, wired_client, tmp_path):
    mock_everything()

    result = await server.call_tool(
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "output": "both",
            "output_dir": str(tmp_path),
        },
    )
    content = getattr(result, "content", None) or (result[0] if isinstance(result, tuple) else result)

    summary = json.loads(content[0].text)
    assert Path(summary["report_path"]).exists()
    assert len(content) == 2


@respx.mock
async def test_the_audit_renders_in_the_requested_language(server, wired_client, tmp_path):
    mock_everything()

    text, _ = await call_tool(
        server,
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "language": "it",
            "output_dir": str(tmp_path),
        },
    )

    summary = json.loads(text)
    assert summary["language"] == "it"
    html = Path(summary["report_path"]).read_text(encoding="utf-8")
    assert '<html lang="it"' in html
    assert "Performance generale" in html


@respx.mock
async def test_explicit_brand_terms_beat_the_domain_guess(server, wired_client, tmp_path):
    mock_everything()

    text, _ = await call_tool(
        server,
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "brand_terms": ["example brand"],
            "output_dir": str(tmp_path),
        },
    )

    summary = json.loads(text)
    assert summary["brand"]["source"] == "explicit"
    assert summary["brand"]["terms"] == ["example brand"]


@respx.mock
async def test_an_unknown_section_is_refused_before_any_request(server, wired_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={}))

    text, _ = await call_tool(server, "gsc_audit", {"site_url": SITE, "sections": ["overview", "nonsense"]})

    assert route.call_count == 0
    assert "nonsense" in text


@respx.mock
async def test_inspections_can_be_switched_off(server, wired_client, tmp_path):
    routes = mock_everything()

    await call_tool(
        server,
        "gsc_audit",
        {
            "site_url": SITE,
            "date_from": "2026-08-01",
            "date_to": "2026-08-21",
            "inspect_top_pages": 0,
            "output_dir": str(tmp_path),
        },
    )

    assert routes["inspect"].call_count == 0
