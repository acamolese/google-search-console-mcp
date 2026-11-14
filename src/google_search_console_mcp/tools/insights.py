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
    Compare,
    DateFrom,
    DateTo,
    Days,
    Filters,
    Period,
    ResponseFormat,
    RowLimit,
    SearchType,
    SiteUrl,
    build_filter_groups,
    check_compare,
    check_format,
    check_site_url,
    check_type,
    clamp_row_limit,
    client,
    resolve_window,
    tool_annotations,
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


def _meta(site_url: str, start: str, end: str, label: str, th: Thresholds | None, rows: int, **extra) -> dict:
    meta = {
        "site": site_url,
        "range": f"{start}..{end}",
        "period": label,
        "rows": rows,
        **(th.as_meta() if th is not None else {}),
        "cache": client().last_cache_state,
    }
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


def _scope(search_type: str, filters: list[dict] | None) -> dict:
    """Meta keys describing a narrowed analysis, omitted when nothing was narrowed."""
    out: dict[str, Any] = {}
    if search_type != "web":
        out["type"] = search_type
    if filters:
        out["filters"] = ";".join(
            f"{f.get('dimension')}:{f.get('operator', 'equals')}:{f.get('expression', '')}" for f in filters
        )
    return out


def register(mcp) -> None:
    settings = Settings.from_env()

    async def _fetch(
        site_url,
        start,
        end,
        dimensions,
        row_limit=ANALYSIS_ROWS,
        no_cache=False,
        *,
        search_type="web",
        filter_groups=None,
    ):
        return await _search(
            site_url,
            start,
            end,
            dimensions,
            row_limit=row_limit,
            search_type=search_type,
            data_state=settings.data_state,
            filter_groups=filter_groups,
            no_cache=no_cache,
        )

    @mcp.tool(annotations=tool_annotations("Quick wins"))
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
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
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

        search_type = check_type(type)
        groups = build_filter_groups(filters, "and")
        raw = await _fetch(
            site_url, start, end, ["query"], no_cache=no_cache, search_type=search_type, filter_groups=groups
        )
        rows = normalize_rows(raw, ["query"])
        th = _thresholds(rows, thresholds)
        capped: dict[str, Any] = {}
        found = insights.quick_wins(
            rows,
            th,
            min_position=min_position,
            max_position=max_position,
            target_position=target_position,
            limit=clamp_row_limit(row_limit, capped),
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
            truncated=len(raw) >= ANALYSIS_ROWS,
            total_uplift=sum(item["uplift"] for item in found),
            **capped,
            **_scope(search_type, filters),
            source="insights.quick_wins",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("CTR gaps"))
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
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
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

        search_type = check_type(type)
        groups = build_filter_groups(filters, "and")
        raw = await _fetch(
            site_url, start, end, [entity], no_cache=no_cache, search_type=search_type, filter_groups=groups
        )
        rows = normalize_rows(raw, [entity])
        th = _thresholds(rows, thresholds)
        capped: dict[str, Any] = {}
        found = insights.ctr_gaps(
            rows,
            th,
            entity=entity,
            max_position=max_position,
            gap_ratio=gap_ratio,
            limit=clamp_row_limit(row_limit, capped),
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
            truncated=len(raw) >= ANALYSIS_ROWS,
            total_uplift=sum(item["uplift"] for item in found),
            **capped,
            **_scope(search_type, filters),
            source="insights.ctr_gaps",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Keyword cannibalisation"))
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
        brand_terms: Annotated[
            list[str] | None,
            Field(description="Brand words: queries containing them are left out (whole words)."),
        ] = None,
        thresholds: Thresholds_ = None,
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Queries where several pages of the site compete for the same result.

        Leaves out brand queries (pass `brand_terms`), queries where one page sits
        in the top three with most of the clicks, and queries below the impression
        threshold. Reads up to 25,000 query/page pairs; the meta says when the tail
        was cut off.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        search_type = check_type(type)
        groups = build_filter_groups(filters, "and")
        raw = await _fetch(
            site_url,
            start,
            end,
            ["query", "page"],
            PAIR_ROWS,
            no_cache,
            search_type=search_type,
            filter_groups=groups,
        )
        rows = normalize_rows(raw, ["query", "page"])
        th = _thresholds(rows, thresholds)
        capped: dict[str, Any] = {}
        found = insights.cannibalization(
            rows,
            th,
            min_pages=min_pages,
            min_share=min_share,
            limit=clamp_row_limit(row_limit, capped),
            brand_terms=brand_terms or [],
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
            brand_terms=",".join(brand_terms) if brand_terms else None,
            **capped,
            **_scope(search_type, filters),
            source="insights.cannibalization",
        )
        columns = ["query", "page_count", "clicks", "impressions", "pages"]
        return render(flat, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Traffic drops"))
    @tool_errors
    async def gsc_traffic_drops(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        min_drop_pct: Annotated[float, Field(description="Minimum click loss, in percent.")] = 20.0,
        compare: Compare = "previous",
        thresholds: Thresholds_ = None,
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Pages that lost clicks against the baseline, each with a likely cause.

        `diagnosis` tells a ranking loss from fewer impressions at a stable position,
        a collapsed CTR and a page gone from the results: they need different fixes,
        and both periods' numbers are in the row. Rolling windows end on the last day
        with final data (`data_through` in the meta); `compare=year` handles seasonality.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        search_type = check_type(type)
        mode = check_compare(compare)
        groups = build_filter_groups(filters, "and")
        start, end, label, data_through = await resolve_window(
            site_url, date_from, date_to, days, period, search_type=search_type
        )
        prev_start, prev_end = dates.baseline_range(start, end, mode)

        current_raw, previous_raw = await asyncio.gather(
            _fetch(
                site_url,
                start,
                end,
                ["page"],
                no_cache=no_cache,
                search_type=search_type,
                filter_groups=groups,
            ),
            _fetch(
                site_url,
                prev_start,
                prev_end,
                ["page"],
                no_cache=no_cache,
                search_type=search_type,
                filter_groups=groups,
            ),
        )
        current = normalize_rows(current_raw, ["page"])
        previous = normalize_rows(previous_raw, ["page"])
        current_truncated = len(current_raw) >= ANALYSIS_ROWS
        th = _thresholds(current + previous, thresholds)
        capped: dict[str, Any] = {}
        found = insights.traffic_drops(
            current,
            previous,
            th,
            min_drop_pct=min_drop_pct,
            limit=clamp_row_limit(row_limit, capped),
            current_complete=not current_truncated,
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
            compare=mode,
            data_through=data_through,
            baseline_warning=dates.baseline_warning(prev_start),
            truncated=current_truncated or len(previous_raw) >= ANALYSIS_ROWS,
            lost_clicks=sum(item["clicks_delta"] for item in found),
            **capped,
            **_scope(search_type, filters),
            source="insights.traffic_drops",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Content decay"))
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
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Pages sliding down month after month.

        A period comparison hides this: a page that halves over six months never
        shows a sharp drop in any single month-on-month check. Only whole calendar
        months are compared, so the month in progress is left out (`last_month` in
        the meta). One query per month runs in parallel.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        search_type = check_type(type)
        groups = build_filter_groups(filters, "and")
        months = max(2, min(15, int(months or 6)))
        _start, end, label = dates.resolve_range(date_to=date_to, days=1)
        ranges = dates.month_ranges(end, months, complete_only=True)

        monthly = await asyncio.gather(
            *(
                _fetch(
                    site_url,
                    start,
                    stop,
                    ["page"],
                    no_cache=no_cache,
                    search_type=search_type,
                    filter_groups=groups,
                )
                for _month, start, stop in ranges
            )
        )

        series: dict[str, list[tuple[str, int]]] = {}
        all_rows: list[dict] = []
        for (month, _start, _stop), raw in zip(ranges, monthly, strict=True):
            rows = normalize_rows(raw, ["page"])
            all_rows.extend(rows)
            for row in rows:
                series.setdefault(row["page"], []).append((month, row["clicks"]))
        complete = {page: values for page, values in series.items() if len(values) == len(ranges)}
        truncated_months = [
            month for (month, _a, _b), raw in zip(ranges, monthly, strict=True) if len(raw) >= ANALYSIS_ROWS
        ]

        th = _thresholds(all_rows, thresholds)
        capped: dict[str, Any] = {}
        found = insights.content_decay(
            complete,
            th,
            consecutive_months=consecutive_months,
            min_peak_clicks=min_peak_clicks,
            limit=clamp_row_limit(row_limit, capped),
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
        # The decay rule applies its own two cut-offs, not the adaptive thresholds.
        meta = _meta(
            site_url,
            ranges[0][1],
            ranges[-1][2],
            "complete_months",
            None,
            len(found),
            months=months,
            last_month=ranges[-1][0],
            partial_month_excluded=ranges[-1][2] != end,
            consecutive_months=consecutive_months,
            min_peak_clicks=min_peak_clicks,
            pages_with_full_history=len(complete),
            truncated_months=",".join(truncated_months) if truncated_months else None,
            **capped,
            **_scope(search_type, filters),
            source="insights.content_decay",
        )
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Alerts"))
    @tool_errors
    async def gsc_alerts(
        site_url: SiteUrl,
        window_days: Annotated[int, Field(description="Length of the window to compare.")] = 7,
        date_to: DateTo = "",
        compare: Compare = "previous",
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
        row_limit: RowLimit = 50,
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """What changed sharply enough to be worth a message today.

        Compares the last `window_days` against the window before (or a year
        earlier) across queries and pages, and returns only movements past fixed
        alerting rules, listed in the meta: lost positions, collapsed CTR, dropped
        or vanished pages. The window ends on the last day with final data.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        search_type = check_type(type)
        mode = check_compare(compare)
        groups = build_filter_groups(filters, "and")
        window = max(1, min(90, int(window_days or 7)))
        start, end, label, data_through = await resolve_window(
            site_url, date_to=date_to, days=window, search_type=search_type
        )
        prev_start, prev_end = dates.baseline_range(start, end, mode)

        def fetch(a, b, dims):
            return _fetch(
                site_url, a, b, dims, no_cache=no_cache, search_type=search_type, filter_groups=groups
            )

        cq, pq, cp, pp = await asyncio.gather(
            fetch(start, end, ["query"]),
            fetch(prev_start, prev_end, ["query"]),
            fetch(start, end, ["page"]),
            fetch(prev_start, prev_end, ["page"]),
        )
        current_queries = normalize_rows(cq, ["query"])
        previous_queries = normalize_rows(pq, ["query"])
        current_pages = normalize_rows(cp, ["page"])
        previous_pages = normalize_rows(pp, ["page"])

        capped: dict[str, Any] = {}
        found = insights.alerts(
            current_queries,
            previous_queries,
            current_pages,
            previous_pages,
            limit=clamp_row_limit(row_limit, capped),
            current_pages_complete=len(cp) < ANALYSIS_ROWS,
        )
        meta = _meta(
            site_url,
            start,
            end,
            label,
            None,
            len(found),
            previous_range=f"{prev_start}..{prev_end}",
            compare=mode,
            data_through=data_through,
            baseline_warning=dates.baseline_warning(prev_start),
            high=sum(1 for item in found if item["severity"] == "high"),
            truncated=any(len(raw) >= ANALYSIS_ROWS for raw in (cq, pq, cp, pp)),
            rules=",".join(f"{k}:{v}" for k, v in insights.ALERT_RULES.items()),
            **capped,
            **_scope(search_type, filters),
            source="insights.alerts",
        )
        columns = ["severity", "type", "entity", "before", "after", "delta"]
        return render(found, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Portfolio overview"))
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
        all_sites = [entry.get("siteUrl", "") for entry in entries if entry.get("siteUrl")]
        sites = all_sites[: max(1, int(limit or 30))]
        data_through = None
        if sites and not date_to:
            # Every property shares Google's processing delay, so one lookup on the
            # first property anchors them all to the last day with final data.
            start, end, label, data_through = await resolve_window(sites[0], days=days or 28)
            prev_start, prev_end = dates.previous_range(start, end)

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
            "total_properties": len(all_sites),
            "truncated": len(sites) < len(all_sites) or None,
            "data_through": data_through,
            "cache": client().last_cache_state,
            "source": "insights.portfolio",
        }
        meta = {k: v for k, v in meta.items() if v is not None}
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

    @mcp.tool(annotations=tool_annotations("Brand and non-brand split"))
    @tool_errors
    async def gsc_brand_split(
        site_url: SiteUrl,
        brand_terms: Annotated[
            list[str],
            Field(description="Words that make a query branded. Matched as whole words, spaces tolerated."),
        ],
        months: Annotated[int, Field(description="Complete calendar months to read (1-15).")] = 12,
        date_to: DateTo = "",
        filters: Filters = None,
        type: SearchType = "web",  # noqa: A002 - mirrors the API field name
        response_format: ResponseFormat = "tsv",
        no_cache: bool = False,
    ) -> str:
        """Brand, non-brand and undisclosed clicks, month by month.

        Computed over every query with server-side regex filters, so no row limit
        applies. `anonymized` is what Google counts but never shows as a query; it
        belongs to neither side. Whole months only: the month in progress is left out.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        search_type = check_type(type)
        pattern = insights.brand_regex(brand_terms or [])
        if not pattern:
            raise GSCError(400, "brand_terms needs at least one non-empty word.", reason="badRequest")
        base = build_filter_groups(filters, "and") or []
        months = max(1, min(15, int(months or 12)))
        _start, end, _label = dates.resolve_range(date_to=date_to, days=1)
        earliest = dates.earliest_available(dates.today_utc()).isoformat()
        ranges = [r for r in dates.month_ranges(end, months, complete_only=True) if r[1] >= earliest]

        def groups(operator: str | None) -> list[dict] | None:
            if operator is None:
                return base or None
            brand_filter = {"dimension": "query", "operator": operator, "expression": pattern}
            if base:
                return [{"groupType": "and", "filters": [*base[0]["filters"], brand_filter]}]
            return [{"groupType": "and", "filters": [brand_filter]}]

        async def month_totals(start: str, stop: str) -> list[list[dict]]:
            return await asyncio.gather(
                *(
                    _fetch(
                        site_url,
                        start,
                        stop,
                        [],
                        1,
                        no_cache,
                        search_type=search_type,
                        filter_groups=groups(op),
                    )
                    for op in (None, "includingRegex", "excludingRegex")
                )
            )

        results = await asyncio.gather(*(month_totals(start, stop) for _m, start, stop in ranges))

        def first(raw: list[dict]) -> dict:
            return raw[0] if raw else {}

        def share(part: int, total: int) -> float:
            return round(part / total * 100, 1) if total else 0.0

        rows = []
        for (month, _start, _stop), (total_raw, brand_raw, non_brand_raw) in zip(
            ranges, results, strict=True
        ):
            total, brand, non_brand = first(total_raw), first(brand_raw), first(non_brand_raw)
            clicks = int(total.get("clicks", 0) or 0)
            brand_clicks = int(brand.get("clicks", 0) or 0)
            non_brand_clicks = int(non_brand.get("clicks", 0) or 0)
            anonymized = max(0, clicks - brand_clicks - non_brand_clicks)
            rows.append(
                {
                    "month": month,
                    "clicks": clicks,
                    "brand_clicks": brand_clicks,
                    "non_brand_clicks": non_brand_clicks,
                    "anonymized_clicks": anonymized,
                    "brand_pct": share(brand_clicks, clicks),
                    "non_brand_pct": share(non_brand_clicks, clicks),
                    "anonymized_pct": share(anonymized, clicks),
                    "brand_impressions": int(brand.get("impressions", 0) or 0),
                    "non_brand_impressions": int(non_brand.get("impressions", 0) or 0),
                }
            )

        meta = {
            "site": site_url,
            "range": f"{ranges[0][1]}..{ranges[-1][2]}" if ranges else "",
            "period": "complete_months",
            "rows": len(rows),
            "brand_terms": ",".join(brand_terms),
            "pattern": pattern,
            "cache": client().last_cache_state,
            **_scope(search_type, filters),
            "source": "insights.brand_split",
        }
        columns = [
            "month",
            "clicks",
            "brand_clicks",
            "non_brand_clicks",
            "anonymized_clicks",
            "brand_pct",
            "non_brand_pct",
            "anonymized_pct",
            "brand_impressions",
            "non_brand_impressions",
        ]
        return render(rows, columns, meta, response_format)
