"""Pure analysis functions over normalized Search Console rows.

Nothing here does I/O. The insight tools and the audit report call the same
functions, so a rule can only ever say one thing, and the tests run on synthetic
datasets with no HTTP mock in sight.

Every returned item carries the numbers that produced it: a finding the reader
cannot check against the data is not worth reporting.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .thresholds import Thresholds

Row = Mapping[str, Any]

__all__ = [
    "Thresholds",
    "alerts",
    "brand_split",
    "cannibalization",
    "content_decay",
    "ctr_gaps",
    "pct_change",
    "quick_wins",
    "themes",
    "traffic_drops",
]


def pct_change(current: float, previous: float) -> float | None:
    """Percent change, or None when there is no baseline to divide by."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


_pct_change = pct_change  # internal alias kept for the rule modules


# ---------------------------------------------------------------------------
# Opportunities
# ---------------------------------------------------------------------------


def quick_wins(
    rows: Sequence[Row],
    th: Thresholds,
    *,
    min_position: float = 4.0,
    max_position: float = 20.0,
    target_position: int = 3,
    limit: int = 50,
) -> list[dict]:
    """Queries close enough to the top that a push would pay off.

    Ranked by the clicks the query would gain at `target_position`, not by
    impressions: a huge query already near its ceiling is not an opportunity.
    """
    target_ctr = th.expected_ctr(target_position)
    out = []
    for row in rows:
        position = row.get("position", 0)
        impressions = row.get("impressions", 0)
        if not (min_position <= position <= max_position):
            continue
        if impressions < th.min_impressions:
            continue
        clicks = row.get("clicks", 0)
        potential = int(impressions * target_ctr)
        uplift = max(0, potential - clicks)
        if uplift <= 0:
            continue
        out.append(
            {
                "query": row.get("query", ""),
                "clicks": clicks,
                "impressions": impressions,
                "ctr": row.get("ctr", 0.0),
                "position": position,
                "target_position": target_position,
                "potential_clicks": potential,
                "uplift": uplift,
            }
        )
    out.sort(key=lambda item: item["uplift"], reverse=True)
    return out[:limit]


def ctr_gaps(
    rows: Sequence[Row],
    th: Thresholds,
    *,
    entity: str = "page",
    max_position: float = 10.0,
    gap_ratio: float = 0.6,
    limit: int = 50,
) -> list[dict]:
    """Rows that rank well but are clicked far less than their position implies.

    The snippet, not the ranking, is the problem here, which makes these the
    cheapest fixes on the list.
    """
    out = []
    for row in rows:
        position = row.get("position", 0)
        impressions = row.get("impressions", 0)
        if position <= 0 or position > max_position:
            continue
        if impressions < th.high_visibility_impressions:
            continue
        expected = th.expected_ctr(position)
        ctr = row.get("ctr", 0.0)
        if ctr >= expected * gap_ratio:
            continue
        clicks = row.get("clicks", 0)
        potential = int(impressions * expected)
        out.append(
            {
                entity: row.get(entity, ""),
                "clicks": clicks,
                "impressions": impressions,
                "ctr": ctr,
                "expected_ctr": round(expected, 4),
                "position": position,
                "potential_clicks": potential,
                "uplift": max(0, potential - clicks),
            }
        )
    out.sort(key=lambda item: item["uplift"], reverse=True)
    return out[:limit]


def cannibalization(
    rows: Sequence[Row],
    th: Thresholds,
    *,
    min_pages: int = 2,
    min_share: float = 0.10,
    top_pages: int = 4,
    limit: int = 50,
) -> list[dict]:
    """Queries where Google splits impressions across several pages of the site.

    A page that picks up a rounding error's worth of impressions is not
    competing, so each page must hold at least `min_share` of the query.
    """
    by_query: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        by_query[row.get("query", "")].append(
            {
                "page": row.get("page", ""),
                "clicks": row.get("clicks", 0),
                "impressions": row.get("impressions", 0),
                "ctr": row.get("ctr", 0.0),
                "position": row.get("position", 0),
            }
        )

    out = []
    for query, pages in by_query.items():
        total_impressions = sum(page["impressions"] for page in pages)
        total_clicks = sum(page["clicks"] for page in pages)
        if total_impressions <= 0 or total_clicks < th.min_clicks:
            continue
        competing = [page for page in pages if page["impressions"] >= total_impressions * min_share]
        if len(competing) < min_pages:
            continue
        competing.sort(key=lambda page: page["clicks"], reverse=True)
        out.append(
            {
                "query": query,
                "page_count": len(competing),
                "clicks": total_clicks,
                "impressions": total_impressions,
                "score": total_impressions * len(competing),
                "pages": competing[:top_pages],
            }
        )
    out.sort(key=lambda item: item["score"], reverse=True)
    return out[:limit]


# ---------------------------------------------------------------------------
# Regressions
# ---------------------------------------------------------------------------

DIAGNOSES = ("disappeared", "ranking_loss", "demand_decline", "ctr_collapse", "mixed")


def _diagnose(current: Row, previous: Row) -> str:
    """Name the most likely cause of a drop from the shape of the change."""
    if current.get("clicks", 0) == 0:
        return "disappeared"

    position_change = current.get("position", 0) - previous.get("position", 0)
    impressions_change = _pct_change(current.get("impressions", 0), previous.get("impressions", 0))
    ctr_change = _pct_change(current.get("ctr", 0.0), previous.get("ctr", 0.0))

    if position_change >= 1.0:
        return "ranking_loss"
    if impressions_change is not None and impressions_change <= -20 and abs(position_change) <= 1.0:
        return "demand_decline"
    if (
        ctr_change is not None
        and ctr_change <= -20
        and impressions_change is not None
        and abs(impressions_change) <= 10
        and abs(position_change) <= 1.0
    ):
        return "ctr_collapse"
    return "mixed"


def traffic_drops(
    current_rows: Sequence[Row],
    previous_rows: Sequence[Row],
    th: Thresholds,
    *,
    key: str = "page",
    min_drop_pct: float = 20.0,
    limit: int = 50,
) -> list[dict]:
    """Pages that lost clicks against the baseline, each with a likely cause."""
    current = {row.get(key, ""): row for row in current_rows}
    previous = {row.get(key, ""): row for row in previous_rows}

    out = []
    for name, before in previous.items():
        if before.get("clicks", 0) < th.min_clicks:
            continue
        now = current.get(name, {"clicks": 0, "impressions": 0, "ctr": 0.0, "position": 0.0})
        delta_pct = _pct_change(now.get("clicks", 0), before.get("clicks", 0))
        if delta_pct is None or delta_pct > -min_drop_pct:
            continue
        out.append(
            {
                key: name,
                "clicks": now.get("clicks", 0),
                "prev_clicks": before.get("clicks", 0),
                "clicks_delta": now.get("clicks", 0) - before.get("clicks", 0),
                "clicks_delta_pct": delta_pct,
                "impressions": now.get("impressions", 0),
                "prev_impressions": before.get("impressions", 0),
                "ctr": now.get("ctr", 0.0),
                "prev_ctr": before.get("ctr", 0.0),
                "position": now.get("position", 0.0),
                "prev_position": before.get("position", 0.0),
                "diagnosis": _diagnose(now, before),
            }
        )
    out.sort(key=lambda item: item["clicks_delta"])
    return out[:limit]


def content_decay(
    monthly_by_page: Mapping[str, Sequence[tuple[str, int]]],
    th: Thresholds,
    *,
    consecutive_months: int = 3,
    min_peak_clicks: int = 30,
    limit: int = 50,
) -> list[dict]:
    """Pages sliding down month after month, which a period comparison hides.

    A page that halves over six months never shows a 20% drop in any single
    month-on-month comparison.
    """
    out = []
    for page, series in monthly_by_page.items():
        if len(series) < consecutive_months + 1:
            continue
        months = list(series)
        clicks = [value for _month, value in months]
        peak = max(clicks)
        if peak < min_peak_clicks:
            continue
        tail = clicks[-(consecutive_months + 1) :]
        if not all(later < earlier for earlier, later in zip(tail, tail[1:], strict=False)):
            continue
        last = clicks[-1]
        out.append(
            {
                "page": page,
                "peak_clicks": peak,
                "peak_month": months[clicks.index(peak)][0],
                "last_clicks": last,
                "last_month": months[-1][0],
                "lost_clicks": peak - last,
                "decay_pct": round((peak - last) / peak * 100, 1) if peak else 0.0,
                "months": consecutive_months,
            }
        )
    out.sort(key=lambda item: item["lost_clicks"], reverse=True)
    return out[:limit]


SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2}


def alerts(
    current_queries: Sequence[Row],
    previous_queries: Sequence[Row],
    current_pages: Sequence[Row],
    previous_pages: Sequence[Row],
    th: Thresholds,
    *,
    limit: int = 50,
) -> list[dict]:
    """What changed sharply enough to be worth a message today."""
    out: list[dict] = []

    prev_q = {row.get("query", ""): row for row in previous_queries}
    for row in current_queries:
        name = row.get("query", "")
        before = prev_q.get(name)
        if before is None or before.get("impressions", 0) < 100:
            continue
        position_change = row.get("position", 0) - before.get("position", 0)
        if position_change >= 5:
            out.append(
                {
                    "severity": "high" if position_change >= 10 else "medium",
                    "type": "position_loss",
                    "entity": name,
                    "before": before.get("position", 0),
                    "after": row.get("position", 0),
                    "delta": round(position_change, 1),
                }
            )
            continue
        ctr_change = _pct_change(row.get("ctr", 0.0), before.get("ctr", 0.0))
        impressions_change = _pct_change(row.get("impressions", 0), before.get("impressions", 0))
        if (
            ctr_change is not None
            and ctr_change <= -50
            and impressions_change is not None
            and abs(impressions_change) <= 20
        ):
            out.append(
                {
                    "severity": "medium",
                    "type": "ctr_collapse",
                    "entity": name,
                    "before": before.get("ctr", 0.0),
                    "after": row.get("ctr", 0.0),
                    "delta": ctr_change,
                }
            )

    current_p = {row.get("page", ""): row for row in current_pages}
    for name, before in {row.get("page", ""): row for row in previous_pages}.items():
        if before.get("clicks", 0) < 20:
            continue
        now = current_p.get(name)
        if now is None or now.get("clicks", 0) == 0:
            out.append(
                {
                    "severity": "high",
                    "type": "page_disappeared",
                    "entity": name,
                    "before": before.get("clicks", 0),
                    "after": 0,
                    "delta": -100.0,
                }
            )
            continue
        delta = _pct_change(now.get("clicks", 0), before.get("clicks", 0))
        if delta is not None and delta <= -30:
            out.append(
                {
                    "severity": "high" if delta <= -50 else "medium",
                    "type": "clicks_drop",
                    "entity": name,
                    "before": before.get("clicks", 0),
                    "after": now.get("clicks", 0),
                    "delta": delta,
                }
            )

    out.sort(key=lambda item: (SEVERITY_ORDER.get(item["severity"], 9), item["delta"]))
    return out[:limit]


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def domain_label(site_url: str) -> str:
    """The first label of the domain, used as a last-resort brand guess."""
    cleaned = site_url.replace("sc-domain:", "").replace("https://", "").replace("http://", "")
    host = cleaned.split("/")[0]
    host = host.removeprefix("www.")
    return host.split(".")[0].lower()


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text.lower())


def brand_split(
    rows: Sequence[Row],
    brand_terms: Sequence[str] | None = None,
    *,
    site_url: str = "",
) -> dict:
    """Split queries into brand and non-brand traffic.

    Guessing the brand from the domain is often wrong (an abbreviation, a
    holding company, a made-up name), so the result says where the terms came
    from and the caller can pass real ones.
    """
    terms = [t for t in (brand_terms or []) if t.strip()]
    source = "explicit"
    if not terms and site_url:
        terms = [domain_label(site_url)]
        source = "domain_label"
    normalized = [_normalize(t) for t in terms if t.strip()]

    brand = {"clicks": 0, "impressions": 0, "queries": 0}
    non_brand = {"clicks": 0, "impressions": 0, "queries": 0}
    non_brand_rows = []

    for row in rows:
        text = _normalize(str(row.get("query", "")))
        bucket = brand if any(term and term in text for term in normalized) else non_brand
        bucket["clicks"] += row.get("clicks", 0)
        bucket["impressions"] += row.get("impressions", 0)
        bucket["queries"] += 1
        if bucket is non_brand:
            non_brand_rows.append(row)

    total_clicks = brand["clicks"] + non_brand["clicks"]
    return {
        "brand_terms": terms,
        "brand_terms_source": source if normalized else "none",
        "brand": brand,
        "non_brand": non_brand,
        "brand_clicks_pct": round(brand["clicks"] / total_clicks * 100, 1) if total_clicks else 0.0,
        "non_brand_clicks_pct": round(non_brand["clicks"] / total_clicks * 100, 1) if total_clicks else 0.0,
        "non_brand_rows": non_brand_rows,
    }


WORD_PATTERN = re.compile(r"[^\W\d_]{4,}", re.UNICODE)


def themes(
    rows: Sequence[Row],
    stopwords: Sequence[str] = (),
    brand_terms: Sequence[str] = (),
    *,
    top: int = 15,
) -> list[dict]:
    """Recurring words across non-brand queries.

    Experimental: word frequency is a weak proxy for topic, and it says nothing
    about intent. Useful as a starting point for a content plan, not as a
    finding on its own.
    """
    stop = {s.lower() for s in stopwords}
    brand = {_normalize(t) for t in brand_terms if t}
    clicks: Counter[str] = Counter()
    impressions: Counter[str] = Counter()
    queries: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        text = str(row.get("query", "")).lower()
        for word in WORD_PATTERN.findall(text):
            if word in stop or word in brand:
                continue
            clicks[word] += row.get("clicks", 0)
            impressions[word] += row.get("impressions", 0)
            queries[word].add(text)

    return [
        {
            "theme": word,
            "clicks": count,
            "impressions": impressions[word],
            "query_count": len(queries[word]),
            "experimental": True,
        }
        for word, count in clicks.most_common(top)
    ]
