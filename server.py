"""MCP Server for Google Search Console."""

import json
import urllib.parse
import urllib.request
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from google.oauth2.credentials import Credentials

CREDS_DIR = Path(__file__).parent / "credentials"

mcp = FastMCP("google-search-console")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _google_credentials() -> Credentials:
    with open(CREDS_DIR / "oauth_credentials.json") as f:
        oauth = json.load(f)["installed"]
    with open(CREDS_DIR / "token.json") as f:
        token = json.load(f)
    return Credentials(
        token=token.get("access_token"),
        refresh_token=token["refresh_token"],
        token_uri=oauth["token_uri"],
        client_id=oauth["client_id"],
        client_secret=oauth["client_secret"],
        scopes=[
            "https://www.googleapis.com/auth/webmasters.readonly",
        ],
    )


# ===========================================================================
# TOOLS
# ===========================================================================


@mcp.tool()
def search_console_sites() -> str:
    """List verified sites in Google Search Console."""
    credentials = _google_credentials()
    if not credentials.valid:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())

    url = "https://www.googleapis.com/webmasters/v3/sites"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {credentials.token}"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    results = []
    for site in data.get("siteEntry", []):
        results.append({"url": site["siteUrl"], "permission": site["permissionLevel"]})
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def search_console_query(
    site_url: str,
    date_from: str,
    date_to: str,
    dimensions: str = "query",
    row_limit: int = 100,
) -> str:
    """Search Console performance report.

    Args:
        site_url: Site URL (e.g. "https://example.com/" or "sc-domain:example.com").
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        dimensions: Comma-separated dimensions (query, page, country, device, date).
        row_limit: Maximum rows (default 100, max 25000).
    """
    credentials = _google_credentials()
    if not credentials.valid:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())

    url = f"https://www.googleapis.com/webmasters/v3/sites/{urllib.parse.quote(site_url, safe='')}/searchAnalytics/query"
    body = json.dumps(
        {
            "startDate": date_from,
            "endDate": date_to,
            "dimensions": [d.strip() for d in dimensions.split(",")],
            "rowLimit": min(row_limit, 25000),
        }
    ).encode()

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {credentials.token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    results = []
    dims = [d.strip() for d in dimensions.split(",")]
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


# ===========================================================================
# Start server
# ===========================================================================

if __name__ == "__main__":
    mcp.run()
