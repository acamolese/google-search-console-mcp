"""The HTML audit report: collect, analyse, render."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .. import i18n
from ..config import Settings
from ..insights.issues import detect_issues
from ..insights.thresholds import Thresholds
from . import branding as branding_module
from . import collect as collect_module
from . import render as render_module
from .render import ALL_SECTIONS

__all__ = ["ALL_SECTIONS", "AuditResult", "run_audit", "site_slug"]

DEFAULT_OUTPUT_DIR = Path.home() / "gsc-reports"


def site_slug(site_url: str) -> str:
    """A filesystem-safe name for a property."""
    text = site_url.replace("sc-domain:", "").replace("https://", "").replace("http://", "")
    return text.replace("/", "_").replace(".", "_").strip("_")


@dataclass
class AuditResult:
    html: str
    summary: dict
    path: str | None
    language: str
    resource_uri: str


async def run_audit(
    gsc,
    site_url: str,
    date_from: str,
    date_to: str,
    *,
    language: str = "",
    brand_terms: list[str] | None = None,
    sections: list[str] | None = None,
    output_dir: str = "",
    branding_path: str = "",
    inspect_top_pages: int = collect_module.DEFAULT_INSPECT_TOP_PAGES,
    thresholds: dict | None = None,
    write_file: bool = True,
    settings: Settings | None = None,
    ctx: Any = None,
) -> AuditResult:
    """Build the report and, unless told otherwise, write it to disk."""
    settings = settings or Settings.from_env()
    branding = branding_module.load(branding_path)

    resolved_language = (language or "").strip().lower() or settings.report_language
    translator = i18n.load(resolved_language)

    data = await collect_module.collect(
        gsc,
        site_url,
        date_from,
        date_to,
        data_state=settings.data_state,
        inspect_top_pages=inspect_top_pages,
        ctx=ctx,
    )

    # Branding may carry per-client thresholds and a CTR curve; the call argument wins.
    overrides = {**(branding.get("thresholds") or {})}
    if branding.get("ctr_curve"):
        overrides["ctr_curve"] = branding["ctr_curve"]
    overrides.update(thresholds or {})

    th = Thresholds.from_rows(data["queries"] + data["pages"], overrides)
    issues = detect_issues(data, th)

    from . import strategy as strategy_module

    strategy = strategy_module.build(
        data,
        issues,
        th,
        brand_terms=brand_terms or branding.get("brand_terms") or [],
        stopwords=sorted(translator.stopwords()),
        question_words=translator.question_words(),
    )

    html = render_module.render(data, issues, strategy, branding, translator, sections=sections)

    path: str | None = None
    if write_file:
        directory = Path(output_dir).expanduser() if output_dir else DEFAULT_OUTPUT_DIR
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / f"{site_slug(site_url)}_{date_from}_{date_to}.html"
        target.write_text(html, encoding="utf-8")
        path = str(target)

    summary = render_module.build_summary(
        data, issues, strategy, language=translator.language, report_path=path
    )
    await collect_module.report_progress(ctx, collect_module.PROGRESS_STEPS, "Report ready")

    return AuditResult(
        html=html,
        summary=summary,
        path=path,
        language=translator.language,
        resource_uri=f"gsc-report://{site_slug(site_url)}/{date_from}_{date_to}",
    )
