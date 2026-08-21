"""Sitemap listing."""

from __future__ import annotations

from ..formatting import render
from ._common import (
    NoCache,
    ResponseFormat,
    SiteUrl,
    annotations,
    check_format,
    check_site_url,
    client,
    tool_errors,
)


def _contents(entry: dict) -> tuple[int, int]:
    """Submitted and indexed URL counts, summed across the content types Google reports."""
    submitted = indexed = 0
    for block in entry.get("contents", []) or []:
        submitted += int(block.get("submitted", 0) or 0)
        indexed += int(block.get("indexed", 0) or 0)
    return submitted, indexed


def register(mcp) -> None:
    @mcp.tool(annotations=annotations("List submitted sitemaps"))
    @tool_errors
    async def gsc_sitemaps(
        site_url: SiteUrl,
        response_format: ResponseFormat = "tsv",
        no_cache: NoCache = False,
    ) -> str:
        """List the sitemaps Google knows about for a property, with errors and warnings.

        Read-only: submitting or deleting a sitemap needs the read-write scope, which
        this server never requests.

        Returns one row per sitemap: path, last submitted and downloaded timestamps,
            pending flag, index flag, warning and error counts, and the submitted /
            indexed URL counts when Google reports them.
        """
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        entries = await client().list_sitemaps(site_url, no_cache=no_cache)

        rows = []
        for entry in entries:
            submitted, indexed = _contents(entry)
            rows.append(
                {
                    "path": entry.get("path", ""),
                    "last_submitted": entry.get("lastSubmitted", ""),
                    "last_downloaded": entry.get("lastDownloaded", ""),
                    "is_pending": bool(entry.get("isPending", False)),
                    "is_index": bool(entry.get("isSitemapsIndex", False)),
                    "warnings": int(entry.get("warnings", 0) or 0),
                    "errors": int(entry.get("errors", 0) or 0),
                    "submitted_urls": submitted,
                    "indexed_urls": indexed,
                }
            )

        meta = {
            "site": site_url,
            "rows": len(rows),
            "total_errors": sum(row["errors"] for row in rows),
            "total_warnings": sum(row["warnings"] for row in rows),
            "cache": client().last_cache_state,
            "source": "sitemaps.list",
        }
        columns = [
            "path",
            "last_submitted",
            "last_downloaded",
            "is_pending",
            "is_index",
            "warnings",
            "errors",
            "submitted_urls",
            "indexed_urls",
        ]
        return render(rows, columns, meta, response_format)
