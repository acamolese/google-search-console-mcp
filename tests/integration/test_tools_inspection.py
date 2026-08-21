"""Inspection, sites and sitemaps tools."""

from __future__ import annotations

import json

import httpx
import respx

from google_search_console_mcp.client import INSPECTION_BASE, WEBMASTERS_BASE
from tests.conftest import call_tool, load_fixture

SITE = "sc-domain:example.com"
INSPECT_URL = f"{INSPECTION_BASE}/urlInspection/index:inspect"
SITES_URL = f"{WEBMASTERS_BASE}/sites"
SITEMAPS_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/sitemaps"


@respx.mock
async def test_indexing_issues_returns_one_row_per_url_in_input_order(server, wired_client):
    respx.post(INSPECT_URL).mock(return_value=httpx.Response(200, json=load_fixture("inspection_pass.json")))
    pages = [f"https://example.com/{n}" for n in range(12)]

    text, _ = await call_tool(server, "gsc_indexing_issues", {"site_url": SITE, "pages": pages})

    lines = text.split("\n")
    assert "rows=12" in lines[0]
    assert "summary=PASS:12" in lines[0]
    urls = [line.split("\t")[0] for line in lines[2:]]
    assert urls == pages


@respx.mock
async def test_one_failing_url_does_not_lose_the_others(server, wired_client):
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["inspectionUrl"]
        if page.endswith("/broken"):
            return httpx.Response(403, json=load_fixture("errors", "403_permission.json"))
        return httpx.Response(200, json=load_fixture("inspection_fail.json"))

    respx.post(INSPECT_URL).mock(side_effect=handler)

    text, _ = await call_tool(
        server,
        "gsc_indexing_issues",
        {"site_url": SITE, "pages": ["https://example.com/a", "https://example.com/broken"]},
    )

    lines = text.split("\n")[2:]
    assert lines[0].split("\t")[1] == "FAIL"
    assert "Duplicate, Google chose different canonical" in lines[0]
    assert lines[1].split("\t")[1] == "ERROR"
    assert "summary=ERROR:1,FAIL:1" in text.split("\n")[0]


@respx.mock
async def test_more_than_a_hundred_urls_is_refused_without_calling_the_api(server, wired_client):
    route = respx.post(INSPECT_URL).mock(return_value=httpx.Response(200, json={}))

    text, _ = await call_tool(
        server,
        "gsc_indexing_issues",
        {"site_url": SITE, "pages": [f"https://example.com/{n}" for n in range(101)]},
    )

    assert route.call_count == 0
    assert "limit is 100" in text
    assert "2,000 per day" in text


@respx.mock
async def test_an_empty_page_list_is_refused(server, wired_client):
    text, _ = await call_tool(server, "gsc_indexing_issues", {"site_url": SITE, "pages": []})
    assert "at least one URL" in text


@respx.mock
async def test_inspect_url_returns_the_structured_payload(server, wired_client):
    respx.post(INSPECT_URL).mock(return_value=httpx.Response(200, json=load_fixture("inspection_pass.json")))

    _text, structured = await call_tool(
        server,
        "gsc_inspect_url",
        {"site_url": SITE, "page_url": "https://example.com/page"},
    )

    assert structured["verdict"] == "PASS"
    assert structured["coverage_state"] == "Submitted and indexed"
    assert structured["mobile_usability"]["verdict"] == "PASS"
    assert structured["rich_results"]["detectedItems"][0]["richResultType"] == "Product"
    assert structured["inspection_result_link"].startswith("https://search.google.com/")


@respx.mock
async def test_sites_lists_properties_with_their_type(server, wired_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    text, _ = await call_tool(server, "gsc_sites", {})

    lines = text.split("\n")
    assert "rows=3" in lines[0]
    assert lines[1] == "site_url\tpermission\ttype"
    assert lines[2] == "https://blog.example.com/\tsiteRestrictedUser\turl-prefix"
    assert "sc-domain:example.com\tsiteOwner\tdomain" in text


@respx.mock
async def test_site_details_reports_the_permission_level(server, wired_client):
    respx.get(f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com").mock(
        return_value=httpx.Response(200, json=load_fixture("site_details.json"))
    )

    text, _ = await call_tool(server, "gsc_site_details", {"site_url": SITE})

    assert "siteOwner" in text
    assert "domain" in text


@respx.mock
async def test_sitemaps_sums_the_submitted_and_indexed_counts(server, wired_client):
    respx.get(SITEMAPS_URL).mock(return_value=httpx.Response(200, json=load_fixture("sitemaps.json")))

    text, _ = await call_tool(server, "gsc_sitemaps", {"site_url": SITE})

    header, columns, first, second = text.split("\n")
    assert "total_errors=2" in header
    assert "total_warnings=3" in header
    assert columns.endswith("submitted_urls\tindexed_urls")
    assert first.split("\t")[-2:] == ["1840", "1712"]
    assert second.split("\t")[-2:] == ["920", "614"]
    assert "is_index" in columns
    assert first.split("\t")[4] == "true"


@respx.mock
async def test_a_property_with_no_sitemaps_returns_an_empty_table(server, wired_client):
    respx.get(SITEMAPS_URL).mock(return_value=httpx.Response(200, json={}))

    text, _ = await call_tool(server, "gsc_sitemaps", {"site_url": SITE})

    assert "rows=0" in text
    assert len(text.split("\n")) == 2
