"""Issue detection, expressed as i18n keys plus the numbers behind them.

No rule here produces a sentence. Each one returns a key, the parameters to
interpolate into it and the rows that triggered it; the renderer decides the
language. That is what makes the same report readable in English and Italian
without two copies of the logic.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import parse_qs, urlsplit

from . import ctr_gaps, pct_change
from .thresholds import Thresholds

Row = Mapping[str, Any]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

TRAFFIC_DROP_PCT = 10.0
# Pagination parameters seen in the wild. `p` is also WordPress's default post
# permalink (`/?p=123`), so it only counts when the same path ranks without it.
PAGE_PARAMS = ("page", "paged", "pg")
PATH_PAGE = re.compile(r"/page/(\d+)/?$")
MAX_PAGE_NUMBER = 500


def _issue(
    severity: str,
    category: str,
    key: str,
    params: dict,
    examples: dict | None = None,
) -> dict:
    return {
        "severity": severity,
        "category": category,
        "key": key,
        "params": params,
        "examples": examples or {},
    }


def _page_rows(rows: Sequence[Row], limit: int = 10) -> list[dict]:
    ordered = sorted(rows, key=lambda row: row.get("clicks", 0), reverse=True)[:limit]
    return [
        {
            "url": row.get("page", ""),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        }
        for row in ordered
    ]


def _query_rows(rows: Sequence[Row], limit: int = 10) -> list[dict]:
    ordered = sorted(rows, key=lambda row: row.get("impressions", 0), reverse=True)[:limit]
    return [
        {
            "query": row.get("query", ""),
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": row.get("ctr", 0.0),
            "position": row.get("position", 0.0),
        }
        for row in ordered
    ]


def _page_number(url: str, known_paths: set[str]) -> int | None:
    parts = urlsplit(url)
    match = PATH_PAGE.search(parts.path)
    if match:
        return int(match.group(1))
    params = parse_qs(parts.query)
    for name in PAGE_PARAMS:
        value = (params.get(name) or [""])[0]
        if value.isdigit():
            return int(value)
    value = (params.get("p") or [""])[0]
    if value.isdigit() and f"{parts.netloc}{parts.path}" in known_paths and parts.path not in ("", "/"):
        return int(value)
    return None


def paginated_pages(pages: Sequence[Row], _th: Thresholds) -> dict | None:
    """Page 2 and beyond of a listing earning search traffic.

    Informational: Google indexes paginated pages on purpose and wants each one
    to keep its own canonical. The finding is that a deep page answers queries
    the first page or a dedicated page should be answering.
    """
    known_paths = set()
    for row in pages:
        parts = urlsplit(str(row.get("page", "")))
        if not parts.query:
            known_paths.add(f"{parts.netloc}{parts.path}")
    hits = []
    for row in pages:
        number = _page_number(str(row.get("page", "")), known_paths)
        if number is not None and 2 <= number <= MAX_PAGE_NUMBER:
            hits.append(row)
    if not hits:
        return None
    return _issue(
        "low",
        "content",
        "paginated_pages",
        {"n": len(hits), "clicks": sum(row.get("clicks", 0) for row in hits)},
        {"type": "pages", "rows": _page_rows(hits)},
    )


def http_pages(pages: Sequence[Row], _th: Thresholds) -> dict | None:
    hits = [row for row in pages if str(row.get("page", "")).startswith("http://")]
    if not hits:
        return None
    return _issue(
        "high",
        "technical",
        "http_pages",
        {"n": len(hits), "clicks": sum(row.get("clicks", 0) for row in hits)},
        {"type": "pages", "rows": _page_rows(hits)},
    )


def mixed_hosts(pages: Sequence[Row], _th: Thresholds) -> dict | None:
    """www and non-www (or several subdomains) both ranking splits the signals."""
    clicks_by_host: dict[str, int] = {}
    for row in pages:
        url = str(row.get("page", ""))
        if "://" not in url:
            continue
        host = url.split("://", 1)[1].split("/", 1)[0]
        clicks_by_host[host] = clicks_by_host.get(host, 0) + row.get("clicks", 0)

    hosts = set(clicks_by_host)
    if len(hosts) <= len({host.removeprefix("www.") for host in hosts}):
        return None

    rows = [
        {"host": host, "clicks": clicks}
        for host, clicks in sorted(clicks_by_host.items(), key=lambda item: -item[1])
    ]
    return _issue(
        "medium",
        "technical",
        "mixed_hosts",
        {"n": len(hosts), "hosts": ", ".join(sorted(hosts))},
        {"type": "hosts", "rows": rows},
    )


def low_ctr_queries(queries: Sequence[Row], th: Thresholds) -> dict | None:
    """First-page queries clicked far less than their position normally earns.

    Same rule as the CTR-gap section, so the report has one definition of a
    low CTR: below 60% of the expected CTR for the position.
    """
    gaps = ctr_gaps(queries, th, entity="query", limit=1_000)
    if not gaps:
        return None
    return _issue(
        "medium",
        "content",
        "low_ctr_queries",
        {"n": len(gaps), "lost": sum(item["uplift"] for item in gaps)},
        {"type": "queries", "rows": _query_rows(gaps)},
    )


def page_two_queries(queries: Sequence[Row], th: Thresholds) -> dict | None:
    hits = [
        row
        for row in queries
        if 10 < row.get("position", 0) <= 20 and row.get("impressions", 0) >= th.min_impressions
    ]
    if not hits:
        return None
    return _issue(
        "low",
        "opportunity",
        "page_two_queries",
        {"n": len(hits)},
        {"type": "queries", "rows": _query_rows(hits)},
    )


def weak_high_visibility_pages(pages: Sequence[Row], th: Thresholds) -> dict | None:
    """Highly visible first-page pages clicked far less than their position earns."""
    gaps = ctr_gaps(pages, th, entity="page", limit=1_000)
    if not gaps:
        return None
    return _issue(
        "medium",
        "content",
        "weak_high_visibility_pages",
        {"n": len(gaps), "lost": sum(item["uplift"] for item in gaps)},
        {"type": "pages", "rows": _page_rows(gaps)},
    )


def sitemap_problems(sitemaps: Sequence[Mapping[str, Any]], _th: Thresholds) -> dict | None:
    hits = [
        entry for entry in sitemaps if int(entry.get("warnings", 0) or 0) or int(entry.get("errors", 0) or 0)
    ]
    if not hits:
        return None
    warnings = sum(int(entry.get("warnings", 0) or 0) for entry in hits)
    errors = sum(int(entry.get("errors", 0) or 0) for entry in hits)
    rows = [
        {
            "path": entry.get("path", ""),
            "warnings": int(entry.get("warnings", 0) or 0),
            "errors": int(entry.get("errors", 0) or 0),
            "last_downloaded": str(entry.get("lastDownloaded", ""))[:10],
        }
        for entry in hits
    ]
    return _issue(
        "high" if errors else "medium",
        "technical",
        "sitemap_problems",
        {"n": len(hits), "warnings": warnings, "errors": errors},
        {"type": "sitemaps", "rows": rows},
    )


def indexing_problems(indexing: Sequence[Mapping[str, Any]], _th: Thresholds) -> dict | None:
    """Inspected pages Google does not index as it should.

    FAIL is a real problem. NEUTRAL and PARTIAL cover deliberate exclusions too
    (noindex, alternate pages), so on their own they are a medium finding. ERROR is
    a failed inspection, not a verdict, and never counts.
    """
    hits = [entry for entry in indexing if entry.get("verdict") in ("FAIL", "NEUTRAL", "PARTIAL")]
    if not hits:
        return None
    severity = "high" if any(entry.get("verdict") == "FAIL" for entry in hits) else "medium"
    rows = [
        {
            "url": entry.get("url", ""),
            "verdict": entry.get("verdict", ""),
            "coverage": entry.get("coverage_state", ""),
        }
        for entry in hits
    ]
    return _issue(
        severity,
        "indexing",
        "indexing_problems",
        {"n": len(hits)},
        {"type": "indexing", "rows": rows},
    )


def traffic_drop(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    _th: Thresholds,
    baseline: str = "previous",
) -> dict | None:
    delta = pct_change(current.get("clicks", 0), previous.get("clicks", 0))
    if delta is None or delta > -TRAFFIC_DROP_PCT:
        return None
    impressions_delta = pct_change(current.get("impressions", 0), previous.get("impressions", 0))
    rows = [
        {
            "metric": "clicks",
            "previous": previous.get("clicks", 0),
            "current": current.get("clicks", 0),
            "delta": delta,
        },
        {
            "metric": "impressions",
            "previous": previous.get("impressions", 0),
            "current": current.get("impressions", 0),
            "delta": impressions_delta,
        },
    ]
    return _issue(
        "high",
        "performance",
        "traffic_drop",
        {
            "pct": abs(delta),
            "previous": previous.get("clicks", 0),
            "current": current.get("clicks", 0),
            "impressions_pct": impressions_delta if impressions_delta is not None else 0.0,
            "baseline": baseline,
        },
        {"type": "metric", "rows": rows},
    )


def detect_issues(data: Mapping[str, Any], th: Thresholds, th_pages: Thresholds | None = None) -> list[dict]:
    """Run every rule over one collected dataset, highest severity first.

    `th` comes from the query rows and `th_pages` from the page rows: a page
    gathers many queries, so one set of percentiles cannot fit both.
    """
    pages = data.get("pages", [])
    queries = data.get("queries", [])
    page_th = th_pages or th

    found = [
        paginated_pages(pages, page_th),
        http_pages(pages, page_th),
        mixed_hosts(pages, page_th),
        low_ctr_queries(queries, th),
        page_two_queries(queries, th),
        weak_high_visibility_pages(pages, page_th),
        sitemap_problems(data.get("sitemaps", []), th),
        indexing_problems(data.get("indexing", []), th),
        traffic_drop(data.get("current", {}), data.get("previous", {}), th, data.get("compare", "previous")),
    ]
    issues = [issue for issue in found if issue]
    issues.sort(key=lambda issue: SEVERITY_ORDER.get(issue["severity"], 9))
    return issues
