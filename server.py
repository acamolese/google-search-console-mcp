"""MCP Server for Google Ads, Google Analytics 4, and Google Search Console."""

import json
import os
import urllib.parse
from pathlib import Path

from mcp.server.fastmcp import FastMCP
from google.ads.googleads.client import GoogleAdsClient
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange,
    Dimension,
    Metric,
    RunReportRequest,
)
from google.oauth2.credentials import Credentials
import urllib.request

CREDS_DIR = Path(__file__).parent / "credentials"

mcp = FastMCP("google-workspace")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_ads_client(login_customer_id: str = "") -> GoogleAdsClient:
    with open(CREDS_DIR / "google_ads.json") as f:
        creds = json.load(f)
    config = {
        "developer_token": creds["developer_token"],
        "client_id": creds["client_id"],
        "client_secret": creds["client_secret"],
        "refresh_token": creds["refresh_token"],
        "use_proto_plus": True,
    }
    lid = _clean_customer_id(login_customer_id) if login_customer_id else creds.get("login_customer_id", "")
    if lid:
        config["login_customer_id"] = lid
    return GoogleAdsClient.load_from_dict(config)


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
            "https://www.googleapis.com/auth/analytics.readonly",
            "https://www.googleapis.com/auth/webmasters.readonly",
        ],
    )


def _clean_customer_id(cid: str) -> str:
    return cid.replace("-", "").strip()


# ===========================================================================
# GOOGLE ADS TOOLS
# ===========================================================================


@mcp.tool()
def list_accounts() -> str:
    """List all Google Ads accounts accessible from the MCC."""
    client = _load_ads_client()
    service = client.get_service("CustomerService")
    response = service.list_accessible_customers()
    results = []
    for resource_name in response.resource_names:
        cid = resource_name.split("/")[-1]
        try:
            ga_service = client.get_service("GoogleAdsService")
            query = "SELECT customer.id, customer.descriptive_name, customer.currency_code, customer.status FROM customer LIMIT 1"
            rows = ga_service.search(customer_id=cid, query=query)
            for row in rows:
                results.append(
                    {
                        "id": str(row.customer.id),
                        "name": row.customer.descriptive_name,
                        "currency": row.customer.currency_code,
                        "status": row.customer.status.name,
                    }
                )
        except Exception:
            results.append({"id": cid, "name": "(limited access)", "currency": "", "status": "UNKNOWN"})
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def list_campaigns(customer_id: str) -> str:
    """List campaigns for a Google Ads account.

    Args:
        customer_id: Google Ads customer ID (with or without dashes).
    """
    client = _load_ads_client()
    service = client.get_service("GoogleAdsService")
    cid = _clean_customer_id(customer_id)
    query = """
        SELECT campaign.id, campaign.name, campaign.status,
               campaign.advertising_channel_type, campaign_budget.amount_micros
        FROM campaign
        ORDER BY campaign.name
    """
    rows = service.search(customer_id=cid, query=query)
    results = []
    for row in rows:
        results.append(
            {
                "id": str(row.campaign.id),
                "name": row.campaign.name,
                "status": row.campaign.status.name,
                "channel": row.campaign.advertising_channel_type.name,
                "budget_micros": str(row.campaign_budget.amount_micros),
            }
        )
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def campaign_performance(customer_id: str, date_from: str, date_to: str) -> str:
    """Campaign performance report for a date range.

    Args:
        customer_id: Google Ads customer ID.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
    """
    client = _load_ads_client()
    service = client.get_service("GoogleAdsService")
    cid = _clean_customer_id(customer_id)
    query = f"""
        SELECT campaign.id, campaign.name,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.conversions_value,
               metrics.ctr, metrics.average_cpc
        FROM campaign
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
        ORDER BY metrics.cost_micros DESC
    """
    rows = service.search(customer_id=cid, query=query)
    results = []
    for row in rows:
        results.append(
            {
                "campaign": row.campaign.name,
                "impressions": str(row.metrics.impressions),
                "clicks": str(row.metrics.clicks),
                "cost": f"{row.metrics.cost_micros / 1_000_000:.2f}",
                "conversions": f"{row.metrics.conversions:.2f}",
                "conv_value": f"{row.metrics.conversions_value:.2f}",
                "ctr": f"{row.metrics.ctr:.4f}",
                "avg_cpc": f"{row.metrics.average_cpc / 1_000_000:.2f}",
            }
        )
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def keyword_performance(customer_id: str, date_from: str, date_to: str, campaign_id: str = "") -> str:
    """Keyword performance report.

    Args:
        customer_id: Google Ads customer ID.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        campaign_id: (optional) Filter by campaign ID.
    """
    client = _load_ads_client()
    service = client.get_service("GoogleAdsService")
    cid = _clean_customer_id(customer_id)
    campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""
    query = f"""
        SELECT ad_group_criterion.keyword.text,
               ad_group_criterion.keyword.match_type,
               campaign.name, ad_group.name,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions, metrics.ctr, metrics.average_cpc,
               ad_group_criterion.quality_info.quality_score
        FROM keyword_view
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
            {campaign_filter}
        ORDER BY metrics.cost_micros DESC
        LIMIT 100
    """
    rows = service.search(customer_id=cid, query=query)
    results = []
    for row in rows:
        results.append(
            {
                "keyword": row.ad_group_criterion.keyword.text,
                "match_type": row.ad_group_criterion.keyword.match_type.name,
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "impressions": str(row.metrics.impressions),
                "clicks": str(row.metrics.clicks),
                "cost": f"{row.metrics.cost_micros / 1_000_000:.2f}",
                "conversions": f"{row.metrics.conversions:.2f}",
                "ctr": f"{row.metrics.ctr:.4f}",
                "avg_cpc": f"{row.metrics.average_cpc / 1_000_000:.2f}",
                "quality_score": str(row.ad_group_criterion.quality_info.quality_score),
            }
        )
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def search_terms_report(customer_id: str, date_from: str, date_to: str, campaign_id: str = "") -> str:
    """Search terms report showing actual user queries.

    Args:
        customer_id: Google Ads customer ID.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        campaign_id: (optional) Filter by campaign ID.
    """
    client = _load_ads_client()
    service = client.get_service("GoogleAdsService")
    cid = _clean_customer_id(customer_id)
    campaign_filter = f"AND campaign.id = {campaign_id}" if campaign_id else ""
    query = f"""
        SELECT search_term_view.search_term,
               campaign.name, ad_group.name,
               metrics.impressions, metrics.clicks, metrics.cost_micros,
               metrics.conversions
        FROM search_term_view
        WHERE segments.date BETWEEN '{date_from}' AND '{date_to}'
            {campaign_filter}
        ORDER BY metrics.impressions DESC
        LIMIT 100
    """
    rows = service.search(customer_id=cid, query=query)
    results = []
    for row in rows:
        results.append(
            {
                "search_term": row.search_term_view.search_term,
                "campaign": row.campaign.name,
                "ad_group": row.ad_group.name,
                "impressions": str(row.metrics.impressions),
                "clicks": str(row.metrics.clicks),
                "cost": f"{row.metrics.cost_micros / 1_000_000:.2f}",
                "conversions": f"{row.metrics.conversions:.2f}",
            }
        )
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def run_gaql_query(customer_id: str, query: str, login_customer_id: str = "") -> str:
    """Run a custom GAQL query on Google Ads.

    Args:
        customer_id: Google Ads customer ID.
        query: Google Ads Query Language query.
        login_customer_id: (optional) Override login_customer_id. Use empty string for direct access without MCC.
    """
    client = _load_ads_client(login_customer_id=login_customer_id)
    service = client.get_service("GoogleAdsService")
    cid = _clean_customer_id(customer_id)
    rows = service.search(customer_id=cid, query=query)
    results = []
    for row in rows:
        results.append(str(row))
    return "\n---\n".join(results) if results else "No results."


# ===========================================================================
# GOOGLE ANALYTICS TOOLS
# ===========================================================================


@mcp.tool()
def analytics_report(
    property_id: str,
    date_from: str,
    date_to: str,
    dimensions: str = "date",
    metrics_list: str = "sessions,totalUsers,screenPageViews",
) -> str:
    """Google Analytics 4 report.

    Args:
        property_id: GA4 property ID (e.g. "properties/123456789").
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        dimensions: Comma-separated dimensions (e.g. "date,country").
        metrics_list: Comma-separated metrics (e.g. "sessions,totalUsers").
    """
    credentials = _google_credentials()
    client = BetaAnalyticsDataClient(credentials=credentials)

    request = RunReportRequest(
        property=property_id if property_id.startswith("properties/") else f"properties/{property_id}",
        dimensions=[Dimension(name=d.strip()) for d in dimensions.split(",")],
        metrics=[Metric(name=m.strip()) for m in metrics_list.split(",")],
        date_ranges=[DateRange(start_date=date_from, end_date=date_to)],
    )

    response = client.run_report(request)
    results = []
    for row in response.rows:
        entry = {}
        for i, dim in enumerate(response.dimension_headers):
            entry[dim.name] = row.dimension_values[i].value
        for i, met in enumerate(response.metric_headers):
            entry[met.name] = row.metric_values[i].value
        results.append(entry)
    return json.dumps(results, indent=2, ensure_ascii=False)


@mcp.tool()
def analytics_list_properties() -> str:
    """List accessible GA4 properties."""
    credentials = _google_credentials()
    if not credentials.valid:
        from google.auth.transport.requests import Request
        credentials.refresh(Request())

    url = "https://analyticsadmin.googleapis.com/v1beta/accountSummaries"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {credentials.token}"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read())

    results = []
    for account in data.get("accountSummaries", []):
        for prop in account.get("propertySummaries", []):
            results.append(
                {
                    "account": account.get("displayName", ""),
                    "property_id": prop.get("property", ""),
                    "property_name": prop.get("displayName", ""),
                }
            )
    return json.dumps(results, indent=2, ensure_ascii=False)


# ===========================================================================
# GOOGLE SEARCH CONSOLE TOOLS
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
