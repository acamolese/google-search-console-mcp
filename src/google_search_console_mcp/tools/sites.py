"""Property listing and details."""

from __future__ import annotations

from ..formatting import render
from ._common import (
    NoCache,
    ResponseFormat,
    SiteUrl,
    check_format,
    check_site_url,
    client,
    tool_annotations,
    tool_errors,
)


def register(mcp) -> None:
    @mcp.tool(annotations=tool_annotations("List Search Console properties"))
    @tool_errors
    async def gsc_sites(response_format: ResponseFormat = "tsv", no_cache: NoCache = False) -> str:
        """List every property the authenticated account can read.

        Call this first when a property string fails: it returns the exact `site_url`
        values the other tools expect, and whether each one is a domain property
        (`sc-domain:example.com`) or a URL-prefix property.
        """
        response_format = check_format(response_format)
        entries = await client().list_sites(no_cache=no_cache)
        rows = [
            {
                "site_url": entry.get("siteUrl", ""),
                "permission": entry.get("permissionLevel", ""),
                "type": "domain" if str(entry.get("siteUrl", "")).startswith("sc-domain:") else "url-prefix",
            }
            for entry in entries
        ]
        rows.sort(key=lambda row: row["site_url"])
        meta = {
            "rows": len(rows),
            "cache": client().last_cache_state,
            "source": "sites.list",
        }
        return render(rows, ["site_url", "permission", "type"], meta, response_format)

    @mcp.tool(annotations=tool_annotations("Property details"))
    @tool_errors
    async def gsc_site_details(
        site_url: SiteUrl,
        response_format: ResponseFormat = "tsv",
        no_cache: NoCache = False,
    ) -> str:
        """Permission level and property type for one property."""
        site_url = check_site_url(site_url)
        response_format = check_format(response_format)
        entry = await client().get_site(site_url, no_cache=no_cache)
        rows = [
            {
                "site_url": entry.get("siteUrl", site_url),
                "permission": entry.get("permissionLevel", ""),
                "type": "domain" if site_url.startswith("sc-domain:") else "url-prefix",
            }
        ]
        meta = {
            "site": site_url,
            "cache": client().last_cache_state,
            "source": "sites.get",
        }
        return render(rows, ["site_url", "permission", "type"], meta, response_format)
