"""One tool per analysis question.

Each of these used to require the model to pull raw rows and reason over them,
which burned context and produced answers nobody could check. Here the rule runs
server-side and the response carries the numbers that triggered it, plus the
thresholds that were applied.
"""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from pydantic import Field

from .. import dates, insights
from ..config import Settings
from ..errors import GSCError
from ..formatting import normalize_rows, render
from ..insights.thresholds import Thresholds
from ._common import (
    DateFrom,
    DateTo,
    Days,
    Period,
    ResponseFormat,
    RowLimit,
    SiteUrl,
    annotations,
    check_format,
    check_site_url,
    clamp_row_limit,
    client,
    tool_errors,
)
from .analytics import _search, totals_for

# Rules need the long tail, not the top slice: a query ranked 14th with volume is
# invisible in a 100-row report.
ANALYSIS_ROWS = 5_000
# Cannibalisation needs query+page pairs, which multiply fast.
PAIR_ROWS = 25_000
PORTFOLIO_CONCURRENCY = 5

Thresholds_ = Annotated[
    dict | None,
    Field(
        description=(
            "Override the adaptive thresholds: min_impressions, min_clicks, "
            "high_visibility_impressions, ctr_curve."
        )
    ),
]


def _thresholds(rows: list[dict], overrides: dict | None) -> Thresholds:
    return Thresholds.from_rows(rows, overrides)


def _meta(site_url: str, start: str, end: str, label: str, th: Thresholds, rows: int, **extra) -> dict:
    meta = {
        "site": site_url,
        "range": f"{start}..{end}",
        "period": label,
        "rows": rows,
        **th.as_meta(),
        "cache": client().last_cache_state,
    }
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


def register(mcp) -> None:
    settings = Settings.from_env()

    async def _fetch(site_url, start, end, dimensions, row_limit=ANALYSIS_ROWS, no_cache=False):
        return await _search(
            site_url,
            start,
            end,
            dimensions,
            row_limit=row_limit,
            data_state=settings.data_state,
            no_cache=no_cache,
        )

    @mcp.tool(annotations=annotations("Quick wins"))
    @tool_errors
    async def gsc_quick_wins(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        min_position: Annotated[float, Field(description="Ignore queries above this position.")] = 4.0,
        max_position: Annotated[float, Field(description="Ignore queries below this position.")] = 20.0,
        target_position: Annotated[int, Field(description="Position to size the opportunity against.")] = 3,
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Queries close enough to the top that a push would pay off.

        Ranked by the clicks each query would gain at `target_position`, not by
        impressions: a big query already near its ceiling is not an opportunity.
        The meta reports the thresholds that were applied.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        raw = await _fetch(site_url, start, end, ["query"], no_cache=no_cache)
        rows = normalize_rows(raw, ["query"])
        th = _thresholds(rows, thresholds)
        found = insights.quick_wins(
            rows,
            th,
            min_position=min_position,
            max_position=max_position,
            target_position=target_position,
            limit=clamp_row_limit(row_limit, {}),
        )
        columns = [
            "query",
            "clicks",
            "impressions",
            "ctr",
            "position",
            "target_position",
            "potential_clicks",
            "uplift",
        ]
        meta = _meta(
            site_url,
            start,
            end,
            label,
            th,
            len(found),
            analysed=len(rows),
            total_uplift=sum(item["uplift"] for item in found),
            source="insights.quick_wins",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=annotations("CTR gaps"))
    @tool_errors
    async def gsc_ctr_gaps(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        entity: Annotated[str, Field(description="Analyse by `page` (default) or by `query`.")] = "page",
        max_position: Annotated[
            float, Field(description="Only consider rows at or above this position.")
        ] = 10.0,
        gap_ratio: Annotated[
            float,
            Field(description="Flag rows whose CTR is below this fraction of the expected CTR."),
        ] = 0.6,
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Rows that rank well but are clicked far less than their position implies.

        The snippet, not the ranking, is the problem, which makes these the
        cheapest fixes available. `expected_ctr` is what a result at that position
        normally earns.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        if entity not in ("page", "query"):
            raise GSCError(400, "entity must be 'page' or 'query'.", reason="badRequest")
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        raw = await _fetch(site_url, start, end, [entity], no_cache=no_cache)
        rows = normalize_rows(raw, [entity])
        th = _thresholds(rows, thresholds)
        found = insights.ctr_gaps(
            rows,
            th,
            entity=entity,
            max_position=max_position,
            gap_ratio=gap_ratio,
            limit=clamp_row_limit(row_limit, {}),
        )
        columns = [
            entity,
            "clicks",
            "impressions",
            "ctr",
            "expected_ctr",
            "position",
            "potential_clicks",
            "uplift",
        ]
        meta = _meta(
            site_url,
            start,
            end,
            label,
            th,
            len(found),
            entity=entity,
            analysed=len(rows),
            total_uplift=sum(item["uplift"] for item in found),
            source="insights.ctr_gaps",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=annotations("Keyword cannibalisation"))
    @tool_errors
    async def gsc_cannibalization(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        min_pages: Annotated[int, Field(description="Minimum competing pages per query.")] = 2,
        min_share: Annotated[
            float,
            Field(description="A page must hold this share of the query's impressions to count."),
        ] = 0.10,
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Queries where several pages of the site compete for the same result.

        Reads one page of up to 25,000 query/page pairs; on a very large property
        the tail is cut off, and the meta says how many pairs were analysed.
        Each row lists the competing pages with their own clicks and positions.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        raw = await _fetch(site_url, start, end, ["query", "page"], PAIR_ROWS, no_cache)
        rows = normalize_rows(raw, ["query", "page"])
        th = _thresholds(rows, thresholds)
        found = insights.cannibalization(
            rows, th, min_pages=min_pages, min_share=min_share, limit=clamp_row_limit(row_limit, {})
        )

        flat = [
            {
                "query": group["query"],
                "page_count": group["page_count"],
                "clicks": group["clicks"],
                "impressions": group["impressions"],
                "pages": " | ".join(
                    f"{page['page']} ({page['clicks']} clicks, pos {page['position']})"
                    for page in group["pages"]
                ),
            }
            for group in found
        ]
        meta = _meta(
            site_url,
            start,
            end,
            label,
            th,
            len(flat),
            pairs_analysed=len(rows),
            truncated=len(rows) >= PAIR_ROWS,
            source="insights.cannibalization",
        )
        columns = ["query", "page_count", "clicks", "impressions", "pages"]
        return render(flat, columns, meta, response_format)

    @mcp.tool(annotations=annotations("Traffic drops"))
    @tool_errors
    async def gsc_traffic_drops(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        min_drop_pct: Annotated[float, Field(description="Minimum click loss, in percent.")] = 20.0,
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Pages that lost clicks against the baseline, each with a likely cause.

        `diagnosis` separates a ranking loss from falling demand, a collapsed CTR
        and a page that disappeared: the four need different fixes, and the raw
        numbers for both periods are in the row so the call can be checked.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)
        prev_start, prev_end = dates.previous_range(start, end)

        current_raw, previous_raw = await asyncio.gather(
            _fetch(site_url, start, end, ["page"], no_cache=no_cache),
            _fetch(site_url, prev_start, prev_end, ["page"], no_cache=no_cache),
        )
        current = normalize_rows(current_raw, ["page"])
        previous = normalize_rows(previous_raw, ["page"])
        th = _thresholds(current + previous, thresholds)
        found = insights.traffic_drops(
            current, previous, th, min_drop_pct=min_drop_pct, limit=clamp_row_limit(row_limit, {})
        )
        columns = [
            "page",
            "clicks",
            "prev_clicks",
            "clicks_delta",
            "clicks_delta_pct",
            "impressions",
            "prev_impressions",
            "ctr",
            "prev_ctr",
            "position",
            "prev_position",
            "diagnosis",
        ]
        meta = _meta(
            site_url,
            start,
            end,
            label,
            th,
            len(found),
            previous_range=f"{prev_start}..{prev_end}",
            lost_clicks=sum(item["clicks_delta"] for item in found),
            source="insights.traffic_drops",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=annotations("Content decay"))
    @tool_errors
    async def gsc_content_decay(
        site_url: SiteUrl,
        date_to: DateTo = "",
        months: Annotated[int, Field(description="How many months of history to read (2-16).")] = 6,
        consecutive_months: Annotated[
            int, Field(description="Months of uninterrupted decline required.")
        ] = 3,
        min_peak_clicks: Annotated[
            int, Field(description="Ignore pages that never reached this many clicks in a month.")
        ] = 30,
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Pages sliding down month after month.

        A period comparison hides this: a page that halves over six months never
        shows a sharp drop in any single month-on-month check. One query per month
        runs in parallel.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        months = max(2, min(16, int(months or 6)))
        _start, end, label = dates.resolve_range(date_to=date_to, days=1)
        ranges = dates.month_ranges(end, months)

        monthly = await asyncio.gather(
            *(_fetch(site_url, start, stop, ["page"], no_cache=no_cache) for _month, start, stop in ranges)
        )

        series: dict[str, list[tuple[str, int]]] = {}
        all_rows: list[dict] = []
        for (month, _start, _stop), raw in zip(ranges, monthly, strict=True):
            rows = normalize_rows(raw, ["page"])
            all_rows.extend(rows)
            for row in rows:
                series.setdefault(row["page"], []).append((month, row["clicks"]))
        complete = {page: values for page, values in series.items() if len(values) == len(ranges)}

        th = _thresholds(all_rows, thresholds)
        found = insights.content_decay(
            complete,
            th,
            consecutive_months=consecutive_months,
            min_peak_clicks=min_peak_clicks,
            limit=clamp_row_limit(row_limit, {}),
        )
        columns = [
            "page",
            "peak_month",
            "peak_clicks",
            "last_month",
            "last_clicks",
            "lost_clicks",
            "decay_pct",
        ]
        meta = _meta(
            site_url,
            ranges[0][1],
            end,
            label,
            th,
            len(found),
            months=months,
            pages_with_full_history=len(complete),
            source="insights.content_decay",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=annotations("Alerts"))
    @tool_errors
    async def gsc_alerts(
        site_url: SiteUrl,
        window_days: Annotated[int, Field(description="Length of the window to compare.")] = 7,
        date_to: DateTo = "",
        thresholds: Thresholds_ = None,
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """What changed sharply enough to be worth a message today.

        Compares the last `window_days` against the window before it across both
        queries and pages, and returns only movements past the alerting rules:
        lost positions, collapsed CTR, dropped or vanished pages.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        window = max(1, min(90, int(window_days or 7)))
        start, end, label = dates.resolve_range(date_to=date_to, days=window)
        prev_start, prev_end = dates.previous_range(start, end)

        cq, pq, cp, pp = await asyncio.gather(
            _fetch(site_url, start, end, ["query"], no_cache=no_cache),
            _fetch(site_url, prev_start, prev_end, ["query"], no_cache=no_cache),
            _fetch(site_url, start, end, ["page"], no_cache=no_cache),
            _fetch(site_url, prev_start, prev_end, ["page"], no_cache=no_cache),
        )
        current_queries = normalize_rows(cq, ["query"])
        previous_queries = normalize_rows(pq, ["query"])
        current_pages = normalize_rows(cp, ["page"])
        previous_pages = normalize_rows(pp, ["page"])

        th = _thresholds(current_queries + current_pages, thresholds)
        found = insights.alerts(
            current_queries,
            previous_queries,
            current_pages,
            previous_pages,
            th,
            limit=clamp_row_limit(row_limit, {}),
        )
        meta = _meta(
            site_url,
            start,
            end,
            label,
            th,
            len(found),
            previous_range=f"{prev_start}..{prev_end}",
            high=sum(1 for item in found if item["severity"] == "high"),
            source="insights.alerts",
        )
        columns = ["severity", "type", "entity", "before", "after", "delta"]
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=annotations("Portfolio overview"))
    @tool_errors
    async def gsc_portfolio(
        limit: Annotated[int, Field(description="How many properties to check.")] = 30,
        days: Days = 28,
        date_to: DateTo = "",
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Every accessible property at a glance, ranked worst first.

        One row per property with the current period, the previous one and a health
        flag: critical below -30% clicks, warning below -15%. Use it to decide which
        property to look at before running anything else.
        """
        response_format = check_format(response_format)
        start, end, label = dates.resolve_range(date_to=date_to, days=days or 28)
        prev_start, prev_end = dates.previous_range(start, end)

        entries = await client().list_sites(no_cache=no_cache)
        sites = [entry.get("siteUrl", "") for entry in entries if entry.get("siteUrl")]
        sites = sites[: max(1, int(limit or 30))]

        semaphore = asyncio.Semaphore(PORTFOLIO_CONCURRENCY)

        async def one(site: str) -> dict[str, Any]:
            async with semaphore:
                try:
                    current, previous = await asyncio.gather(
                        totals_for(site, start, end, data_state=settings.data_state, no_cache=no_cache),
                        totals_for(
                            site,
                            prev_start,
                            prev_end,
                            data_state=settings.data_state,
                            no_cache=no_cache,
                        ),
                    )
                except GSCError as exc:
                    return {"site_url": site, "health": "error", "error": str(exc)[:160]}

            delta = insights.pct_change(current.clicks, previous.clicks)
            if delta is None:
                health = "no_baseline"
            elif delta <= -30:
                health = "critical"
            elif delta <= -15:
                health = "warning"
            else:
                health = "ok"
            return {
                "site_url": site,
                "clicks": current.clicks,
                "prev_clicks": previous.clicks,
                "clicks_delta_pct": delta,
                "impressions": current.impressions,
                "prev_impressions": previous.impressions,
                "ctr": current.ctr,
                "position": current.position,
                "health": health,
                "error": "",
            }

        rows = list(await asyncio.gather(*(one(site) for site in sites)))
        order = {"error": 0, "critical": 1, "warning": 2, "no_baseline": 3, "ok": 4}
        rows.sort(key=lambda row: (order.get(row["health"], 9), row.get("clicks_delta_pct") or 0))

        meta = {
            "range": f"{start}..{end}",
            "previous_range": f"{prev_start}..{prev_end}",
            "period": label,
            "rows": len(rows),
            "critical": sum(1 for row in rows if row["health"] == "critical"),
            "warning": sum(1 for row in rows if row["health"] == "warning"),
            "cache": client().last_cache_state,
            "source": "insights.portfolio",
        }
        columns = [
            "site_url",
            "clicks",
            "prev_clicks",
            "clicks_delta_pct",
            "impressions",
            "prev_impressions",
            "ctr",
            "position",
            "health",
            "error",
        ]
        return render(rows, columns, meta, response_format)
