"""Issue detection, expressed as i18n keys plus the numbers behind them.

No rule here produces a sentence. Each one returns a key, the parameters to
interpolate into it and the rows that triggered it; the renderer decides the
language. That is what makes the same report readable in English and Italian
without two copies of the logic.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from . import pct_change
from .thresholds import Thresholds

Row = Mapping[str, Any]

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}

# A page-one result clicked less than this is under-performing regardless of the
# per-site thresholds; below it the snippet is the problem, not the ranking.
LOW_CTR_CEILING = 0.02
WEAK_PAGE_CTR_CEILING = 0.015
TRAFFIC_DROP_PCT = 10.0


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


def paginated_pages(pages: Sequence[Row], _th: Thresholds) -> dict | None:
    hits = [row for row in pages if "?p=" in row.get("page", "") or "&p=" in row.get("page", "")]
    if not hits:
        return None
    return _issue(
        "high",
        "indexing",
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
    hits = [
        row
        for row in queries
        if row.get("impressions", 0) >= th.high_visibility_impressions
        and row.get("ctr", 0.0) < LOW_CTR_CEILING
        and 0 < row.get("position", 0) <= 10
    ]
    if not hits:
        return None
    return _issue(
        "medium",
        "content",
        "low_ctr_queries",
        {"n": len(hits), "threshold": round(LOW_CTR_CEILING * 100, 1)},
        {"type": "queries", "rows": _query_rows(hits)},
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
    hits = [
        row
        for row in pages
        if row.get("impressions", 0) >= th.high_visibility_impressions
        and row.get("ctr", 0.0) < WEAK_PAGE_CTR_CEILING
    ]
    if not hits:
        return None
    return _issue(
        "medium",
        "content",
        "weak_high_visibility_pages",
        {"n": len(hits), "threshold": round(WEAK_PAGE_CTR_CEILING * 100, 1)},
        {"type": "pages", "rows": _page_rows(hits)},
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
    hits = [entry for entry in indexing if entry.get("verdict") not in ("PASS", "UNKNOWN", "")]
    if not hits:
        return None
    rows = [
        {
            "url": entry.get("url", ""),
            "verdict": entry.get("verdict", ""),
            "coverage": entry.get("coverage_state", ""),
        }
        for entry in hits
    ]
    return _issue(
        "high",
        "indexing",
        "indexing_problems",
        {"n": len(hits)},
        {"type": "indexing", "rows": rows},
    )


def traffic_drop(
    current: Mapping[str, Any],
    previous: Mapping[str, Any],
    _th: Thresholds,
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
        },
        {"type": "metric", "rows": rows},
    )


def detect_issues(data: Mapping[str, Any], th: Thresholds) -> list[dict]:
    """Run every rule over one collected dataset, highest severity first."""
    pages = data.get("pages", [])
    queries = data.get("queries", [])

    found = [
        paginated_pages(pages, th),
        http_pages(pages, th),
        mixed_hosts(pages, th),
        low_ctr_queries(queries, th),
        page_two_queries(queries, th),
        weak_high_visibility_pages(pages, th),
        sitemap_problems(data.get("sitemaps", []), th),
        indexing_problems(data.get("indexing", []), th),
        traffic_drop(data.get("current", {}), data.get("previous", {}), th),
    ]
    issues = [issue for issue in found if issue]
    issues.sort(key=lambda issue: SEVERITY_ORDER.get(issue["severity"], 9))
    return issues
