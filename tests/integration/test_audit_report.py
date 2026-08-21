"""The rendered report, built from the committed fixture. No HTTP, no credentials."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from google_search_console_mcp import i18n
from google_search_console_mcp.audit import branding as branding_module
from google_search_console_mcp.audit import render as render_module
from google_search_console_mcp.audit import strategy as strategy_module
from google_search_console_mcp.insights.issues import detect_issues
from google_search_console_mcp.insights.thresholds import Thresholds

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "site_medium" / "dataset.json"


def dataset():
    data = json.loads(FIXTURE.read_text(encoding="utf-8"))
    data["monthly_by_page"] = {
        page: [tuple(item) for item in series] for page, series in data["monthly_by_page"].items()
    }
    return data


def build(language="en", branding_overrides=None, sections=None):
    data = dataset()
    translator = i18n.load(language)
    branding = branding_module.load("", branding_overrides)
    th = Thresholds.from_rows(data["queries"] + data["pages"])
    issues = detect_issues(data, th)
    strategy = strategy_module.build(
        data,
        issues,
        th,
        brand_terms=["exampleco"],
        stopwords=sorted(translator.stopwords()),
        question_words=translator.question_words(),
    )
    html = render_module.render(data, issues, strategy, branding, translator, sections=sections)
    summary = render_module.build_summary(data, issues, strategy, language=translator.language)
    return html, summary, issues, strategy


def visible(html: str) -> str:
    """The document with scripts and styles stripped: what a reader actually sees."""
    return re.sub(r"<script.*?</script>|<style.*?</style>", "", html, flags=re.S)


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_report_renders_in_every_language(language):
    html, _summary, _issues, _strategy = build(language)

    assert html.startswith("<!DOCTYPE html>")
    assert f'<html lang="{language}"' in html
    assert len(html) > 10_000


@pytest.mark.parametrize("language", ["en", "it"])
def test_the_report_reaches_nothing_outside_itself(language):
    html, _summary, _issues, _strategy = build(language)

    external = set(re.findall(r'(?:src|href)="(https?://[^"]+)"', html))
    assert external == set()
    assert "cdn.jsdelivr.net" not in html
    assert "fonts.googleapis.com" not in html


def test_a_remote_logo_is_dropped_unless_external_assets_are_allowed():
    without, _s, _i, _st = build(branding_overrides={"logo": "https://cdn.example.com/logo.png"})
    assert "cdn.example.com" not in without

    with_external, _s, _i, _st = build(
        branding_overrides={"logo": "https://cdn.example.com/logo.png", "allow_external_fonts": True}
    )
    assert "cdn.example.com" in with_external


def test_chart_js_is_inlined_not_linked():
    html, _summary, _issues, _strategy = build()
    assert "Chart.js v4" in html
    assert "<script src=" not in html


@pytest.mark.parametrize("language", ["en", "it"])
def test_no_translation_key_or_placeholder_leaks_into_the_page(language):
    body = visible(build(language)[0])

    assert not re.search(r"\{\{|\{%", body)
    assert not re.search(r"\{[a-z_]+\}", body)
    assert not re.search(r"\b(?:issue|sections|columns|quick_win|roadmap|executive)\.[a-z_0-9]+", body)


@pytest.mark.parametrize("language", ["en", "it"])
def test_every_section_is_present(language):
    body = visible(build(language)[0])
    headings = re.findall(r"<h2>(.*?)</h2>", body)
    translator = i18n.load(language)

    for section in render_module.ALL_SECTIONS:
        if section == "strategy":
            continue
        expected = translator.t(f"sections.{section}")
        assert any(expected in heading for heading in headings), f"{section} missing in {language}"


def test_sections_can_be_narrowed():
    html, _summary, _issues, _strategy = build(sections=["overview", "issues"])
    body = visible(html)
    translator = i18n.load("en")

    assert translator.t("sections.overview") in body
    assert translator.t("sections.top_queries") not in body
    assert translator.t("sections.roadmap") not in body


def test_numbers_are_formatted_for_the_language():
    english = visible(build("en")[0])
    italian = visible(build("it")[0])

    assert "4,300" in english
    assert "4.300" in italian
    assert "16.5%" in english
    assert "16,5%" in italian


def test_the_report_stays_well_under_the_size_budget():
    html, _summary, _issues, _strategy = build()
    assert len(html.encode("utf-8")) < 1_500_000


def test_the_summary_is_the_snapshot_the_model_can_reason_about():
    _html, summary, issues, _strategy = build()

    assert summary["site"] == "sc-domain:example.com"
    assert summary["range"] == ["2026-07-25", "2026-08-21"]
    assert summary["previous"] == ["2026-06-27", "2026-07-24"]
    assert summary["language"] == "en"
    assert summary["kpis"]["clicks"] == [3590, 4300, -16.5]
    assert summary["issues"]["high"] + summary["issues"]["medium"] + summary["issues"]["low"] == len(issues)
    assert set(summary["issue_keys"]) == {issue["key"] for issue in issues}
    assert summary["brand"]["source"] == "explicit"
    assert summary["thresholds"]["min_impressions"] > 0
    assert len(summary["quick_wins_top5"]) <= 5


def test_the_summary_survives_a_json_round_trip():
    _html, summary, _issues, _strategy = build()
    encoded = json.dumps(summary, ensure_ascii=False, separators=(",", ":"))
    assert json.loads(encoded) == summary
    # It has to stay small enough to sit in a tool response next to the HTML.
    assert len(encoded) < 8_000


def test_the_fixture_produces_findings_for_every_family_of_rule():
    _html, _summary, issues, strategy = build()
    keys = {issue["key"] for issue in issues}

    assert {"paginated_pages", "http_pages", "sitemap_problems", "indexing_problems"} <= keys
    assert strategy["quick_wins"]
    assert strategy["page_two_wins"]
    assert strategy["cannibalization"]
    assert strategy["traffic_drops"]
    assert strategy["content_decay"]
    assert strategy["roadmap"]["30"]


def test_branding_colours_reach_the_stylesheet():
    html, _summary, _issues, _strategy = build(branding_overrides={"colors": {"primary": "#ff00aa"}})
    assert "--primary: #ff00aa" in html


def test_the_default_font_stack_needs_no_download():
    html, _summary, _issues, _strategy = build()
    assert "BlinkMacSystemFont" in html
