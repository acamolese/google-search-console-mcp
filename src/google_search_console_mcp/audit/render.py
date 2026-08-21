"""Render the report to a single self-contained HTML file.

2.x pulled Chart.js and Google Fonts from a CDN, so the "self-contained" report
broke on a plane and phoned home when a client opened it. Chart.js is now
vendored and inlined, and the default font stack is the system one.
"""

from __future__ import annotations

import json
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .. import __version__
from ..i18n import Translator

PACKAGE_DIR = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = PACKAGE_DIR / "templates"
STATIC_DIR = PACKAGE_DIR / "static"
CHART_JS = STATIC_DIR / "chart.umd.min.js"

ALL_SECTIONS = (
    "overview",
    "issues",
    "top_queries",
    "top_pages",
    "countries",
    "sitemaps",
    "indexing",
    "strategy",
    "roadmap",
)


def chart_library() -> str:
    """The vendored Chart.js bundle, inlined into the document."""
    if not CHART_JS.exists():  # pragma: no cover - packaging guard
        return ""
    return CHART_JS.read_text(encoding="utf-8")


def _shorten_url(url: str, max_len: int = 70) -> str:
    text = str(url).replace("https://", "").replace("http://", "")
    return text if len(text) <= max_len else text[: max_len - 1] + "…"


def _environment(translator: Translator) -> Environment:
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["shorten_url"] = _shorten_url
    env.filters["num"] = lambda value, decimals=0: translator.number(value or 0, decimals)
    env.filters["pct"] = lambda value, decimals=1: translator.pct(value, decimals)
    env.filters["signed_pct"] = lambda value, decimals=1: translator.pct(value, decimals, signed=True)
    env.filters["ctr"] = lambda value: translator.pct((value or 0) * 100, 2)
    env.filters["pos"] = lambda value: translator.number(value or 0, 1)
    return env


def _kpis(data: dict, translator: Translator) -> list[dict]:
    from .. import insights

    current, previous = data.get("current", {}), data.get("previous", {})
    rows = [
        ("clicks", current.get("clicks", 0), previous.get("clicks", 0), 0, False),
        ("impressions", current.get("impressions", 0), previous.get("impressions", 0), 0, False),
        ("ctr", current.get("ctr", 0.0) * 100, previous.get("ctr", 0.0) * 100, 2, False),
        ("position", current.get("position", 0.0), previous.get("position", 0.0), 1, True),
    ]

    out = []
    for key, now, before, decimals, lower_is_better in rows:
        change = insights.pct_change(now, before)
        suffix = "%" if key == "ctr" else ""
        out.append(
            {
                "key": key,
                "label": translator.t(f"kpi.{key}"),
                "value": translator.number(now, decimals) + suffix,
                "delta_pct": change,
                "delta_label": translator.pct(change, signed=True)
                if change is not None
                else translator.t("kpi.no_baseline"),
                "positive": None if change is None else (change < 0 if lower_is_better else change >= 0),
            }
        )
    return out


def _charts(data: dict) -> dict:
    trend = data.get("trend", [])
    devices = data.get("devices", [])
    return {
        "trend_labels": [row.get("date", "") for row in trend],
        "trend_clicks": [row.get("clicks", 0) for row in trend],
        "trend_impressions": [row.get("impressions", 0) for row in trend],
        "device_labels": [row.get("device", "") for row in devices],
        "device_clicks": [row.get("clicks", 0) for row in devices],
        "device_positions": [row.get("position", 0.0) for row in devices],
    }


def translate_issues(issues: list[dict], translator: Translator) -> list[dict]:
    """Attach the localized title, description and strategy to each issue."""
    out = []
    for issue in issues:
        key = issue["key"]
        params = dict(issue.get("params", {}))
        display = dict(params)
        # Numbers inside sentences follow the locale, not Python's repr.
        for name, value in params.items():
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            display[name] = translator.number(value, 1 if isinstance(value, float) else 0)
        count = params.get(issue.get("plural_on", "n"))
        count = count if isinstance(count, (int, float)) and not isinstance(count, bool) else 2
        out.append(
            {
                **issue,
                "title": translator.plural(f"issue.{key}.title", count, **display),
                "description": translator.plural(f"issue.{key}.description", count, **display),
                "strategy": translator.list(f"issue.{key}.strategy"),
                "severity_label": translator.t(f"severity.{issue['severity']}"),
                "category_label": translator.t(f"category.{issue['category']}"),
            }
        )
    return out


def translate_quick_wins(wins: list[dict], translator: Translator) -> list[dict]:
    out = []
    for win in wins:
        params = dict(win.get("params", {}))
        display = {}
        for name, value in params.items():
            if name == "ctr" or name == "expected_ctr":
                display[name] = translator.pct((value or 0) * 100, 2)
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                display[name] = value
            else:
                display[name] = translator.number(value, 1 if isinstance(value, float) else 0)
        count = params.get("n")
        count = count if isinstance(count, (int, float)) and not isinstance(count, bool) else 2
        out.append(
            {
                **win,
                "title": translator.t(f"quick_win.{win['key']}.title", **display),
                "action": translator.plural(f"quick_win.{win['key']}.action", count, **display),
                "impact_label": translator.t(f"impact.{win['impact']}"),
                "effort_label": translator.t(f"effort.{win['effort']}"),
            }
        )
    return out


def translate_roadmap(roadmap: dict, issues: list[dict], wins: list[dict], translator: Translator) -> dict:
    """Roadmap steps reference issues and wins by key, so resolve them here."""
    issue_titles = {issue["key"]: issue["title"] for issue in issues}
    win_titles = {win["key"]: win["title"] for win in wins}
    prefix = translator.t("roadmap.critical_prefix")

    out: dict[str, list[str]] = {}
    for horizon, steps in roadmap.items():
        lines = []
        for step in steps:
            key = step["key"]
            params = step.get("params", {})
            if key == "issue":
                title = issue_titles.get(params.get("issue_key"), params.get("issue_key", ""))
                lines.append(f"{prefix} {title}" if params.get("critical") else title)
            elif key == "quick_win":
                lines.append(win_titles.get(params.get("win_key"), params.get("win_key", "")))
            else:
                display = {
                    name: translator.number(value) if isinstance(value, int) else value
                    for name, value in params.items()
                }
                lines.append(translator.t(f"roadmap.{key}", **display))
        out[horizon] = lines
    return out


def build_summary(
    data: dict,
    issues: list[dict],
    strategy: dict,
    *,
    language: str,
    report_path: str | None = None,
) -> dict:
    """The compact JSON block returned alongside the HTML.

    Lets the model discuss the report without reading a 250KB document.
    """
    from .. import insights

    current, previous = data.get("current", {}), data.get("previous", {})
    counts = {"high": 0, "medium": 0, "low": 0}
    for issue in issues:
        counts[issue["severity"]] = counts.get(issue["severity"], 0) + 1

    def metric(name: str) -> list:
        now, before = current.get(name, 0), previous.get(name, 0)
        return [now, before, insights.pct_change(now, before)]

    summary = {
        "site": data.get("site_url", ""),
        "range": [data.get("date_from", ""), data.get("date_to", "")],
        "previous": [data.get("prev_from", ""), data.get("prev_to", "")],
        "language": language,
        "data_state": data.get("data_state", "all"),
        "kpis": {
            "clicks": metric("clicks"),
            "impressions": metric("impressions"),
            "ctr": metric("ctr"),
            "position": metric("position"),
        },
        "issues": counts,
        "issue_keys": [issue["key"] for issue in issues],
        "thresholds": strategy.get("thresholds", {}),
        "brand": {
            "terms": strategy.get("brand", {}).get("brand_terms", []),
            "source": strategy.get("brand", {}).get("brand_terms_source", ""),
            "brand_clicks_pct": strategy.get("brand", {}).get("brand_clicks_pct", 0.0),
        },
        "quick_wins_top5": [
            {
                "query": win["params"].get("query") or win["params"].get("url") or win["key"],
                "key": win["key"],
                "impact": win["impact"],
                "effort": win["effort"],
            }
            for win in strategy.get("quick_wins", [])[:5]
        ],
        "estimated_uplift_clicks": strategy.get("executive", {}).get("total_uplift", 0),
        "alerts": strategy.get("alerts", [])[:5],
        "traffic_drops_top5": strategy.get("traffic_drops", [])[:5],
    }
    if report_path:
        summary["report_path"] = report_path
    return summary


def render(
    data: dict,
    issues: list[dict],
    strategy: dict,
    branding: dict,
    translator: Translator,
    *,
    sections: list[str] | None = None,
) -> str:
    """Render the HTML report."""
    wanted = [s for s in (sections or ALL_SECTIONS) if s in ALL_SECTIONS]
    env = _environment(translator)
    template = env.get_template("report.html.j2")

    localized_issues = translate_issues(issues, translator)
    localized_wins = translate_quick_wins(strategy.get("quick_wins", []), translator)

    return template.render(
        t=translator.t,
        lang=translator.language,
        locale=translator.locale,
        data=data,
        issues=localized_issues,
        strategy=strategy,
        quick_wins=localized_wins,
        roadmap=translate_roadmap(strategy.get("roadmap", {}), localized_issues, localized_wins, translator),
        branding=branding,
        kpis=_kpis(data, translator),
        charts=json.dumps(_charts(data)),
        chart_js=chart_library(),
        sections=wanted,
        version=__version__,
    )
