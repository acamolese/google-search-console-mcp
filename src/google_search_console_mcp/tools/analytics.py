"""Search Analytics tools: the performance report, the overview and period comparison."""

from __future__ import annotations

import asyncio
from typing import Annotated, Any

from pydantic import Field

from .. import dates
from ..config import Settings
from ..formatting import columns_for, normalize_rows, render
from ..models import Overview, Totals, build_delta, pct_change
from ._common import (
    DataState,
    DateFrom,
    DateTo,
    Days,
    NoCache,
    Period,
    ResponseFormat,
    RowLimit,
    SiteUrl,
    annotations,
    base_meta,
    build_filter_groups,
    check_aggregation,
    check_format,
    check_site_url,
    check_type,
    clamp_row_limit,
    client,
    parse_dimensions,
    tool_errors,
)

# Google documents the v3 body in lowerCamelCase, but the HOUR dimension and the
# hourly data state were introduced with the newer enum spelling.
UPPERCASE_DIMENSIONS = {"hour": "HOUR"}
DATA_STATES = {"all": "all", "final": "final", "hourly_all": "HOURLY_ALL"}


def _data_state(requested: str, dimensions: list[str], settings: Settings) -> str:
    if "hour" in dimensions:
        return DATA_STATES["hourly_all"]
    value = (requested or settings.data_state).strip().lower()
    return DATA_STATES.get(value, DATA_STATES["all"])


def _api_dimensions(dimensions: list[str]) -> list[str]:
    return [UPPERCASE_DIMENSIONS.get(d, d) for d in dimensions]


async def _search(
    site_url: str,
    date_from: str,
    date_to: str,
    dimensions: list[str],
    *,
    row_limit: int,
    start_row: int = 0,
    search_type: str = "web",
    data_state: str = "all",
    filter_groups: list[dict] | None = None,
    aggregation_type: str = "auto",
    no_cache: bool = False,
) -> list[dict]:
    body: dict[str, Any] = {
        "startDate": date_from,
        "endDate": date_to,
        "type": search_type,
        "dataState": data_state,
        "rowLimit": row_limit,
    }
    if dimensions:
        body["dimensions"] = _api_dimensions(dimensions)
    if start_row:
        body["startRow"] = start_row
    if filter_groups:
        body["dimensionFilterGroups"] = filter_groups
    if aggregation_type and aggregation_type != "auto":
        body["aggregationType"] = aggregation_type

    data = await client().search_analytics(site_url, body, no_cache=no_cache)
    return data.get("rows", [])


async def totals_for(
    site_url: str,
    date_from: str,
    date_to: str,
    *,
    search_type: str = "web",
    data_state: str = "all",
    no_cache: bool = False,
) -> Totals:
    """Site-wide totals: one query with no dimensions."""
    rows = await _search(
        site_url,
        date_from,
        date_to,
        [],
        row_limit=1,
        search_type=search_type,
        data_state=data_state,
        no_cache=no_cache,
    )
    if not rows:
        return Totals()
    row = rows[0]
    return Totals(
        clicks=int(row.get("clicks", 0) or 0),
        impressions=int(row.get("impressions", 0) or 0),
        ctr=round(float(row.get("ctr", 0) or 0), 4),
        position=round(float(row.get("position", 0) or 0), 1),
    )


def register(mcp) -> None:
    settings = Settings.from_env()

    @mcp.tool(annotations=annotations("Search Console performance report"))
    @tool_errors
    async def gsc_query(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        dimensions: Annotated[
            str,
            Field(
                description=(
                    "Comma-separated dimensions: query, page, country, device, date, "
                    "searchAppearance, hour. `hour` covers only the last 10 days."
                )
            ),
        ] = "query",
        type: Annotated[  # noqa: A002 - mirrors the API field name
            str,
            Field(description="web, image, video, news, discover or googleNews."),
        ] = "web",
        data_state: DataState = "",
        filters: Annotated[
            list[dict] | None,
            Field(
                description=(
                    "List of {dimension, operator, expression}. Operators: equals, "
                    "notEquals, contains, notContains, includingRegex, excludingRegex."
                )
            ),
        ] = None,
        filter_group_type: Annotated[
            str,
            Field(description="Only `and` is supported by the API within one group."),
        ] = "and",
        aggregation_type: Annotated[
            str,
            Field(description="auto, byPage or byProperty."),
        ] = "auto",
        row_limit: RowLimit = 100,
        start_row: Annotated[int, Field(description="Zero-based pagination offset.")] = 0,
        response_format: ResponseFormat = "tsv",
        no_cache: NoCache = False,
    ) -> str:
        """Query the Search Analytics report: clicks, impressions, CTR, position.

        This is the general-purpose tool. With no dates it covers the last 28 days
        ending today (UTC), with data_state=all so today's partial data is included,
        matching what the Search Console UI shows.

        Example: site_url="sc-domain:example.com", dimensions="query,page",
        period="last_28_days", row_limit=100.

        Returns a `# meta ...` line then a TSV table, or JSON with `meta` and `rows`.
        The meta names the exact range, the row count, whether more rows exist and
        the `start_row` to pass next.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        dimension_list = parse_dimensions(dimensions)
        search_type = check_type(type)
        aggregation = check_aggregation(aggregation_type)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        if "hour" in dimension_list:
            dates.validate_hourly_range(start, end)

        meta = base_meta(site_url, start, end, period=label, type=search_type)
        state = _data_state(data_state, dimension_list, settings)
        limit = clamp_row_limit(row_limit, meta)
        groups = build_filter_groups(filters, filter_group_type)

        raw = await _search(
            site_url,
            start,
            end,
            dimension_list,
            row_limit=limit,
            start_row=max(0, int(start_row or 0)),
            search_type=search_type,
            data_state=state,
            filter_groups=groups,
            aggregation_type=aggregation,
            no_cache=no_cache,
        )
        rows = normalize_rows(raw, dimension_list)

        meta.update(
            {
                "data_state": state,
                "dimensions": ",".join(dimension_list),
                "rows": len(rows),
                "has_more": len(rows) == limit,
                "next_start_row": (start_row or 0) + len(rows) if len(rows) == limit else None,
                "cache": client().last_cache_state,
                "source": "searchanalytics.query",
            }
        )
        return render(rows, columns_for(dimension_list), meta, response_format)

    @mcp.tool(annotations=annotations("Search Console performance overview"))
    @tool_errors
    async def gsc_performance_overview(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        type: Annotated[  # noqa: A002 - mirrors the API field name
            str,
            Field(description="web, image, video, news, discover or googleNews."),
        ] = "web",
        data_state: DataState = "",
        compare_previous: Annotated[
            bool,
            Field(description="Also fetch the equally long preceding period."),
        ] = True,
        no_cache: NoCache = False,
    ) -> Overview:
        """Site totals for a period, compared with the preceding one by default.

        Start here: it answers "is the site up or down" in one call, with the
        percentage change on every metric. `position_delta` is negative when the
        average position improves.
        """
        site_url = check_site_url(site_url)
        search_type = check_type(type)
        start, end, _label = dates.resolve_range(date_from, date_to, days, period)
        state = _data_state(data_state, [], settings)

        if not compare_previous:
            current = await totals_for(
                site_url, start, end, search_type=search_type, data_state=state, no_cache=no_cache
            )
            return Overview(
                site_url=site_url,
                date_from=start,
                date_to=end,
                data_state=state,
                current=current,
            )

        prev_start, prev_end = dates.previous_range(start, end)
        current, previous = await asyncio.gather(
            totals_for(site_url, start, end, search_type=search_type, data_state=state, no_cache=no_cache),
            totals_for(
                site_url,
                prev_start,
                prev_end,
                search_type=search_type,
                data_state=state,
                no_cache=no_cache,
            ),
        )
        return Overview(
            site_url=site_url,
            date_from=start,
            date_to=end,
            data_state=state,
            current=current,
            previous=previous,
            previous_range=[prev_start, prev_end],
            delta=build_delta(current, previous),
        )

    @mcp.tool(annotations=annotations("Compare two periods"))
    @tool_errors
    async def gsc_compare_periods(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        prev_date_from: Annotated[
            str,
            Field(
                description=(
                    "Baseline start YYYY-MM-DD. Defaults to the equally long period "
                    "ending the day before date_from."
                )
            ),
        ] = "",
        prev_date_to: Annotated[str, Field(description="Baseline end YYYY-MM-DD.")] = "",
        days: Days = None,
        period: Period = "",
        dimension: Annotated[
            str,
            Field(description="One of query, page, country, device, searchAppearance."),
        ] = "query",
        row_limit: RowLimit = 100,
        min_impressions: Annotated[
            int,
            Field(description="Drop rows below this impression count in both periods."),
        ] = 0,
        response_format: ResponseFormat = "tsv",
        no_cache: NoCache = False,
    ) -> str:
        """Join two periods on one dimension and rank the rows by click delta.

        Answers "what changed" without the model diffing two tables by hand. Rows
        present in only one period are kept, with zeros on the missing side; the
        biggest movers in both directions are returned, worst first. The meta counts
        how many rows gained and how many lost clicks.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        dimension_list = parse_dimensions(dimension)[:1]
        start, end, label = dates.resolve_range(date_from, date_to, days, period)

        if prev_date_from or prev_date_to:
            prev_start, prev_end, _ = dates.resolve_range(prev_date_from, prev_date_to)
        else:
            prev_start, prev_end = dates.previous_range(start, end)

        meta = base_meta(site_url, start, end, period=label)
        limit = clamp_row_limit(row_limit, meta)
        state = _data_state("", dimension_list, settings)

        # 5,000 rows per side so the join sees more than the top slice before ranking.
        fetch_limit = 5_000
        current_raw, previous_raw = await asyncio.gather(
            _search(
                site_url,
                start,
                end,
                dimension_list,
                row_limit=fetch_limit,
                data_state=state,
                no_cache=no_cache,
            ),
            _search(
                site_url,
                prev_start,
                prev_end,
                dimension_list,
                row_limit=fetch_limit,
                data_state=state,
                no_cache=no_cache,
            ),
        )

        key = dimension_list[0]
        current = {row[key]: row for row in normalize_rows(current_raw, dimension_list)}
        previous = {row[key]: row for row in normalize_rows(previous_raw, dimension_list)}

        merged = []
        for name in set(current) | set(previous):
            now = current.get(name)
            before = previous.get(name)
            now_clicks = now["clicks"] if now else 0
            before_clicks = before["clicks"] if before else 0
            now_impressions = now["impressions"] if now else 0
            before_impressions = before["impressions"] if before else 0
            if max(now_impressions, before_impressions) < min_impressions:
                continue
            merged.append(
                {
                    key: name,
                    "clicks": now_clicks,
                    "prev_clicks": before_clicks,
                    "clicks_delta": now_clicks - before_clicks,
                    "clicks_delta_pct": pct_change(now_clicks, before_clicks),
                    "impressions": now_impressions,
                    "prev_impressions": before_impressions,
                    "impressions_delta": now_impressions - before_impressions,
                    "ctr": now["ctr"] if now else 0.0,
                    "prev_ctr": before["ctr"] if before else 0.0,
                    "position": now["position"] if now else 0.0,
                    "prev_position": before["position"] if before else 0.0,
                }
            )

        losers = sum(1 for row in merged if row["clicks_delta"] < 0)
        winners = sum(1 for row in merged if row["clicks_delta"] > 0)
        # Keep the biggest movers in either direction, then read them worst-first.
        merged.sort(key=lambda row: abs(row["clicks_delta"]), reverse=True)
        rows = sorted(merged[:limit], key=lambda row: row["clicks_delta"])

        meta.update(
            {
                "previous_range": f"{prev_start}..{prev_end}",
                "dimension": key,
                "data_state": state,
                "compared": len(merged),
                "rows": len(rows),
                "winners": winners,
                "losers": losers,
                "min_impressions": min_impressions or None,
                "cache": client().last_cache_state,
                "source": "searchanalytics.query",
            }
        )
        columns = [
            key,
            "clicks",
            "prev_clicks",
            "clicks_delta",
            "clicks_delta_pct",
            "impressions",
            "prev_impressions",
            "impressions_delta",
            "ctr",
            "prev_ctr",
            "position",
            "prev_position",
        ]
        return render(rows, columns, meta, response_format)
