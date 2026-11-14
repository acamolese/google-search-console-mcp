"""Turn the collected data into opportunities, quick wins and a roadmap.

Like the issue rules, everything here is keys plus numbers. The renderer picks
the language.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from .. import insights
from ..insights.thresholds import Thresholds

QUESTION_MAX_POSITION = 15.0
GEO_MIN_IMPRESSIONS = 500
GEO_CTR_RATIO = 0.8
DEVICE_GAP = 1.5
BRAND_DEPENDENCY_PCT = 50.0
ROADMAP_BRAND_PCT = 40.0
# How many page-two queries the headline uplift adds up. Summing every
# opportunity assumes they all reach the target at once, which never happens.
UPLIFT_TOP_N = 10
# A theme needs this many distinct queries before it can carry a content hub.
HUB_MIN_QUERIES = 10
# Many queries stuck on page two point at authority more than at content.
BACKLINKS_MIN_PAGE_TWO = 10


def _win(key: str, impact: str, effort: str, **params: Any) -> dict:
    return {"key": key, "impact": impact, "effort": effort, "params": params}


def _step(key: str, **params: Any) -> dict:
    return {"key": key, "params": params}


def questions(queries: Sequence[Mapping[str, Any]], question_words: Sequence[str]) -> list[dict]:
    """Question queries already ranking well enough to chase a featured snippet."""
    words = tuple(question_words)
    if not words:
        return []
    out = []
    for row in queries:
        text = str(row.get("query", "")).lower().strip()
        first = text.split(" ")[0] if text else ""
        if first in words and 0 < row.get("position", 0) <= QUESTION_MAX_POSITION:
            out.append(
                {
                    "query": row.get("query", ""),
                    "clicks": row.get("clicks", 0),
                    "impressions": row.get("impressions", 0),
                    "ctr": row.get("ctr", 0.0),
                    "position": row.get("position", 0.0),
                }
            )
    out.sort(key=lambda item: item["impressions"], reverse=True)
    return out[:10]


def geo_opportunities(countries: Sequence[Mapping[str, Any]]) -> list[dict]:
    """Secondary markets converting about as well as the primary one."""
    if not countries:
        return []
    primary_ctr = countries[0].get("ctr", 0.0)
    out = []
    for row in countries[1:]:
        if row.get("impressions", 0) < GEO_MIN_IMPRESSIONS:
            continue
        if row.get("ctr", 0.0) <= primary_ctr * GEO_CTR_RATIO:
            continue
        out.append(
            {
                "country": str(row.get("country", "")).upper(),
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0.0),
                "position": row.get("position", 0.0),
            }
        )
    return out


def device_insights(devices: Sequence[Mapping[str, Any]]) -> dict | None:
    by_device = {str(row.get("device", "")).upper(): row for row in devices}
    mobile, desktop = by_device.get("MOBILE"), by_device.get("DESKTOP")
    if not mobile or not desktop:
        return None
    gap = desktop.get("position", 0.0) - mobile.get("position", 0.0)
    total = mobile.get("clicks", 0) + desktop.get("clicks", 0)
    return {
        "mobile_position": mobile.get("position", 0.0),
        "desktop_position": desktop.get("position", 0.0),
        "gap": round(gap, 1),
        "mobile_share": round(mobile.get("clicks", 0) / total * 100, 1) if total else 0.0,
        "has_gap": abs(gap) > DEVICE_GAP,
    }


def build(
    data: Mapping[str, Any],
    issues: Sequence[Mapping[str, Any]],
    th: Thresholds,
    *,
    th_pages: Thresholds | None = None,
    brand_terms: Sequence[str] | None = None,
    stopwords: Sequence[str] = (),
    question_words: Sequence[str] = (),
) -> dict:
    """Everything the report shows below the issue list."""
    queries = data.get("queries", [])
    pages = data.get("pages", [])
    page_th = th_pages or th
    truncated = data.get("truncated", {})

    brand = insights.brand_split(queries, brand_terms, site_url=data.get("site_url", ""))
    brand_share = _brand_share(data, brand)
    page_two = insights.quick_wins(queries, th)
    gaps = insights.ctr_gaps(pages, page_th, entity="page")
    cannibals = insights.cannibalization(data.get("query_page", []), th, brand_terms=brand["brand_terms"])
    drops = insights.traffic_drops(
        pages, data.get("prev_pages", []), page_th, current_complete=not truncated.get("pages", False)
    )
    decay = insights.content_decay(data.get("monthly_by_page", {}), page_th)
    active_alerts = insights.alerts(
        queries,
        data.get("prev_queries", []),
        pages,
        data.get("prev_pages", []),
        current_pages_complete=not truncated.get("pages", False),
    )
    top_themes = insights.themes(brand["non_brand_rows"], stopwords, brand["brand_terms"])

    uplift_rows = page_two[:UPLIFT_TOP_N]
    total_uplift = sum(item["uplift"] for item in uplift_rows)
    issue_keys = {issue["key"] for issue in issues}

    wins: list[dict] = []
    if gaps:
        top = gaps[0]
        wins.append(
            _win(
                "rewrite_snippets",
                "high",
                "low",
                url=top["page"],
                impressions=top["impressions"],
                ctr=top["ctr"],
                expected_ctr=top["expected_ctr"],
                uplift=top["uplift"],
            )
        )
    if page_two:
        top = page_two[0]
        wins.append(
            _win(
                "push_page_two",
                "high",
                "medium",
                query=top["query"],
                impressions=top["impressions"],
                position=top["position"],
            )
        )
    if cannibals:
        top = cannibals[0]
        wins.append(
            _win("fix_cannibalization", "medium", "medium", query=top["query"], pages=top["page_count"])
        )
    if "http_pages" in issue_keys:
        wins.append(_win("force_https", "high", "low"))
    if "paginated_pages" in issue_keys:
        wins.append(_win("review_pagination", "low", "low"))

    question_rows = questions(queries, question_words)
    if question_rows:
        wins.append(_win("answer_questions", "medium", "medium", n=len(question_rows)))
    if brand_share["brand_pct"] > BRAND_DEPENDENCY_PCT:
        wins.append(_win("reduce_brand_dependency", "high", "high", pct=brand_share["brand_pct"]))
    hub_themes = [theme for theme in top_themes if theme["query_count"] >= HUB_MIN_QUERIES]
    if hub_themes:
        top = hub_themes[0]
        wins.append(
            _win(
                "build_topic_hub",
                "medium",
                "high",
                theme=top["theme"],
                clicks=top["clicks"],
                queries=top["query_count"],
            )
        )

    geo = geo_opportunities(data.get("countries", []))
    current = data.get("current", {})
    previous = data.get("previous", {})
    trend_pct = insights.pct_change(current.get("clicks", 0), previous.get("clicks", 0))
    roadmap = _roadmap(
        issues, wins, page_two, cannibals, hub_themes, brand_share["brand_pct"], geo, trend_pct
    )

    return {
        "executive": {
            "trend_pct": trend_pct,
            "brand_pct": brand_share["brand_pct"],
            "non_brand_pct": brand_share["non_brand_pct"],
            "anonymized_pct": brand_share["anonymized_pct"],
            "brand_basis": brand_share["basis"],
            "non_brand_clicks": brand_share["non_brand_clicks"],
            "high_issues": sum(1 for issue in issues if issue["severity"] == "high"),
            "medium_issues": sum(1 for issue in issues if issue["severity"] == "medium"),
            "total_uplift": int(total_uplift),
            "uplift_queries": len(uplift_rows),
            "quick_win_count": len(wins),
        },
        "brand": {**brand, **brand_share},
        "quick_wins": wins,
        "page_two_wins": page_two[:15],
        "ctr_gaps": gaps[:10],
        "cannibalization": cannibals[:10],
        "traffic_drops": drops[:10],
        "content_decay": decay[:10],
        "alerts": active_alerts[:15],
        "themes": top_themes,
        "questions": question_rows,
        "geo_opportunities": geo,
        "device_insights": device_insights(data.get("devices", [])),
        "roadmap": roadmap,
        "thresholds": th.as_meta(),
        "thresholds_pages": page_th.as_meta(),
        "ctr_curve": dict(th.ctr_curve),
        "truncated": truncated,
    }


def _brand_share(data: Mapping[str, Any], brand: Mapping[str, Any]) -> dict:
    """Brand, non-brand and unattributable shares of the site's clicks.

    With the API totals (every query, filtered server-side) the shares are of
    the real total, and whatever neither filter matched is anonymised traffic.
    Without them it falls back to the top-query slice and says so.
    """
    totals = data.get("brand_totals")
    site_clicks = data.get("current", {}).get("clicks", 0)
    if totals and site_clicks:
        brand_clicks = totals["brand_clicks"]
        non_brand_clicks = totals["non_brand_clicks"]
        anonymized = max(0, site_clicks - brand_clicks - non_brand_clicks)
        return {
            "basis": "all_queries",
            "brand_pct": round(brand_clicks / site_clicks * 100, 1),
            "non_brand_pct": round(non_brand_clicks / site_clicks * 100, 1),
            "anonymized_pct": round(anonymized / site_clicks * 100, 1),
            "non_brand_clicks": non_brand_clicks,
        }
    return {
        "basis": "top_queries",
        "brand_pct": brand["brand_clicks_pct"],
        "non_brand_pct": brand["non_brand_clicks_pct"],
        "anonymized_pct": None,
        "non_brand_clicks": brand["non_brand"]["clicks"],
    }


def _roadmap(
    issues: Sequence[Mapping[str, Any]],
    wins: Sequence[Mapping[str, Any]],
    page_two: Sequence[Mapping[str, Any]],
    cannibals: Sequence[Mapping[str, Any]],
    top_themes: Sequence[Mapping[str, Any]],
    brand_pct: float,
    geo: Sequence[Mapping[str, Any]],
    trend_pct: float | None,
) -> dict[str, list[dict]]:
    """Critical work first, then the medium-effort wins, then the slow bets."""
    first: list[dict] = [
        _step("issue", issue_key=issue["key"], critical=True)
        for issue in issues
        if issue["severity"] == "high"
    ]
    first.extend(_step("quick_win", win_key=win["key"]) for win in wins if win["effort"] == "low")
    if not first:
        first.append(_step("nothing_critical"))

    second: list[dict] = [_step("quick_win", win_key=win["key"]) for win in wins if win["effort"] == "medium"]
    if page_two:
        second.append(_step("optimize_page_two", n=min(10, len(page_two))))
    if cannibals:
        second.append(_step("fix_cannibalization", n=min(5, len(cannibals))))

    third: list[dict] = []
    if top_themes:
        third.append(_step("content_hubs", themes=", ".join(t["theme"] for t in top_themes[:3])))
    if brand_pct > ROADMAP_BRAND_PCT:
        third.append(_step("expand_non_brand"))
    if geo:
        third.append(_step("localize", countries=", ".join(item["country"] for item in geo[:3])))
    if len(page_two) >= BACKLINKS_MIN_PAGE_TWO:
        third.append(_step("backlinks", n=len(page_two)))
    if trend_pct is not None and trend_pct < 0:
        third.append(_step("competitors"))
    if not third:
        third.append(_step("monitor"))

    return {"30": first, "60": second, "90": third}
