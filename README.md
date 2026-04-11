# Google Search Console MCP

MCP (Model Context Protocol) server for **Google Search Console**, **Google Ads**, and **Google Analytics 4**.

Query search performance, advertising data, and analytics reports directly from Google APIs through any MCP-compatible client.

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
git clone https://github.com/acamolese/google-search-console-mcp.git
cd google-search-console-mcp

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

## Usage with Claude

Claude supports MCP servers natively in both the CLI (Claude Code) and the Desktop app. You need to configure the server in both if you use both clients.

### Claude Code (CLI)

Edit `~/.claude/.mcp.json`:

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

Restart Claude Code after saving. The tools will appear automatically and you can ask things like:

- "List my Google Ads accounts"
- "Show campaign performance for account 123-456-7890 from 2026-01-01 to 2026-03-31"
- "What are my top 50 search queries on Search Console for example.com in the last 30 days?"
- "Run a GA4 report with sessions and conversions by country for the last week"
- "Execute this GAQL query: SELECT campaign.name, metrics.cost_micros FROM campaign WHERE metrics.cost_micros > 0"

### Claude Desktop App

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

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

Restart the Desktop app. You should see the MCP tools icon in the chat input area.

### Tips

- **Google Ads**: always provide the customer ID. If you work with an MCC, set `login_customer_id` in `google_ads.json` to avoid specifying it each time.
- **Search Console**: use `sc-domain:example.com` for domain properties or `https://example.com/` for URL-prefix properties.
- **GA4**: property IDs look like `properties/123456789`. Use `analytics_list_properties` to find yours.
- **GAQL**: the `run_gaql_query` tool accepts any valid [Google Ads Query Language](https://developers.google.com/google-ads/api/docs/query/overview) query for advanced use cases.

## Security

Credential files (`credentials/*.json`) are excluded via `.gitignore`. Never commit actual credentials to version control.

## License

MIT
