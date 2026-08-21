"""The HTML audit report tool.

3.0.0 keeps the 2.x report intact and only moves it onto the async client; the
report itself is rebuilt (i18n, self-contained assets, adaptive thresholds) in
the audit package.
"""

from __future__ import annotations

import json
from typing import Annotated

from pydantic import Field

from .. import dates
from ..audit import generate_audit
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


def register(mcp) -> None:
    @mcp.tool(annotations=annotations("Generate an HTML SEO audit"))
    @tool_errors
    async def gsc_audit(
        site_url: SiteUrl,
        date_from: DateFrom = "",
        date_to: DateTo = "",
        days: Days = None,
        period: Period = "",
        output_dir: Annotated[
            str,
            Field(description="Where to write the report. Defaults to ~/gsc-reports/."),
        ] = "",
        branding_path: Annotated[
            str,
            Field(description="Path to a branding.json overriding colours, logo and name."),
        ] = "",
    ) -> str:
        """Build a complete HTML SEO audit report for one property.

        Runs the overview, the previous-period comparison, top queries and pages,
        devices, countries, the daily trend, sitemaps and an indexing check on the
        top 10 pages, detects issues, builds a prioritised strategy and writes a
        self-contained HTML file.

        Ask the user for the period if they have not named one; the 28-day default
        is rarely what someone wants in a client report.

        Returns JSON with the report path and the range that was actually used.
        """
        site_url = check_site_url(site_url)
        start, end, label = dates.resolve_range(date_from, date_to, days, period)
        path = await generate_audit(client(), site_url, start, end, output_dir, branding_path)
        return json.dumps(
            {
                "report_path": path,
                "site_url": site_url,
                "date_from": start,
                "date_to": end,
                "period": label,
            },
            ensure_ascii=False,
        )
