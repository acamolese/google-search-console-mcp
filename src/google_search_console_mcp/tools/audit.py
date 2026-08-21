"""The HTML audit report tool."""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from .. import dates
from .._compat import Context, EmbeddedResource, TextResourceContents
from ..audit import ALL_SECTIONS, run_audit
from ..config import SUPPORTED_LANGUAGES, Settings
from ..errors import GSCError
from ._common import (
    DateFrom,
    DateTo,
    Days,
    Period,
    SiteUrl,
    annotations,
    check_site_url,
    client,
    tool_errors,
)

OUTPUT_MODES = ("auto", "file", "inline", "both")


def _resolve_output(mode: str) -> str:
    value = (mode or "auto").strip().lower()
    if value not in OUTPUT_MODES:
        raise GSCError(
            400,
            f"output must be one of {', '.join(OUTPUT_MODES)}, got {mode!r}.",
            reason="badRequest",
        )
    if value != "auto":
        return value
    # Over stdio the client shares the filesystem, so a path is the useful answer.
    # Over HTTP it does not, so the document has to travel with the response.
    import os

    return "file" if os.environ.get("MCP_TRANSPORT", "stdio") == "stdio" else "inline"


def _check_sections(sections: list[str] | None) -> list[str] | None:
    if not sections:
        return None
    unknown = [name for name in sections if name not in ALL_SECTIONS]
    if unknown:
        raise GSCError(
            400,
            f"Unknown sections {', '.join(unknown)}. Valid sections: {', '.join(ALL_SECTIONS)}.",
            reason="badRequest",
        )
    return list(sections)


def register(mcp) -> None:
    settings = Settings.from_env()

    @mcp.tool(annotations=annotations("Generate an HTML SEO audit"))
    @tool_errors
    async def gsc_audit(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        language: Annotated[
            str,
            Field(description=f"Report language: {', '.join(SUPPORTED_LANGUAGES)}. Defaults to en."),
        ] = "",
        brand_terms: Annotated[
            list[str] | None,
            Field(
                description=(
                    "Words that mark a query as branded. Without them the first label "
                    "of the domain is used, which is often wrong."
                )
            ),
        ] = None,
        sections: Annotated[
            list[str] | None,
            Field(description=f"Subset of sections to render: {', '.join(ALL_SECTIONS)}."),
        ] = None,
        output: Annotated[
            str,
            Field(
                description=(
                    "`file` writes the report and returns its path, `inline` returns the "
                    "HTML as an embedded resource, `both` does both, `auto` picks by transport."
                )
            ),
        ] = "auto",
        output_dir: Annotated[
            str,
            Field(description="Where to write the report. Defaults to ~/gsc-reports/."),
        ] = "",
        branding_path: Annotated[
            str,
            Field(description="Path to a branding.json overriding colours, logo, name and thresholds."),
        ] = "",
        inspect_top_pages: Annotated[
            int,
            Field(description="How many top pages to run through URL Inspection. 0 disables it."),
        ] = 10,
        thresholds: Annotated[
            dict | None,
            Field(
                description=(
                    "Override the adaptive thresholds: min_impressions, min_clicks, "
                    "high_visibility_impressions, ctr_curve."
                )
            ),
        ] = None,
        ctx: Context | None = None,
    ) -> list:
        """Build a complete, self-contained HTML SEO audit for one property.

        Collects the period and its baseline, top queries and pages, devices,
        countries, the daily trend, six months of history, sitemaps and an indexing
        check, then detects issues and builds a prioritised strategy and roadmap.
        Thresholds adapt to the size of the property, so small sites get a report
        too. Available in English and Italian.

        Ask the user for the period if they have not named one: the 28-day default
        is rarely what a client report wants.

        Returns a compact JSON summary first (KPIs with deltas, issue counts, top
        quick wins, roadmap), so the findings can be discussed without reading the
        HTML, followed by the report path or the document itself.
        """
        site_url = check_site_url(site_url)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)
        mode = _resolve_output(output)
        wanted = _check_sections(sections)

        result = await run_audit(
            client(),
            site_url,
            start,
            end,
            language=language,
            brand_terms=brand_terms,
            sections=wanted,
            output_dir=output_dir,
            branding_path=branding_path,
            inspect_top_pages=max(0, int(inspect_top_pages or 0)),
            thresholds=thresholds,
            write_file=mode in ("file", "both"),
            settings=settings,
            ctx=ctx,
        )

        summary = dict(result.summary)
        summary["period"] = label
        blocks: list = [json.dumps(summary, ensure_ascii=False, separators=(",", ":"))]

        if mode in ("inline", "both"):
            blocks.append(
                EmbeddedResource(
                    type="resource",
                    resource=TextResourceContents(
                        uri=result.resource_uri,
                        mimeType="text/html",
                        text=result.html,
                    ),
                )
            )
        return blocks
