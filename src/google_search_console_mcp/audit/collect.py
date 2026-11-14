"""Fetch everything the report needs, in parallel.

2.x issued nineteen calls one after another. They all go out together here, in
two waves: the analytics and sitemap calls, then the URL inspections, which are
separately rate-limited and run behind the client's semaphore.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .. import dates, insights
from ..errors import GSCError
from ..formatting import normalize_rows

logger = logging.getLogger(__name__)

# The same depth the insight tools read, so the report and the tools agree, and a
# page outside the slice is rare enough to be declared rather than assumed gone.
TOP_QUERIES = 5_000
TOP_PAGES = 5_000
QUERY_PAGE_ROWS = 25_000
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


async def _safe(coro, fallback, label: str, *, section: str, skipped: list[dict]):
    """Optional sections must not cost the caller the whole report.

    A failure is still recorded in ``skipped``: an empty section that was never
    checked must not read as a clean one.
    """
    try:
        return await coro
    except GSCError as exc:
        logger.warning("Skipping %s: %s", label, exc)
        skipped.append(
            {"section": section, "label": label, "status": exc.status, "error": str(exc.message)[:200]}
        )
        return fallback


async def _monthly_by_page(
    gsc, site_url: str, date_to: str, data_state: str, months: int, skipped: list[dict]
) -> dict:
    """Clicks per page per month, for the content-decay rule. Whole months only."""
    ranges = dates.month_ranges(date_to, months, complete_only=True)
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
                section="content_decay",
                skipped=skipped,
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


async def _brand_totals(
    gsc, site_url: str, window: dict, brand_terms: list[str], skipped: list[dict]
) -> dict | None:
    """Brand and non-brand clicks over every query, not just the top slice.

    Two filtered calls with no row limit. Queries Google anonymises match neither
    filter, so whatever the two leave out of the site total is the share that
    cannot be attributed.
    """
    pattern = insights.brand_regex(brand_terms)
    if not pattern:
        return None

    def body(operator: str) -> dict:
        return {
            **window,
            "dimensionFilterGroups": [
                {
                    "groupType": "and",
                    "filters": [{"dimension": "query", "operator": operator, "expression": pattern}],
                }
            ],
        }

    brand_rows, non_brand_rows = await asyncio.gather(
        _safe(
            _rows(gsc, site_url, body("includingRegex"), []),
            None,
            "brand totals",
            section="brand",
            skipped=skipped,
        ),
        _safe(
            _rows(gsc, site_url, body("excludingRegex"), []),
            None,
            "non-brand totals",
            section="brand",
            skipped=skipped,
        ),
    )
    if brand_rows is None or non_brand_rows is None:
        return None
    zero = {"clicks": 0, "impressions": 0}
    brand = brand_rows[0] if brand_rows else zero
    non_brand = non_brand_rows[0] if non_brand_rows else zero
    return {
        "brand_clicks": brand.get("clicks", 0),
        "brand_impressions": brand.get("impressions", 0),
        "non_brand_clicks": non_brand.get("clicks", 0),
        "non_brand_impressions": non_brand.get("impressions", 0),
        "pattern": pattern,
    }


async def collect(
    gsc,
    site_url: str,
    date_from: str,
    date_to: str,
    *,
    data_state: str = "all",
    inspect_top_pages: int = DEFAULT_INSPECT_TOP_PAGES,
    decay_months: int = DECAY_MONTHS,
    brand_terms: list[str] | None = None,
    compare: str = "previous",
    ctx: Any = None,
) -> dict:
    """Return the full dataset the issue rules and the template work from."""
    prev_from, prev_to = dates.baseline_range(date_from, date_to, compare)
    window = {"startDate": date_from, "endDate": date_to, "dataState": data_state}
    prev_window = {"startDate": prev_from, "endDate": prev_to, "dataState": data_state}

    skipped: list[dict] = []

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
        brand_totals,
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
        _safe(gsc.list_sitemaps(site_url), [], "sitemaps", section="sitemaps", skipped=skipped),
        _brand_totals(gsc, site_url, window, list(brand_terms or []), skipped),
    )
    # Google returns rows grouped by date in date order today; the chart must not
    # depend on it.
    trend.sort(key=lambda row: row.get("date", ""))

    await report_progress(ctx, 2, "Fetching month-by-month history")
    monthly = await _monthly_by_page(gsc, site_url, date_to, data_state, decay_months, skipped)

    await report_progress(ctx, 3, "Inspecting the top pages")
    indexing = await _inspect(
        gsc, site_url, _inspection_candidates(pages, prev_pages), inspect_top_pages, skipped
    )

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
        "brand_totals": brand_totals,
        "compare": compare,
        "truncated": {
            "queries": len(queries) >= TOP_QUERIES,
            "prev_queries": len(prev_queries) >= TOP_QUERIES,
            "pages": len(pages) >= TOP_PAGES,
            "prev_pages": len(prev_pages) >= TOP_PAGES,
            "query_page": len(query_page) >= QUERY_PAGE_ROWS,
        },
        "skipped_sections": skipped,
    }


def _inspection_candidates(pages: list[dict], prev_pages: list[dict]) -> list[str]:
    """Pages worth inspecting, most suspicious first.

    The top pages by clicks are indexed almost by definition. The pages that lost
    the most clicks against the baseline are where an indexing problem would show,
    so they go first; the top pages fill the remaining slots.
    """
    current = {row.get("page", ""): row.get("clicks", 0) for row in pages}
    losses = sorted(
        (
            (current.get(row.get("page", ""), 0) - row.get("clicks", 0), row.get("page", ""))
            for row in prev_pages
            if row.get("page")
        ),
    )
    ordered = [url for delta, url in losses if delta < 0]
    ordered += [row["page"] for row in pages if row.get("page")]
    return list(dict.fromkeys(ordered))


async def _inspect(gsc, site_url: str, urls: list[str], limit: int, skipped: list[dict]) -> list[dict]:
    if limit <= 0 or not urls:
        return []
    urls = urls[:limit]

    results = await gsc.inspect_many(site_url, urls)
    out = []
    failed = []
    for item in results:
        if "error" in item:
            failed.append(item)
            continue
        status = (item.get("result") or {}).get("indexStatusResult", {})
        out.append(
            {
                "url": item["url"],
                "verdict": status.get("verdict", "UNKNOWN"),
                "coverage_state": status.get("coverageState", ""),
            }
        )
    if failed:
        # A failed inspection is not a verdict: keep it out of the table and say
        # how many pages went unchecked.
        first = failed[0]["error"]
        logger.warning("URL Inspection failed for %d of %d pages: %s", len(failed), len(urls), first)
        skipped.append(
            {
                "section": "indexing",
                "label": f"URL Inspection for {len(failed)} of {len(urls)} pages",
                "status": None,
                "error": str(first)[:200],
                "unchecked": len(failed),
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
