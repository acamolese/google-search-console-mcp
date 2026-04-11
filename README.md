# Google Workspace MCP Server

MCP (Model Context Protocol) server that provides tools for **Google Ads**, **Google Analytics 4**, and **Google Search Console**.

Any MCP-compatible client can use this server to query advertising data, analytics reports, and search performance directly from Google APIs.

## Tools

### Google Ads
| Tool | Description |
|------|-------------|
| `list_accounts` | List all accessible Google Ads accounts |
| `list_campaigns` | List campaigns for a given account |
| `campaign_performance` | Campaign performance metrics for a date range |
| `keyword_performance` | Keyword-level performance report |
| `search_terms_report` | Actual user search terms report |
| `run_gaql_query` | Run any custom GAQL query |

### Google Analytics 4
| Tool | Description |
|------|-------------|
| `analytics_list_properties` | List accessible GA4 properties |
| `analytics_report` | Run a GA4 report with custom dimensions and metrics |

### Google Search Console
| Tool | Description |
|------|-------------|
| `search_console_sites` | List verified sites |
| `search_console_query` | Search performance report (queries, pages, countries, devices) |

## Prerequisites

- Python 3.10+
- A Google Cloud project with the following APIs enabled:
  - Google Ads API
  - Google Analytics Data API
  - Google Search Console API
- OAuth 2.0 credentials (Desktop app type)
- A Google Ads developer token (for Ads features)

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/acamolese/google-workspace-mcp.git
cd google-workspace-mcp

python -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or with `uv`:

```bash
uv venv
uv pip install -e .
```

### 2. Configure credentials

Copy the example files and fill in your values:

```bash
cp credentials/oauth_credentials.example.json credentials/oauth_credentials.json
cp credentials/google_ads.example.json credentials/google_ads.json
```

**`credentials/oauth_credentials.json`** - Download this from Google Cloud Console > APIs & Credentials > OAuth 2.0 Client IDs (Desktop app type).

**`credentials/google_ads.json`** - Fill in your developer token, client ID, client secret, refresh token, and (optionally) your MCC login customer ID.

### 3. Get a refresh token

Run the helper script to authorize via browser and obtain a refresh token:

```bash
python get_refresh_token.py
```

This will:
1. Open your browser for Google OAuth consent
2. Capture the authorization code via a local redirect
3. Save the token to `credentials/token.json`

Copy the refresh token into `credentials/google_ads.json` as well if you plan to use Google Ads tools.

### 4. Configure your MCP client

Add the server to your MCP client configuration. The exact format depends on the client, but typically looks like:

```json
{
  "mcpServers": {
    "google-workspace": {
      "command": "/path/to/google-workspace-mcp/.venv/bin/python",
      "args": ["/path/to/google-workspace-mcp/server.py"]
    }
  }
}
```

Replace `/path/to/google-workspace-mcp` with the actual path where you cloned the repo.

### 5. Test

Start the server manually to verify it loads without errors:

```bash
python server.py
```

The server communicates over stdio, so it will appear to hang (that's expected). Press `Ctrl+C` to stop.

## Google Cloud Setup Guide

If you don't have a Google Cloud project yet:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable these APIs:
   - **Google Ads API** (requires a developer token from [Google Ads API Center](https://developers.google.com/google-ads/api/docs/get-started/dev-token))
   - **Google Analytics Data API**
   - **Search Console API**
4. Go to **APIs & Credentials** > **Create Credentials** > **OAuth 2.0 Client ID**
5. Choose **Desktop app** as application type
6. Download the JSON and save it as `credentials/oauth_credentials.json`

## Security

Credential files (`credentials/*.json`) are excluded via `.gitignore`. Never commit actual credentials to version control.

## License

MIT
