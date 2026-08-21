"""Fetch everything the report needs, in parallel.

2.x issued nineteen calls one after another. They all go out together here, in
two waves: the analytics and sitemap calls, then the URL inspections, which are
separately rate-limited and run behind the client's semaphore.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import dates
from ..errors import GSCError
from ..formatting import normalize_rows

logger = logging.getLogger(__name__)

TOP_QUERIES = 500
TOP_PAGES = 500
QUERY_PAGE_ROWS = 5_000
COUNTRIES = 15
TREND_ROWS = 1_000
DEFAULT_INSPECT_TOP_PAGES = 10
DECAY_MONTHS = 6

PROGRESS_STEPS = 5


async def _rows(gsc, site_url: str, body: dict, dimensions: list[str]) -> list[dict]:
    data = await gsc.search_analytics(site_url, body)
    return normalize_rows(data.get("rows", []), dimensions)


async def _totals(gsc, site_url: str, date_from: str, date_to: str, data_state: str) -> dict:
    rows = await _rows(
        gsc,
        site_url,
        {"startDate": date_from, "endDate": date_to, "dataState": data_state},
        [],
    )
    if not rows:
        return {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0}
    return rows[0]


async def _safe(coro, fallback, label: str):
    """Optional sections must not cost the caller the whole report."""
    try:
        return await coro
    except GSCError as exc:
        logger.warning("Skipping %s: %s", label, exc)
        return fallback


async def _monthly_by_page(gsc, site_url: str, date_to: str, data_state: str, months: int) -> dict:
    """Clicks per page per month, for the content-decay rule."""
    ranges = dates.month_ranges(date_to, months)
    results = await asyncio.gather(
        *(
            _safe(
                _rows(
                    gsc,
                    site_url,
                    {
                        "startDate": start,
                        "endDate": end,
                        "dimensions": ["page"],
                        "rowLimit": 1_000,
                        "dataState": data_state,
                    },
                    ["page"],
                ),
                [],
                f"monthly page data for {label}",
            )
            for label, start, end in ranges
        )
    )

    series: dict[str, list[tuple[str, int]]] = {}
    for (label, _start, _end), rows in zip(ranges, results, strict=True):
        for row in rows:
            series.setdefault(row["page"], []).append((label, row["clicks"]))
    # Only pages present in every month can show a consecutive decline.
    return {page: months_data for page, months_data in series.items() if len(months_data) == len(ranges)}


async def collect(
    gsc,
    site_url: str,
    date_from: str,
    date_to: str,
    *,
    data_state: str = "all",
    inspect_top_pages: int = DEFAULT_INSPECT_TOP_PAGES,
    decay_months: int = DECAY_MONTHS,
    ctx: Any = None,
) -> dict:
    """Return the full dataset the issue rules and the template work from."""
    prev_from, prev_to = dates.previous_range(date_from, date_to)
    window = {"startDate": date_from, "endDate": date_to, "dataState": data_state}
    prev_window = {"startDate": prev_from, "endDate": prev_to, "dataState": data_state}

    await report_progress(ctx, 1, "Fetching performance data")

    (
        current,
        previous,
        queries,
        prev_queries,
        pages,
        prev_pages,
        devices,
        countries,
        trend,
        query_page,
        sitemaps,
    ) = await asyncio.gather(
        _totals(gsc, site_url, date_from, date_to, data_state),
        _totals(gsc, site_url, prev_from, prev_to, data_state),
        _rows(gsc, site_url, {**window, "dimensions": ["query"], "rowLimit": TOP_QUERIES}, ["query"]),
        _rows(gsc, site_url, {**prev_window, "dimensions": ["query"], "rowLimit": TOP_QUERIES}, ["query"]),
        _rows(gsc, site_url, {**window, "dimensions": ["page"], "rowLimit": TOP_PAGES}, ["page"]),
        _rows(gsc, site_url, {**prev_window, "dimensions": ["page"], "rowLimit": TOP_PAGES}, ["page"]),
        _rows(gsc, site_url, {**window, "dimensions": ["device"]}, ["device"]),
        _rows(gsc, site_url, {**window, "dimensions": ["country"], "rowLimit": COUNTRIES}, ["country"]),
        _rows(gsc, site_url, {**window, "dimensions": ["date"], "rowLimit": TREND_ROWS}, ["date"]),
        _rows(
            gsc,
            site_url,
            {**window, "dimensions": ["query", "page"], "rowLimit": QUERY_PAGE_ROWS},
            ["query", "page"],
        ),
        _safe(gsc.list_sitemaps(site_url), [], "sitemaps"),
    )

    await report_progress(ctx, 2, "Fetching month-by-month history")
    monthly = await _monthly_by_page(gsc, site_url, date_to, data_state, decay_months)

    await report_progress(ctx, 3, "Inspecting the top pages")
    indexing = await _inspect(gsc, site_url, pages, inspect_top_pages)

    await report_progress(ctx, 4, "Analysing")

    return {
        "site_url": site_url,
        "date_from": date_from,
        "date_to": date_to,
        "prev_from": prev_from,
        "prev_to": prev_to,
        "data_state": data_state,
        "current": current,
        "previous": previous,
        "queries": queries,
        "prev_queries": prev_queries,
        "pages": pages,
        "prev_pages": prev_pages,
        "devices": devices,
        "countries": countries,
        "trend": trend,
        "query_page": query_page,
        "monthly_by_page": monthly,
        "sitemaps": sitemaps,
        "indexing": indexing,
    }


async def _inspect(gsc, site_url: str, pages: list[dict], limit: int) -> list[dict]:
    if limit <= 0 or not pages:
        return []
    urls = [row["page"] for row in pages[:limit] if row.get("page")]
    if not urls:
        return []

    results = await gsc.inspect_many(site_url, urls)
    out = []
    for item in results:
        if "error" in item:
            out.append({"url": item["url"], "verdict": "ERROR", "coverage_state": item["error"][:160]})
            continue
        status = (item.get("result") or {}).get("indexStatusResult", {})
        out.append(
            {
                "url": item["url"],
                "verdict": status.get("verdict", "UNKNOWN"),
                "coverage_state": status.get("coverageState", ""),
            }
        )
    return out


async def report_progress(ctx: Any, step: int, message: str) -> None:
    if ctx is None:
        return
    report = getattr(ctx, "report_progress", None)
    if report is None:
        return
    try:
        await report(step, PROGRESS_STEPS, message)
    except Exception:  # noqa: BLE001 - progress is best-effort, never fatal
        logger.debug("Progress reporting failed", exc_info=True)
