"""URL Inspection tools."""

from __future__ import annotations

from collections import Counter
from typing import Annotated

from pydantic import Field

from ..errors import GSCError
from ..formatting import render
from ..models import InspectionResult
from ._common import (
    MAX_INSPECT_URLS,
    NoCache,
    ResponseFormat,
    SiteUrl,
    check_format,
    check_site_url,
    client,
    tool_annotations,
    tool_errors,
)

# Per property, per Google's published limits.
QUOTA_NOTE = "600 inspections per minute and 2,000 per day, per property."


def register(mcp) -> None:
    @mcp.tool(annotations=tool_annotations("Bulk indexing check"))
    @tool_errors
    async def gsc_indexing_issues(
        site_url: SiteUrl,
        pages: Annotated[
            list[str],
            Field(description="Fully qualified URLs under site_url. At most 100 per call."),
        ],
        response_format: ResponseFormat = "tsv",
        no_cache: NoCache = False,
    ) -> str:
        """Check whether a batch of URLs is indexed, and why not when they are not.

        Runs the inspections concurrently and returns one row per input URL, in input
        order. A URL that fails gets an `error` column instead of a verdict; the rest
        of the batch still comes back. For the full payload of a single page
        (mobile usability, rich results, AMP) use `gsc_inspect_url`.

        Quota: 600 inspections per minute and 2,000 per day, per property.

        Columns: url, verdict (PASS / PARTIAL / FAIL / NEUTRAL), coverage_state,
        robots_txt_state, indexing_state, page_fetch_state, crawled_as,
        last_crawl_time, google_canonical, user_canonical, error. The meta carries a
        verdict summary.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)

        urls = [str(page).strip() for page in (pages or []) if str(page).strip()]
        if not urls:
            raise GSCError(400, "`pages` must contain at least one URL.", reason="badRequest")
        if len(urls) > MAX_INSPECT_URLS:
            raise GSCError(
                400,
                f"{len(urls)} URLs requested but the limit is {MAX_INSPECT_URLS} per call.",
                reason="badRequest",
                hint=f"The URL Inspection quota is {QUOTA_NOTE} Split the list into batches.",
            )

        results = await client().inspect_many(site_url, urls, no_cache=no_cache)

        rows = []
        for item in results:
            if "error" in item:
                rows.append({"url": item["url"], "verdict": "ERROR", "error": item["error"]})
                continue
            status = (item.get("result") or {}).get("indexStatusResult", {})
            rows.append(
                {
                    "url": item["url"],
                    "verdict": status.get("verdict", "UNKNOWN"),
                    "coverage_state": status.get("coverageState", ""),
                    "robots_txt_state": status.get("robotsTxtState", ""),
                    "indexing_state": status.get("indexingState", ""),
                    "page_fetch_state": status.get("pageFetchState", ""),
                    "crawled_as": status.get("crawledAs", ""),
                    "last_crawl_time": status.get("lastCrawlTime", ""),
                    "google_canonical": status.get("googleCanonical", ""),
                    "user_canonical": status.get("userCanonical", ""),
                    "error": "",
                }
            )

        summary = Counter(row["verdict"] for row in rows)
        meta = {
            "site": site_url,
            "rows": len(rows),
            "summary": ",".join(f"{verdict}:{count}" for verdict, count in sorted(summary.items())),
            "quota": QUOTA_NOTE,
            "cache": client().last_cache_state,
            "source": "urlInspection.index.inspect",
        }
        columns = [
            "url",
            "verdict",
            "coverage_state",
            "robots_txt_state",
            "indexing_state",
            "page_fetch_state",
            "crawled_as",
            "last_crawl_time",
            "google_canonical",
            "user_canonical",
            "error",
        ]
        return render(rows, columns, meta, response_format)

    @mcp.tool(annotations=tool_annotations("Inspect one URL"))
    @tool_errors
    async def gsc_inspect_url(
        site_url: SiteUrl,
        page_url: Annotated[str, Field(description="Fully qualified URL under site_url.")],
        no_cache: NoCache = False,
    ) -> InspectionResult:
        """Full URL Inspection for one page: index, mobile, rich results and AMP.

        Use this when one page needs a diagnosis. For an indexed-or-not sweep across
        many URLs use `gsc_indexing_issues`.

        Quota: 600 inspections per minute and 2,000 per day, per property.
        """
        site_url = check_site_url(site_url)
        page_url = (page_url or "").strip()
        if not page_url:
            raise GSCError(400, "`page_url` is required.", reason="badRequest")

        result = await client().inspect_url(site_url, page_url, no_cache=no_cache)
        status = result.get("indexStatusResult", {})
        return InspectionResult(
            site_url=site_url,
            page_url=page_url,
            verdict=status.get("verdict", ""),
            coverage_state=status.get("coverageState", ""),
            index_status=status,
            mobile_usability=result.get("mobileUsabilityResult", {}),
            rich_results=result.get("richResultsResult", {}),
            amp=result.get("ampResult", {}),
            inspection_result_link=result.get("inspectionResultLink", ""),
        )
