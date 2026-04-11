# Google Search Console MCP

MCP (Model Context Protocol) server for **Google Search Console**. Query search performance data directly from the Search Console API through any MCP-compatible client.

## Tools

| Tool | Description |
|------|-------------|
| `search_console_sites` | List all verified sites in your Search Console account |
| `search_console_query` | Search performance report with clicks, impressions, CTR, and position. Supports filtering by query, page, country, device, and date. |

## Prerequisites

- Python 3.10+
- A Google Cloud project with the **Search Console API** enabled
- OAuth 2.0 credentials (Desktop app type)

## Setup

### 1. Clone and install dependencies

```bash
git clone https://github.com/acamolese/google-search-console-mcp.git
cd google-search-console-mcp

python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

Or with `uv`:

```bash
uv venv
uv pip install -e .
```

### 2. Configure credentials

Copy the example file and replace it with your actual OAuth credentials:

```bash
cp credentials/oauth_credentials.example.json credentials/oauth_credentials.json
```

Download your OAuth 2.0 credentials from Google Cloud Console (APIs & Credentials, Desktop app type) and save the JSON as `credentials/oauth_credentials.json`.

### 3. Get a refresh token

Run the helper script to authorize via browser:

```bash
python3 get_refresh_token.py
```

This will open your browser for Google OAuth consent, capture the authorization code, and save the token to `credentials/token.json`.

### 4. Configure your MCP client

Add the server to your MCP client configuration:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "/path/to/google-search-console-mcp/.venv/bin/python",
      "args": ["/path/to/google-search-console-mcp/server.py"]
    }
  }
}
```

Replace `/path/to/google-search-console-mcp` with the actual path where you cloned the repo.

### 5. Test

Start the server manually to verify it loads without errors:

```bash
python3 server.py
```

The server communicates over stdio, so it will appear to hang (that's expected). Press `Ctrl+C` to stop.

## Usage with Claude

Claude supports MCP servers natively in both the CLI (Claude Code) and the Desktop app.

### Claude Code (CLI)

Edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "/path/to/google-search-console-mcp/.venv/bin/python",
      "args": ["/path/to/google-search-console-mcp/server.py"]
    }
  }
}
```

Restart Claude Code after saving. The tools will appear automatically and you can ask things like:

- "List my verified sites in Search Console"
- "What are my top 50 search queries for example.com in the last 30 days?"
- "Show me the pages with most impressions for sc-domain:example.com from 2026-01-01 to 2026-03-31"
- "Break down search performance by country and device for the last week"

### Claude Desktop App

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "/path/to/google-search-console-mcp/.venv/bin/python",
      "args": ["/path/to/google-search-console-mcp/server.py"]
    }
  }
}
```

Restart the Desktop app. You should see the MCP tools icon in the chat input area.

### Tips

- Use `sc-domain:example.com` for domain properties or `https://example.com/` for URL-prefix properties.
- Available dimensions: `query`, `page`, `country`, `device`, `date` (combine them with commas).
- Maximum 25,000 rows per request.

## Google Cloud Setup Guide

If you don't have a Google Cloud project yet:

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project
3. Enable the **Search Console API**
4. Go to **APIs & Credentials** > **Create Credentials** > **OAuth 2.0 Client ID**
5. Choose **Desktop app** as application type
6. Download the JSON and save it as `credentials/oauth_credentials.json`

## Security

Credential files (`credentials/oauth_credentials.json`, `credentials/token.json`) are excluded via `.gitignore`. Never commit actual credentials to version control.

## License

MIT
