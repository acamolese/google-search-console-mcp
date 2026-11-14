"""Helpers every tool module shares."""

from __future__ import annotations

import functools
import inspect
from collections.abc import Sequence
from typing import Annotated, Any

from pydantic import Field

from .. import client as client_module
from .. import dates
from .._compat import ToolAnnotations, ToolError
from ..client import MAX_ROW_LIMIT, GSCClient
from ..errors import GSCError

# Nothing this server exposes writes to Search Console: the OAuth scope is
# read-only and no tool asks for more.
READ_ONLY = {
    "readOnlyHint": True,
    "destructiveHint": False,
    "idempotentHint": True,
    "openWorldHint": True,
}

# One call may not ask for more than this; use start_row to page through the rest.
MAX_ROWS_PER_CALL = 1_000
MAX_INSPECT_URLS = 100

VALID_FORMATS = ("tsv", "json")
VALID_TYPES = ("web", "image", "video", "news", "discover", "googleNews")
VALID_DIMENSIONS = ("query", "page", "country", "device", "date", "searchAppearance", "hour")
VALID_OPERATORS = (
    "equals",
    "notEquals",
    "contains",
    "notContains",
    "includingRegex",
    "excludingRegex",
)
VALID_AGGREGATIONS = ("auto", "byPage", "byProperty")


SiteUrl = Annotated[
    str,
    Field(
        description=(
            "`sc-domain:example.com` for a domain property, or `https://example.com/` "
            "with the trailing slash for a URL-prefix property. Call gsc_sites if unsure."
        )
    ),
]
DateFrom = Annotated[str, Field(description="Start date YYYY-MM-DD. Overrides period and days.")]
DateTo = Annotated[str, Field(description="End date YYYY-MM-DD. Defaults to today.")]
Days = Annotated[int | None, Field(description="Rolling window length ending today.")]
Period = Annotated[
    str,
    Field(
        description=(
            "Named range: last_7_days, last_28_days, last_3_months, last_month, this_month, last_16_months."
        )
    ),
]
DataState = Annotated[
    str,
    Field(description="`all` (default, includes today's partial data) or `final`."),
]
RowLimit = Annotated[int, Field(description="Rows returned, capped at 1000.")]
SearchType = Annotated[
    str,
    Field(description="web, image, video, news, discover or googleNews."),
]
Filters = Annotated[
    list[dict] | None,
    Field(
        description=(
            "Narrow the data first: list of {dimension, operator, expression}, e.g. "
            '{"dimension":"page","operator":"contains","expression":"/blog/"}. '
            "Dimensions: query, page, country, device, searchAppearance. Operators: equals, "
            "notEquals, contains, notContains, includingRegex, excludingRegex. All must match."
        )
    ),
]
Compare = Annotated[
    str,
    Field(
        description=(
            "Baseline: `previous` (the equally long period before) or `year` "
            "(the same period a year earlier; whole months map to the same months)."
        )
    ),
]
ResponseFormat = Annotated[str, Field(description="`tsv` (default, compact) or `json`.")]
NoCache = Annotated[bool, Field(description="Bypass the response cache for this call.")]


def tool_annotations(title: str) -> ToolAnnotations:
    # Not named `annotations`: that name is taken by `from __future__ import annotations`
    # in every module that would import it.
    return ToolAnnotations(title=title, **READ_ONLY)


def tool_errors(func):
    """Turn a GSCError into a ToolError so the client sees `isError` plus the hint."""

    if inspect.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            client_module.start_cache_log()
            try:
                return await func(*args, **kwargs)
            except GSCError as exc:
                raise ToolError(str(exc)) from exc

        return async_wrapper

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GSCError as exc:
            raise ToolError(str(exc)) from exc

    return wrapper


def client() -> GSCClient:
    # Resolved through the module so tests can swap the shared client.
    return client_module.get_client()


def check_site_url(site_url: str) -> str:
    site_url = (site_url or "").strip()
    if not site_url:
        raise GSCError(
            400,
            "site_url is required.",
            reason="badRequest",
            hint="Use `sc-domain:example.com` for a domain property or "
            "`https://example.com/` for a URL-prefix property. Call gsc_sites for the exact list.",
        )
    return site_url


def check_format(response_format: str) -> str:
    value = (response_format or "tsv").strip().lower()
    if value not in VALID_FORMATS:
        raise GSCError(
            400,
            f"response_format must be one of {', '.join(VALID_FORMATS)}, got {response_format!r}.",
            reason="badRequest",
        )
    return value


def clamp_row_limit(row_limit: int, meta: dict, cap: int = MAX_ROWS_PER_CALL) -> int:
    """Cap the row count and say so in the meta rather than silently truncating."""
    requested = int(row_limit or 0)
    if requested <= 0:
        requested = 100
    if requested > cap:
        meta["row_limit_capped_from"] = requested
        return cap
    return min(requested, MAX_ROW_LIMIT)


def parse_dimensions(dimensions: str) -> list[str]:
    raw = [d.strip() for d in (dimensions or "").split(",") if d.strip()]
    if not raw:
        return ["query"]
    normalized = []
    for dimension in raw:
        match = next((v for v in VALID_DIMENSIONS if v.lower() == dimension.lower()), None)
        if match is None:
            raise GSCError(
                400,
                f"Unknown dimension {dimension!r}. Valid dimensions: {', '.join(VALID_DIMENSIONS)}.",
                reason="badRequest",
            )
        normalized.append(match)
    return normalized


def build_filter_groups(filters: Sequence[dict] | None, group_type: str) -> list[dict] | None:
    """Translate the tool-level filter list into `dimensionFilterGroups`."""
    if not filters:
        return None
    parsed = []
    for entry in filters:
        if not isinstance(entry, dict):
            raise GSCError(
                400,
                "Each filter must be an object with dimension, operator and expression.",
                reason="badRequest",
            )
        dimension = entry.get("dimension", "")
        if not str(dimension).strip():
            raise GSCError(
                400,
                f"Filter {entry!r} has no `dimension`. Use query, page, country, device or searchAppearance.",
                reason="badRequest",
            )
        if str(dimension).strip().lower() in ("date", "hour"):
            raise GSCError(
                400,
                "Dates are filtered with date_from and date_to, not with a filter.",
                reason="badRequest",
            )
        operator = entry.get("operator", "equals")
        expression = entry.get("expression", "")
        if operator not in VALID_OPERATORS:
            raise GSCError(
                400,
                f"Unknown filter operator {operator!r}. Valid operators: {', '.join(VALID_OPERATORS)}.",
                reason="badRequest",
            )
        parsed.append(
            {
                "dimension": parse_dimensions(dimension)[0],
                "operator": operator,
                "expression": expression,
            }
        )
    group = (group_type or "and").strip().lower()
    if group != "and":
        raise GSCError(
            400,
            "filter_group_type only accepts 'and': the API combines the filters of one group with AND.",
            reason="badRequest",
            hint="For an OR on one dimension use a single includingRegex filter, e.g. `a|b`.",
        )
    return [{"groupType": group, "filters": parsed}]


def check_type(value: str) -> str:
    resolved = (value or "web").strip()
    match = next((v for v in VALID_TYPES if v.lower() == resolved.lower()), None)
    if match is None:
        raise GSCError(
            400,
            f"Unknown type {value!r}. Valid values: {', '.join(VALID_TYPES)}.",
            reason="badRequest",
        )
    return match


def check_aggregation(value: str) -> str:
    resolved = (value or "auto").strip()
    match = next((v for v in VALID_AGGREGATIONS if v.lower() == resolved.lower()), None)
    if match is None:
        raise GSCError(
            400,
            f"Unknown aggregation_type {value!r}. Valid values: {', '.join(VALID_AGGREGATIONS)}.",
            reason="badRequest",
        )
    return match


def base_meta(site_url: str, date_from: str, date_to: str, **extra: Any) -> dict:
    meta = {"site": site_url, "range": f"{date_from}..{date_to}"}
    meta.update({k: v for k, v in extra.items() if v is not None})
    return meta


async def resolve_window(
    site_url: str,
    date_from: str = "",
    date_to: str = "",
    days: int | None = None,
    period: str = "",
    *,
    search_type: str = "web",
) -> tuple[str, str, str, str | None]:
    """Resolve a range for a tool that compares two periods.

    A rolling window with no explicit end is anchored to the last day with final
    data, so both sides hold the same number of complete days. Returns
    `(start, end, label, data_through)`; `data_through` is None when the range was
    left as asked.
    """
    if date_from or date_to or period not in dates.ROLLING_PERIODS:
        start, end, label = dates.resolve_range(date_from, date_to, days, period)
        return start, end, label, None
    today = dates.today_utc()
    latest = await client().latest_final_date(site_url, today.isoformat(), search_type=search_type)
    if latest is None:
        start, end, label = dates.resolve_range(date_from, date_to, days, period)
        return start, end, label, None
    from datetime import date as _date

    start, end, label = dates.resolve_range(days=days, period=period, today=_date.fromisoformat(latest))
    return start, end, label, latest


def check_compare(value: str) -> str:
    mode = (value or "previous").strip().lower()
    if mode not in dates.COMPARE_MODES:
        raise GSCError(
            400,
            f"compare must be one of {', '.join(dates.COMPARE_MODES)}, got {value!r}.",
            reason="badRequest",
        )
    return mode


def check_entity_dimension(value: str, allowed: Sequence[str]) -> str:
    """One dimension out of a closed list, matched case-insensitively."""
    match = next((v for v in allowed if v.lower() == (value or "").strip().lower()), None)
    if match is None:
        raise GSCError(
            400,
            f"Unknown dimension {value!r}. Valid values here: {', '.join(allowed)}.",
            reason="badRequest",
        )
    return match
