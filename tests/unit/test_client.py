"""Retries, caching and bounded concurrency, all against a mocked transport."""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest
import respx

from google_search_console_mcp.client import (
    INSPECTION_BASE,
    WEBMASTERS_BASE,
    GSCClient,
    TTLCache,
    cache_key,
)
from google_search_console_mcp.errors import GSCError
from tests.conftest import load_fixture

SITES_URL = f"{WEBMASTERS_BASE}/sites"
QUERY_URL = f"{WEBMASTERS_BASE}/sites/sc-domain%3Aexample.com/searchAnalytics/query"
INSPECT_URL = f"{INSPECTION_BASE}/urlInspection/index:inspect"


@respx.mock
async def test_the_bearer_token_is_sent(gsc_client, fake_provider):
    route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    await gsc_client.list_sites()

    assert route.calls[0].request.headers["Authorization"] == "Bearer fake-access-token"
    assert fake_provider.calls == 1


@respx.mock
async def test_a_503_is_retried_and_then_succeeds(gsc_client):
    route = respx.get(SITES_URL).mock(
        side_effect=[
            httpx.Response(503, json=load_fixture("errors", "503_backend.json")),
            httpx.Response(200, json=load_fixture("sites.json")),
        ]
    )

    sites = await gsc_client.list_sites()

    assert len(sites) == 3
    assert route.call_count == 2
    assert gsc_client.retries == 1


@respx.mock
async def test_retry_after_is_honoured(gsc_client, no_real_sleep):
    respx.get(SITES_URL).mock(
        side_effect=[
            httpx.Response(
                429,
                json=load_fixture("errors", "429_too_many.json"),
                headers={"Retry-After": "7"},
            ),
            httpx.Response(200, json=load_fixture("sites.json")),
        ]
    )

    await gsc_client.list_sites()

    assert no_real_sleep == [7.0]


@respx.mock
async def test_a_non_numeric_retry_after_falls_back_to_backoff(gsc_client, no_real_sleep):
    respx.get(SITES_URL).mock(
        side_effect=[
            httpx.Response(429, json={}, headers={"Retry-After": "Wed, 21 Aug 2026 07:28:00 GMT"}),
            httpx.Response(200, json=load_fixture("sites.json")),
        ]
    )

    await gsc_client.list_sites()

    assert no_real_sleep and no_real_sleep[0] != 7.0


@respx.mock
async def test_a_persistent_429_gives_up_after_four_attempts(gsc_client):
    route = respx.get(SITES_URL).mock(
        return_value=httpx.Response(429, json=load_fixture("errors", "429_too_many.json"))
    )

    with pytest.raises(GSCError) as excinfo:
        await gsc_client.list_sites()

    assert route.call_count == 4
    assert excinfo.value.retryable is True
    assert excinfo.value.status == 429


@respx.mock
async def test_the_daily_quota_error_is_not_retried(gsc_client):
    route = respx.get(SITES_URL).mock(
        return_value=httpx.Response(403, json=load_fixture("errors", "403_quota_daily.json"))
    )

    with pytest.raises(GSCError) as excinfo:
        await gsc_client.list_sites()

    assert route.call_count == 1
    assert excinfo.value.retryable is False
    assert "Daily quota" in excinfo.value.hint


@respx.mock
async def test_a_permission_error_is_not_retried_and_explains_the_format(gsc_client):
    route = respx.get(SITES_URL).mock(
        return_value=httpx.Response(403, json=load_fixture("errors", "403_permission.json"))
    )

    with pytest.raises(GSCError) as excinfo:
        await gsc_client.list_sites()

    assert route.call_count == 1
    assert "sc-domain:" in excinfo.value.hint


@respx.mock
async def test_a_transport_error_is_retried_and_then_reported(gsc_client):
    route = respx.get(SITES_URL).mock(side_effect=httpx.ConnectTimeout("timed out"))

    with pytest.raises(GSCError) as excinfo:
        await gsc_client.list_sites()

    assert route.call_count == 4
    assert excinfo.value.retryable is True
    assert excinfo.value.status == 0


@respx.mock
async def test_an_identical_request_is_served_from_the_cache(gsc_client):
    route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    first = await gsc_client.list_sites()
    assert gsc_client.last_cache_state == "miss"
    second = await gsc_client.list_sites()

    assert route.call_count == 1
    assert first == second
    assert gsc_client.last_cache_state == "hit"


@respx.mock
async def test_no_cache_bypasses_the_cache(gsc_client):
    route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    await gsc_client.list_sites()
    await gsc_client.list_sites(no_cache=True)

    assert route.call_count == 2


@respx.mock
async def test_different_bodies_are_cached_separately(gsc_client):
    route = respx.post(QUERY_URL).mock(return_value=httpx.Response(200, json={"rows": []}))

    await gsc_client.search_analytics("sc-domain:example.com", {"startDate": "2026-08-01"})
    await gsc_client.search_analytics("sc-domain:example.com", {"startDate": "2026-08-02"})
    await gsc_client.search_analytics("sc-domain:example.com", {"startDate": "2026-08-01"})

    assert route.call_count == 2


@respx.mock
async def test_a_zero_ttl_disables_the_cache(fake_provider, http_client):
    from google_search_console_mcp.config import Settings

    client = GSCClient(
        fake_provider,
        http_client,
        settings=Settings(cache_ttl_seconds=0, retry_base_delay_seconds=0.0),
    )
    route = respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    await client.list_sites()
    await client.list_sites()

    assert route.call_count == 2


@respx.mock
async def test_inspect_many_keeps_input_order_and_isolates_failures(gsc_client):
    def handler(request: httpx.Request) -> httpx.Response:
        page = json.loads(request.content)["inspectionUrl"]
        if page.endswith("/broken"):
            return httpx.Response(403, json=load_fixture("errors", "403_permission.json"))
        return httpx.Response(200, json=load_fixture("inspection_pass.json"))

    respx.post(INSPECT_URL).mock(side_effect=handler)

    urls = [f"https://example.com/{n}" for n in range(5)] + ["https://example.com/broken"]
    results = await gsc_client.inspect_many("sc-domain:example.com", urls)

    assert [r["url"] for r in results] == urls
    assert all("result" in r for r in results[:5])
    assert "error" in results[-1]
    assert "sc-domain:" in results[-1]["error"]


@respx.mock
async def test_inspections_never_exceed_the_configured_concurrency(fake_provider, http_client):
    from google_search_console_mcp.config import Settings

    client = GSCClient(
        fake_provider,
        http_client,
        settings=Settings(inspect_concurrency=5, cache_ttl_seconds=0, retry_base_delay_seconds=0.0),
    )

    in_flight = 0
    peak = 0

    async def handler(request: httpx.Request) -> httpx.Response:
        nonlocal in_flight, peak
        in_flight += 1
        peak = max(peak, in_flight)
        await asyncio.sleep(0)
        in_flight -= 1
        return httpx.Response(200, json=load_fixture("inspection_pass.json"))

    respx.post(INSPECT_URL).mock(side_effect=handler)

    urls = [f"https://example.com/{n}" for n in range(12)]
    results = await client.inspect_many("sc-domain:example.com", urls)

    assert len(results) == 12
    assert peak <= 5


@respx.mock
async def test_a_non_json_response_is_reported_clearly(gsc_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, text="<html>hello</html>"))

    with pytest.raises(GSCError, match="not JSON"):
        await gsc_client.list_sites()


@respx.mock
async def test_stats_track_requests_retries_and_cache(gsc_client):
    respx.get(SITES_URL).mock(
        side_effect=[
            httpx.Response(503, json={}),
            httpx.Response(200, json=load_fixture("sites.json")),
        ]
    )

    await gsc_client.list_sites()
    await gsc_client.list_sites()

    stats = gsc_client.stats()
    assert stats["requests"] == 2
    assert stats["retries"] == 1
    assert stats["cache_hits"] == 1
    assert stats["cache_misses"] == 1


def test_the_cache_key_depends_on_method_url_and_body():
    assert cache_key("GET", "u", None) != cache_key("POST", "u", None)
    assert cache_key("POST", "u", {"a": 1}) != cache_key("POST", "u", {"a": 2})
    # Key order in the body must not produce a different key.
    assert cache_key("POST", "u", {"a": 1, "b": 2}) == cache_key("POST", "u", {"b": 2, "a": 1})


def test_the_cache_expires_entries():
    cache = TTLCache(max_entries=4)
    cache.set("k", "v", ttl=100)
    assert cache.get("k") == "v"

    cache.set("expired", "v", ttl=-1)
    assert cache.get("expired") is None


def test_the_cache_evicts_the_least_recently_used_entry():
    cache = TTLCache(max_entries=2)
    cache.set("a", 1, ttl=100)
    cache.set("b", 2, ttl=100)
    cache.get("a")  # "a" becomes the most recently used
    cache.set("c", 3, ttl=100)

    assert cache.get("b") is None
    assert cache.get("a") == 1
    assert cache.get("c") == 3
