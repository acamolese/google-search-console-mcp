"""MCP Server for Google Search Console."""

import json
import urllib.parse
import urllib.request
from datetime import datetime

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials

from . import config
from .audit import generate_audit

MCP_INSTRUCTIONS = """Google Search Console MCP Server.

When the user asks for an "analysis", "audit", "report", "analisi", "audit" or "report" of a site, ALWAYS use the `gsc_audit` tool to generate a complete HTML report instead of running individual queries manually.

IMPORTANT: Before calling `gsc_audit`, you MUST know the date range. If the user did not explicitly specify a period (e.g. "last 30 days", "march 2026", "from X to Y"), ASK the user which period they want to analyze before proceeding. Do not assume a default period.

After generating the report, tell the user the file path and optionally open it in the browser.
"""

mcp = FastMCP("google-search-console", instructions=MCP_INSTRUCTIONS)


# ---------------------------------------------------------------------------
# Credential helpers
# ---------------------------------------------------------------------------

def _google_credentials() -> Credentials:
    oauth = config.load_oauth_client()
    token = config.load_token()
    creds = Credentials(
        token=token.get("access_token"),
        refresh_token=token["refresh_token"],
        token_uri=oauth.get("token_uri", "https://oauth2.googleapis.com/token"),
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/webmasters.readonly",
        ],
    )
    if token.get("expiry"):
        try:
            creds.expiry = datetime.fromisoformat(token["expiry"])
        except ValueError:
            creds.expiry = datetime(1970, 1, 1)
    else:
        # Force a refresh for tokens without an expiry field (env vars, legacy files)
        creds.expiry = datetime(1970, 1, 1)
    return creds


def _get_token() -> str:
    from google.auth.transport.requests import Request
    credentials = _google_credentials()
    if not credentials.valid:
        credentials.refresh(Request())
        config.update_saved_token(credentials.token, credentials.expiry)
    return credentials.token


def _api_get(url: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_get_token()}"})
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _api_post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {_get_token()}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


BASE = "https://www.googleapis.com/webmasters/v3"
INSPECT_BASE = "https://searchconsole.googleapis.com/v1"


# ===========================================================================
# TOOLS
# ===========================================================================


@mcp.tool()
def gsc_sites() -> str:
    """List all verified sites in Google Search Console."""
    data = _api_get(f"{BASE}/sites")
    results = []
    for site in data.get("siteEntry", []):
        results.append({"url": site["siteUrl"], "permission": site["permissionLevel"]})
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_site_details(site_url: str) -> str:
    """Get details about a specific site in Google Search Console.

    Args:
        site_url: Site URL (e.g. "https://example.com/" or "sc-domain:example.com").
    """
    encoded = urllib.parse.quote(site_url, safe="")
    data = _api_get(f"{BASE}/sites/{encoded}")
    return json.dumps(data, indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_query(
    site_url: str,
    date_from: str,
    date_to: str,
    dimensions: str = "query",
    row_limit: int = 100,
) -> str:
    """Search Console performance report (top queries and pages with metrics).

    Args:
        site_url: Site URL (e.g. "https://example.com/" or "sc-domain:example.com").
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        dimensions: Comma-separated dimensions (query, page, country, device, date).
        row_limit: Maximum rows (default 100, max 25000).
    """
    encoded = urllib.parse.quote(site_url, safe="")
    dims = [d.strip() for d in dimensions.split(",")]
    data = _api_post(
        f"{BASE}/sites/{encoded}/searchAnalytics/query",
        {
            "startDate": date_from,
            "endDate": date_to,
            "dimensions": dims,
            "rowLimit": min(row_limit, 25000),
        },
    )
    results = []
    for row in data.get("rows", []):
        entry = {}
        for i, dim in enumerate(dims):
            entry[dim] = row["keys"][i]
        entry["clicks"] = row.get("clicks", 0)
        entry["impressions"] = row.get("impressions", 0)
        entry["ctr"] = f"{row.get('ctr', 0):.4f}"
        entry["position"] = f"{row.get('position', 0):.1f}"
        results.append(entry)
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_performance_overview(site_url: str, date_from: str, date_to: str) -> str:
    """Summary of site performance (total clicks, impressions, avg CTR, avg position).

    Args:
        site_url: Site URL (e.g. "https://example.com/" or "sc-domain:example.com").
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
    """
    encoded = urllib.parse.quote(site_url, safe="")
    data = _api_post(
        f"{BASE}/sites/{encoded}/searchAnalytics/query",
        {"startDate": date_from, "endDate": date_to},
    )
    rows = data.get("rows", [])
    if not rows:
        return json.dumps({"clicks": 0, "impressions": 0, "ctr": "0.0000", "position": "0.0"})
    row = rows[0]
    return json.dumps(
        {
            "clicks": row.get("clicks", 0),
            "impressions": row.get("impressions", 0),
            "ctr": f"{row.get('ctr', 0):.4f}",
            "position": f"{row.get('position', 0):.1f}",
        },
        indent=2,
    )


@mcp.tool()
def gsc_indexing_issues(site_url: str, pages: list[str]) -> str:
    """Bulk indexing check for multiple pages using the URL Inspection API.

    Use this tool to quickly verify whether a batch of URLs is indexed by Google and
    spot common issues (blocked by robots.txt, crawl errors, page-fetch failures, not
    yet indexed). For each URL it returns a compact summary; to get the full
    inspection payload (mobile usability, rich results, AMP) for a single page, use
    `gsc_inspect_url` instead.

    Quota note: the URL Inspection API enforces ~60 requests per minute and
    ~2000 per day per property. Keep the `pages` list reasonable in size.

    Args:
        site_url: Verified property URL. Domain property format "sc-domain:example.com"
            or URL-prefix format "https://example.com/".
        pages: List of fully qualified page URLs to check. They must belong to the
            `site_url` property.

    Returns:
        JSON array, one entry per input URL, each with:
        - url: the input URL
        - verdict: one of PASS, PARTIAL, FAIL, NEUTRAL, VERDICT_UNSPECIFIED
        - coverageState: human-readable coverage description
        - robotsTxtState: e.g. ALLOWED / DISALLOWED
        - indexingState: e.g. INDEXING_ALLOWED / BLOCKED_BY_META_TAG
        - lastCrawlTime: ISO-8601 timestamp of Google's last crawl attempt
        - pageFetchState: SUCCESSFUL / SOFT_404 / ACCESS_DENIED / etc.
        - crawledAs: DESKTOP / MOBILE
        If a single URL fails, its entry contains an `error` field instead of the
        fields above; the rest of the batch still returns normally.
    """
    results = []
    for page in pages:
        try:
            data = _api_post(
                f"{INSPECT_BASE}/urlInspection/index:inspect",
                {"inspectionUrl": page, "siteUrl": site_url},
            )
            result = data.get("inspectionResult", {})
            index_status = result.get("indexStatusResult", {})
            results.append({
                "url": page,
                "verdict": index_status.get("verdict", "UNKNOWN"),
                "coverageState": index_status.get("coverageState", ""),
                "robotsTxtState": index_status.get("robotsTxtState", ""),
                "indexingState": index_status.get("indexingState", ""),
                "lastCrawlTime": index_status.get("lastCrawlTime", ""),
                "pageFetchState": index_status.get("pageFetchState", ""),
                "crawledAs": index_status.get("crawledAs", ""),
            })
        except Exception as e:
            results.append({"url": page, "error": str(e)})
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_inspect_url(site_url: str, page_url: str) -> str:
    """Full URL Inspection for a single page (index + mobile + rich results + AMP).

    Returns the complete `inspectionResult` payload from Google's URL Inspection API,
    including index coverage, mobile usability, rich-results / structured-data
    eligibility, and AMP status when present. Use this when you need deep detail for
    one URL; for a quick indexed-or-not check across many URLs use
    `gsc_indexing_issues` instead.

    Quota note: the URL Inspection API enforces ~60 requests per minute and
    ~2000 per day per property.

    Args:
        site_url: Verified property URL. Domain property format "sc-domain:example.com"
            or URL-prefix format "https://example.com/". Must be a property the
            authenticated user can access.
        page_url: Fully qualified page URL under `site_url` to inspect.

    Returns:
        JSON object with (at minimum) these sub-objects when available:
        - indexStatusResult: verdict, coverageState, lastCrawlTime, canonicals,
          robotsTxtState, indexingState, pageFetchState, crawledAs, referring URLs
        - mobileUsabilityResult: verdict, issues list
        - richResultsResult: verdict, detected rich-result item types and issues
        - ampResult: verdict, AMP URL, indexing state (only for AMP pages)
        - inspectionResultLink: link to the Search Console UI for the same inspection
    """
    data = _api_post(
        f"{INSPECT_BASE}/urlInspection/index:inspect",
        {"inspectionUrl": page_url, "siteUrl": site_url},
    )
    return json.dumps(data.get("inspectionResult", {}), indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_sitemaps(site_url: str) -> str:
    """List all sitemaps submitted for a property, with errors/warnings and timestamps.

    Use this to check which sitemaps Google knows about for a property, when they were
    last submitted and downloaded, and whether Google recorded warnings or errors while
    processing them. Useful for auditing sitemap hygiene before crawl-budget work or
    to confirm a newly submitted sitemap was picked up.

    Note: this tool is read-only. Submitting or deleting sitemaps requires the
    `webmasters` (read-write) scope, which this server intentionally does not request.

    Args:
        site_url: Verified property URL. Domain property format "sc-domain:example.com"
            or URL-prefix format "https://example.com/".

    Returns:
        JSON array of sitemap entries, one per submitted sitemap, each with:
        - path: absolute URL of the sitemap (e.g. "https://example.com/sitemap.xml")
        - lastSubmitted: ISO-8601 timestamp of last (re)submission
        - lastDownloaded: ISO-8601 timestamp of Google's last fetch
        - isPending: true while Google has not finished processing the sitemap
        - isSitemapsIndex: true if it is a sitemap index file referencing other sitemaps
        - warnings: number of non-blocking issues detected by Google
        - errors: number of blocking errors detected by Google
        Returns an empty array if no sitemaps are submitted for the property.
    """
    encoded = urllib.parse.quote(site_url, safe="")
    data = _api_get(f"{BASE}/sites/{encoded}/sitemaps")
    results = []
    for sm in data.get("sitemap", []):
        results.append({
            "path": sm.get("path", ""),
            "lastSubmitted": sm.get("lastSubmitted", ""),
            "isPending": sm.get("isPending", False),
            "isSitemapsIndex": sm.get("isSitemapsIndex", False),
            "lastDownloaded": sm.get("lastDownloaded", ""),
            "warnings": sm.get("warnings", 0),
            "errors": sm.get("errors", 0),
        })
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def gsc_audit(
    site_url: str,
    date_from: str,
    date_to: str,
    output_dir: str = "",
    branding_path: str = "",
) -> str:
    """Generate a complete HTML SEO audit report for a Search Console property.

    Runs multiple queries (overview, previous-period comparison, top queries, top pages,
    devices, countries, daily trend, sitemaps, indexing check), detects common issues,
    builds an actionable strategy and renders everything in a self-contained HTML report
    with Chart.js graphs. The report layout and colors can be customized via branding.json.

    IMPORTANT: If the user has not specified a date range, ask them before calling this
    tool. Do not assume defaults.

    Args:
        site_url: Site URL (e.g. "https://example.com/" or "sc-domain:example.com").
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        output_dir: Directory where to save the HTML report. Defaults to ~/gsc-reports/.
        branding_path: Optional path to a custom branding.json overriding the default one.
    """
    path = generate_audit(_api_get, _api_post, site_url, date_from, date_to, output_dir, branding_path)
    return json.dumps({"report_path": path, "site_url": site_url, "date_from": date_from, "date_to": date_to})


# ===========================================================================
# Start server
# ===========================================================================

if __name__ == "__main__":
    mcp.run()
