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
    "brand_regex",
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


DOMINANT_POSITION = 3.0
DOMINANT_CLICK_SHARE = 0.8


def cannibalization(
    rows: Sequence[Row],
    th: Thresholds,
    *,
    min_pages: int = 2,
    min_share: float = 0.10,
    top_pages: int = 4,
    limit: int = 50,
    brand_terms: Sequence[str] = (),
) -> list[dict]:
    """Queries where Google splits impressions across several pages of the site.

    A page that picks up a rounding error's worth of impressions is not
    competing, so each page must hold at least `min_share` of the query. Three
    cases are not cannibalisation and are left out: brand queries (the home and
    the contact page both ranking for the brand is expected), queries where one
    page sits in the top three and takes most of the clicks, and queries too
    small to matter. Size is judged on impressions, because the worst cases are
    the ones where the split leaves every page with no clicks at all.
    """
    brand = brand_matcher(brand_terms)
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
        if brand is not None and brand(query):
            continue
        total_impressions = sum(page["impressions"] for page in pages)
        total_clicks = sum(page["clicks"] for page in pages)
        if total_impressions < th.min_impressions:
            continue
        competing = [page for page in pages if page["impressions"] >= total_impressions * min_share]
        if len(competing) < min_pages:
            continue
        competing.sort(key=lambda page: page["clicks"], reverse=True)
        leader = competing[0]
        if (
            total_clicks > 0
            and 0 < leader["position"] <= DOMINANT_POSITION
            and leader["clicks"] >= total_clicks * DOMINANT_CLICK_SHARE
        ):
            continue
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

DIAGNOSES = ("disappeared", "ranking_loss", "fewer_impressions", "ctr_collapse", "mixed")


def _diagnose(current: Row, previous: Row) -> str:
    """Name the most likely cause of a drop from the shape of the change.

    `fewer_impressions` is what the page-level data can show: impressions fell
    while the position held. That may be lower demand, or the page losing some of
    the queries it ranked for; telling the two apart takes the query data.
    """
    if current.get("impressions", 0) == 0:
        return "disappeared"

    position_change = current.get("position", 0) - previous.get("position", 0)
    impressions_change = _pct_change(current.get("impressions", 0), previous.get("impressions", 0))
    ctr_change = _pct_change(current.get("ctr", 0.0), previous.get("ctr", 0.0))

    if position_change >= 1.0:
        return "ranking_loss"
    if impressions_change is not None and impressions_change <= -20 and abs(position_change) <= 1.0:
        return "fewer_impressions"
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
    current_complete: bool = True,
) -> list[dict]:
    """Pages that lost clicks against the baseline, each with a likely cause.

    When the current period was read only up to a row limit (`current_complete`
    false), a page missing from it may simply sit below the cut: such pages are
    left out rather than reported as disappeared.
    """
    current = {row.get(key, ""): row for row in current_rows}
    previous = {row.get(key, ""): row for row in previous_rows}

    out = []
    for name, before in previous.items():
        if before.get("clicks", 0) < th.min_clicks:
            continue
        if name not in current and not current_complete:
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
    out: list[dict[str, Any]] = []
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

# The alerting rules are fixed on purpose: an alert has to mean the same thing on
# every property, so the adaptive thresholds do not apply here. The tool reports
# these values in its meta.
ALERT_RULES = {
    "query_min_impressions": 100,
    "position_loss": 5,
    "position_loss_high": 10,
    "ctr_collapse_pct": -50,
    "ctr_collapse_max_impressions_change_pct": 20,
    "page_min_clicks": 20,
    "clicks_drop_pct": -30,
    "clicks_drop_high_pct": -50,
}


def alerts(
    current_queries: Sequence[Row],
    previous_queries: Sequence[Row],
    current_pages: Sequence[Row],
    previous_pages: Sequence[Row],
    th: Thresholds | None = None,
    *,
    limit: int = 50,
    current_pages_complete: bool = True,
) -> list[dict]:
    """What changed sharply enough to be worth a message today.

    `th` is accepted for a uniform signature and ignored: see ALERT_RULES. A page
    missing from a current period that was cut at a row limit is not reported as
    vanished, since it may only sit below the cut.
    """
    rules = ALERT_RULES
    out: list[dict] = []

    prev_q = {row.get("query", ""): row for row in previous_queries}
    for row in current_queries:
        name = row.get("query", "")
        before = prev_q.get(name)
        if before is None or before.get("impressions", 0) < rules["query_min_impressions"]:
            continue
        position_change = row.get("position", 0) - before.get("position", 0)
        if position_change >= rules["position_loss"]:
            out.append(
                {
                    "severity": "high" if position_change >= rules["position_loss_high"] else "medium",
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
            and ctr_change <= rules["ctr_collapse_pct"]
            and impressions_change is not None
            and abs(impressions_change) <= rules["ctr_collapse_max_impressions_change_pct"]
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
        if before.get("clicks", 0) < rules["page_min_clicks"]:
            continue
        now = current_p.get(name)
        if now is None and not current_pages_complete:
            continue
        if now is None or now.get("impressions", 0) == 0:
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
        if delta is not None and delta <= rules["clicks_drop_pct"]:
            out.append(
                {
                    "severity": "high" if delta <= rules["clicks_drop_high_pct"] else "medium",
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


def _term_pattern(term: str) -> str:
    """A brand term as a pattern that tolerates spaces inside it.

    "exampleco" also matches "example co", which users type all the time.
    """
    letters = [re.escape(char) for char in _normalize(term)]
    return r"\s*".join(letters)


def brand_matcher(brand_terms: Sequence[str]):
    """A predicate telling brand queries apart, or None without terms.

    Terms match whole words only: a short brand like "nova" must not claim
    "innovazione", and "arte" must not claim "partenza".
    """
    patterns = [_term_pattern(t) for t in brand_terms if t and t.strip()]
    if not patterns:
        return None
    compiled = re.compile(r"(?<!\w)(?:" + "|".join(patterns) + r")(?!\w)", re.IGNORECASE)
    return lambda text: bool(compiled.search(str(text)))


def brand_regex(brand_terms: Sequence[str]) -> str | None:
    """The same rule as `brand_matcher`, written for the API's RE2 filter.

    RE2 has no lookbehind, so the word edges are spelled as start, end or a
    non-word character.
    """
    patterns = [_term_pattern(t) for t in brand_terms if t and t.strip()]
    if not patterns:
        return None
    return r"(?i)(^|\W)(" + "|".join(patterns) + r")(\W|$)"


def resolve_brand_terms(brand_terms: Sequence[str] | None, site_url: str = "") -> tuple[list[str], str]:
    """The terms to use and where they came from: `explicit`, `domain_label` or `none`."""
    terms = [t for t in (brand_terms or []) if t and t.strip()]
    if terms:
        return terms, "explicit"
    if site_url:
        return [domain_label(site_url)], "domain_label"
    return [], "none"


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
    terms, source = resolve_brand_terms(brand_terms, site_url)
    matcher = brand_matcher(terms)
    normalized = terms if matcher is not None else []

    brand = {"clicks": 0, "impressions": 0, "queries": 0}
    non_brand = {"clicks": 0, "impressions": 0, "queries": 0}
    non_brand_rows = []

    for row in rows:
        is_brand = matcher is not None and matcher(row.get("query", ""))
        bucket = brand if is_brand else non_brand
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
    is_brand = brand_matcher(brand_terms)
    clicks: Counter[str] = Counter()
    impressions: Counter[str] = Counter()
    queries: dict[str, set[str]] = defaultdict(set)

    for row in rows:
        text = str(row.get("query", "")).lower()
        if is_brand is not None and is_brand(text):
            continue
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
