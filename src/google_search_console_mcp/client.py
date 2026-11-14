"""Async Search Console client: retries, caching and bounded concurrency.

2.x issued synchronous `urllib` calls straight from the tool functions, which
blocked the event loop, discarded Google's error body, never retried a 503 and
re-requested identical data on every call. This module fixes all four.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import random
import time
import urllib.parse
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any

import httpx

from . import config
from .errors import GSCError

logger = logging.getLogger(__name__)

WEBMASTERS_BASE = "https://www.googleapis.com/webmasters/v3"
INSPECTION_BASE = "https://searchconsole.googleapis.com/v1"

MAX_ROW_LIMIT = 25_000
# Google may ask a client to back off for minutes. Past this, waiting inside a tool
# call only looks like a hang: fail with the hint instead.
MAX_RETRY_AFTER_SECONDS = 60.0
# How far back to look for the last day with final data. Google finalises data with
# a delay of a few days; ten covers it with room to spare.
FRESHNESS_LOOKBACK_DAYS = 10

# Cache outcomes of the requests made by the current tool call. Tools fan out
# requests with asyncio.gather, and the tasks share the list set by the caller.
_cache_log: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar("gsc_cache_log", default=None)


def start_cache_log() -> list[str]:
    """Begin collecting cache outcomes for one tool call."""
    log: list[str] = []
    _cache_log.set(log)
    return log


def encode_site(site_url: str) -> str:
    return urllib.parse.quote(site_url, safe="")


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


@dataclass
class TTLCache:
    """Small LRU with a per-entry TTL. Search Console data changes daily at best."""

    max_entries: int = config.DEFAULT_CACHE_MAX_ENTRIES
    _entries: OrderedDict[str, tuple[float, Any]] = field(default_factory=OrderedDict)
    hits: int = 0
    misses: int = 0

    def get(self, key: str) -> Any | None:
        entry = self._entries.get(key)
        if entry is None:
            self.misses += 1
            return None
        expires_at, value = entry
        if expires_at <= time.monotonic():
            del self._entries[key]
            self.misses += 1
            return None
        self._entries.move_to_end(key)
        self.hits += 1
        return value

    def set(self, key: str, value: Any, ttl: float) -> None:
        if ttl <= 0:
            return
        self._entries[key] = (time.monotonic() + ttl, value)
        self._entries.move_to_end(key)
        while len(self._entries) > self.max_entries:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()

    @property
    def size(self) -> int:
        return len(self._entries)


def cache_key(method: str, url: str, body: Any) -> str:
    payload = json.dumps(body, sort_keys=True, separators=(",", ":")) if body is not None else ""
    return hashlib.sha256(f"{method}|{url}|{payload}".encode()).hexdigest()


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class GSCClient:
    """Every Search Console call this server makes goes through here."""

    def __init__(
        self,
        provider: Any,
        http: httpx.AsyncClient,
        cache: TTLCache | None = None,
        settings: config.Settings | None = None,
    ) -> None:
        self._provider = provider
        self._http = http
        self._settings = settings or config.Settings.from_env()
        self._cache = cache if cache is not None else TTLCache(self._settings.cache_max_entries)
        self._inspect_semaphore = asyncio.Semaphore(self._settings.inspect_concurrency)
        self.requests = 0
        self.retries = 0
        self._last_cache_state = "miss"

    @property
    def last_cache_state(self) -> str:
        """`hit`, `miss` or `mixed` across the requests of the current tool call.

        Outside a tool call it falls back to the outcome of the latest request.
        """
        log = _cache_log.get()
        if not log:
            return self._last_cache_state
        states = set(log)
        return states.pop() if len(states) == 1 else "mixed"

    def _record_cache(self, state: str) -> None:
        self._last_cache_state = state
        log = _cache_log.get()
        if log is not None:
            log.append(state)

    # -- stats --------------------------------------------------------------

    @property
    def cache(self) -> TTLCache:
        return self._cache

    @property
    def provider(self) -> Any:
        return self._provider

    def stats(self) -> dict[str, Any]:
        return {
            "requests": self.requests,
            "retries": self.retries,
            "cache_hits": self._cache.hits,
            "cache_misses": self._cache.misses,
            "cache_entries": self._cache.size,
            "cache_ttl_seconds": self._settings.cache_ttl_seconds,
            "inspect_concurrency": self._settings.inspect_concurrency,
        }

    # -- transport ----------------------------------------------------------

    async def _request(
        self,
        method: str,
        url: str,
        body: dict | None = None,
        *,
        cache_ttl: float | None = None,
        no_cache: bool = False,
    ) -> dict:
        ttl = self._settings.cache_ttl_seconds if cache_ttl is None else cache_ttl
        key = cache_key(method, url, body)

        if not no_cache and ttl > 0:
            cached = self._cache.get(key)
            if cached is not None:
                self._record_cache("hit")
                return cached
        self._record_cache("miss")

        data = await self._request_with_retries(method, url, body)

        if not no_cache and ttl > 0:
            self._cache.set(key, data, ttl)
        return data

    async def _request_with_retries(self, method: str, url: str, body: dict | None) -> dict:
        attempts = self._settings.max_retries
        last_error: GSCError | None = None

        for attempt in range(1, attempts + 1):
            token = await self._provider.token()
            headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
            self.requests += 1
            try:
                response = await self._http.request(method, url, json=body, headers=headers)
            except httpx.HTTPError as exc:
                last_error = GSCError.transport(exc)
            else:
                if response.status_code < 400:
                    return _decode(response)
                last_error = GSCError.from_response(response.status_code, response.text)
                if not last_error.retryable:
                    raise last_error
                retry_after = _retry_after_seconds(response)
                if retry_after is not None and retry_after > MAX_RETRY_AFTER_SECONDS:
                    last_error.hint = (
                        f"Google asked to wait {int(retry_after)} seconds before retrying. "
                        "Try again later, or lower the number of parallel calls."
                    )
                    raise last_error
                if attempt < attempts:
                    self.retries += 1
                    await asyncio.sleep(self._backoff(attempt, retry_after))
                continue

            if attempt < attempts:
                self.retries += 1
                await asyncio.sleep(self._backoff(attempt, None))

        raise last_error or GSCError(0, "The request failed for an unknown reason.")

    def _backoff(self, attempt: int, retry_after: float | None) -> float:
        if retry_after is not None:
            return retry_after
        base = self._settings.retry_base_delay_seconds * (2 ** (attempt - 1))
        # Jitter keeps parallel inspection calls from retrying in lockstep.
        return base + random.uniform(0, base / 2)  # noqa: S311 - backoff jitter, not crypto

    # -- endpoints ----------------------------------------------------------

    async def list_sites(self, *, no_cache: bool = False) -> list[dict]:
        data = await self._request("GET", f"{WEBMASTERS_BASE}/sites", no_cache=no_cache)
        return data.get("siteEntry", [])

    async def get_site(self, site_url: str, *, no_cache: bool = False) -> dict:
        url = f"{WEBMASTERS_BASE}/sites/{encode_site(site_url)}"
        return await self._request("GET", url, no_cache=no_cache)

    async def search_analytics(self, site_url: str, body: dict, *, no_cache: bool = False) -> dict:
        url = f"{WEBMASTERS_BASE}/sites/{encode_site(site_url)}/searchAnalytics/query"
        return await self._request("POST", url, body, no_cache=no_cache)

    async def latest_final_date(self, site_url: str, today: str, *, search_type: str = "web") -> str | None:
        """The last day for which Search Console has final data, or None.

        The most recent days are partial for a while, so a window that ends today
        holds fewer complete days than the window it is compared with. Answered
        from the cache like any other call.
        """
        from datetime import date, timedelta

        end = date.fromisoformat(today)
        body = {
            "startDate": (end - timedelta(days=FRESHNESS_LOOKBACK_DAYS)).isoformat(),
            "endDate": end.isoformat(),
            "dimensions": ["date"],
            "type": search_type,
            "dataState": "final",
            "rowLimit": FRESHNESS_LOOKBACK_DAYS + 1,
        }
        data = await self.search_analytics(site_url, body)
        found = []
        for row in data.get("rows", []):
            keys = row.get("keys") or []
            try:
                found.append(date.fromisoformat(str(keys[0])))
            except (IndexError, ValueError):
                continue
        return max(found).isoformat() if found else None

    async def list_sitemaps(self, site_url: str, *, no_cache: bool = False) -> list[dict]:
        url = f"{WEBMASTERS_BASE}/sites/{encode_site(site_url)}/sitemaps"
        data = await self._request("GET", url, no_cache=no_cache)
        return data.get("sitemap", [])

    async def inspect_url(self, site_url: str, page_url: str, *, no_cache: bool = False) -> dict:
        url = f"{INSPECTION_BASE}/urlInspection/index:inspect"
        body = {"inspectionUrl": page_url, "siteUrl": site_url}
        data = await self._request(
            "POST",
            url,
            body,
            cache_ttl=self._settings.inspect_cache_ttl_seconds,
            no_cache=no_cache,
        )
        return data.get("inspectionResult", {})

    async def inspect_many(
        self,
        site_url: str,
        page_urls: list[str],
        *,
        no_cache: bool = False,
    ) -> list[dict]:
        """Inspect many URLs concurrently, capped by the inspection semaphore.

        Results come back in input order. A URL that fails yields an `error` entry
        instead of aborting the batch: a single 403 on one page should not cost the
        caller the other 99 results.
        """

        async def one(page_url: str) -> dict:
            async with self._inspect_semaphore:
                try:
                    result = await self.inspect_url(site_url, page_url, no_cache=no_cache)
                except GSCError as exc:
                    return {"url": page_url, "error": str(exc)}
                return {"url": page_url, "result": result}

        return list(await asyncio.gather(*(one(url) for url in page_urls)))


def _decode(response: httpx.Response) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise GSCError(
            response.status_code,
            "Google returned a response that is not JSON.",
            reason="badResponse",
        ) from exc
    return data if isinstance(data, dict) else {"data": data}


def _retry_after_seconds(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return max(0.0, float(raw))
    except ValueError:
        # The header may carry an HTTP date; fall back to normal backoff.
        return None


# ---------------------------------------------------------------------------
# Process-wide singletons
# ---------------------------------------------------------------------------

_http_client: httpx.AsyncClient | None = None
_client: GSCClient | None = None


def build_http_client(settings: config.Settings) -> httpx.AsyncClient:
    timeout = httpx.Timeout(settings.timeout_seconds, connect=settings.connect_timeout_seconds)
    return httpx.AsyncClient(timeout=timeout, follow_redirects=True)


def get_client() -> GSCClient:
    """The shared client. One `AsyncClient` and one credential provider per process."""
    global _http_client, _client
    if _client is None:
        from .auth import CredentialProvider

        settings = config.Settings.from_env()
        _http_client = build_http_client(settings)
        _client = GSCClient(CredentialProvider(settings), _http_client, settings=settings)
    return _client


async def close_client() -> None:
    global _http_client, _client
    if _http_client is not None:
        await _http_client.aclose()
    _http_client = None
    _client = None


def reset_client() -> None:
    """Drop the singletons without awaiting. For tests only."""
    global _http_client, _client
    _http_client = None
    _client = None
