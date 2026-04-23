<!-- mcp-name: io.github.acamolese/google-search-console-mcp -->

# Google Search Console MCP Server

[![PyPI version](https://img.shields.io/pypi/v/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)
[![Python versions](https://img.shields.io/pypi/pyversions/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)
[![License: MIT](https://img.shields.io/pypi/l/mcp-google-search-console.svg)](https://github.com/acamolese/google-search-console-mcp/blob/main/LICENSE)
[![PyPI downloads](https://img.shields.io/pypi/dm/mcp-google-search-console.svg)](https://pypi.org/project/mcp-google-search-console/)
[![CI](https://github.com/acamolese/google-search-console-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/acamolese/google-search-console-mcp/actions/workflows/ci.yml)

Read this in: **English** | [Italiano](README.it.md)

Open-source **Model Context Protocol (MCP) server for Google Search Console**. Brings your Search Console performance data, URL inspection, indexing checks, and sitemaps into Claude Code, Claude Desktop, Cursor, Zed, Continue, and any MCP-compatible client, and generates complete brandable HTML **SEO audit reports** in a single call.

If you work with SEO and use an AI coding assistant, this MCP server removes the copy-paste loop between Search Console and your chat: ask for top queries, check which pages are indexed, inspect a URL, or produce a 30/60/90-day SEO roadmap as an HTML report, all without leaving the assistant.

## Features

- **Read-only access** to Search Console (no write operations to your properties, only the `webmasters.readonly` OAuth scope)
- **8 tools** covering sites, performance queries, pages, devices, countries, indexing, sitemaps, URL inspection
- **`gsc_audit`**: one-call generator for a self-contained HTML SEO report with Chart.js graphs, automatic issue detection, concrete examples, actionable strategy and a 30/60/90-day roadmap
- **Brandable reports**: customize logo, font, and color palette via `branding.json`, perfect for agencies delivering white-label audits
- **Stateless-friendly**: credentials via environment variables (ideal for CI, Docker, hosted MCP) or via the XDG config directory
- **Zero setup with `uvx`**: no clone, no virtualenv, runs straight from PyPI
- **Works with any MCP client**: Claude Code, Claude Desktop, Cursor, Zed, Continue, Windsurf

## Why use this MCP server

- Skip the Search Console UI when you already live inside your AI assistant
- Turn GSC data into a shareable client-ready HTML audit in a single prompt
- Keep full control over credentials: choose env vars, XDG config, or legacy file layout
- Safe by design: read-only scope means the server cannot edit or remove anything from your properties
- Python 3.10+, MIT licensed, published on PyPI as [`mcp-google-search-console`](https://pypi.org/project/mcp-google-search-console/)

## Tools

| Tool | Description |
|---|---|
| `gsc_sites` | List all verified sites |
| `gsc_site_details` | Details of a specific site |
| `gsc_query` | Performance report with dimensions (query, page, country, device, date) |
| `gsc_performance_overview` | Aggregated metrics for a period (clicks, impressions, CTR, position) |
| `gsc_indexing_issues` | Check indexing status for a list of pages |
| `gsc_inspect_url` | Detailed URL Inspection for a single page |
| `gsc_sitemaps` | List all sitemaps submitted for a site |
| `gsc_audit` | Generate a complete HTML audit report for a date range |

## Installation

### Option A — `uvx` (recommended, zero setup)

Run directly from PyPI, no clone or venv required:

```bash
uvx mcp-google-search-console auth      # one-time OAuth authorization
uvx mcp-google-search-console            # start the MCP server
```

### Option B — `pipx`

```bash
pipx install mcp-google-search-console
mcp-google-search-console auth
mcp-google-search-console
```

### Option C — From source

```bash
git clone https://github.com/acamolese/google-search-console-mcp.git
cd google-search-console-mcp
uv venv && uv pip install -e .
.venv/bin/mcp-google-search-console auth
```

## Configuration

### 1. Google Cloud setup

1. [Google Cloud Console](https://console.cloud.google.com/) → create a project
2. Enable the **Google Search Console API**
3. **APIs & Credentials** → **Create Credentials** → **OAuth 2.0 Client ID** → **Desktop app**
4. Download the JSON

### 2. Provide the OAuth client credentials

You have three ways, pick whichever fits your setup. The server reads them in this order:

**A — Environment variables** (best for headless, CI, Docker, hosted MCP):

```bash
export GSC_CLIENT_ID="xxxxxxxxxxxx.apps.googleusercontent.com"
export GSC_CLIENT_SECRET="GOCSPX-xxxxxxxxxxxxxxxx"
export GSC_REFRESH_TOKEN="1//0xxxxxxxxxxxxxxxx"
```

With these three variables set, the server is fully stateless: no files are read or written.

**B — XDG config directory** (recommended for local desktop usage):

Save the OAuth client JSON as:

```
~/.config/mcp-google-search-console/oauth_credentials.json
```

Then run the interactive authorization flow:

```bash
mcp-google-search-console auth
```

This opens a browser, captures the OAuth consent and saves the refresh token to `~/.config/mcp-google-search-console/token.json`. On Linux and macOS the path honors `$XDG_CONFIG_HOME` if set.

**C — Legacy per-project directory** (backward compatibility only):

Place files under `./credentials/oauth_credentials.json` and `./credentials/token.json` in the working directory where the server is launched. This mode is still supported for older setups but not recommended.

## Client configuration

All examples below assume you installed with `uvx`. Adjust the command if you used `pipx` (`mcp-google-search-console`) or cloned from source (`/path/to/.venv/bin/mcp-google-search-console`).

### Claude Code

Edit `~/.claude/.mcp.json`:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Claude Desktop

Edit `~/Library/Application Support/Claude/claude_desktop_config.json` (macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows):

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Cursor

Edit `~/.cursor/mcp.json` (or the project-local `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Zed

Add to your Zed `settings.json` under `context_servers`:

```json
{
  "context_servers": {
    "google-search-console": {
      "command": {
        "path": "uvx",
        "args": ["mcp-google-search-console"]
      }
    }
  }
}
```

### Continue, Windsurf, and other MCP clients

Any MCP client that supports stdio servers can use the same pattern:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"]
    }
  }
}
```

### Stateless configuration with environment variables

If you prefer not to persist anything on disk, pass credentials inline:

```json
{
  "mcpServers": {
    "google-search-console": {
      "command": "uvx",
      "args": ["mcp-google-search-console"],
      "env": {
        "GSC_CLIENT_ID": "xxxxxxxxxxxx.apps.googleusercontent.com",
        "GSC_CLIENT_SECRET": "GOCSPX-xxxxxxxxxxxxxxxx",
        "GSC_REFRESH_TOKEN": "1//0xxxxxxxxxxxxxxxx"
      }
    }
  }
}
```

## Usage examples

Once the MCP server is wired into your client, you can ask things like:

- "List my verified sites in Search Console"
- "Show the top 50 queries for `sc-domain:example.com` over the last 30 days"
- "Check if these 5 pages are indexed: ..."
- "Generate a complete audit of `example.com` for the period 2026-01-01 → 2026-03-31"

The `gsc_audit` tool writes a self-contained HTML file to `~/gsc-reports/` and returns the path. Open it in any browser.

### Tips

- Use `sc-domain:example.com` for domain properties or `https://example.com/` for URL-prefix properties.
- Available dimensions for `gsc_query`: `query`, `page`, `country`, `device`, `date` (combine with commas).
- Maximum 25,000 rows per request.

## Customizing the audit report

The audit report layout uses a Jinja2 template in `src/google_search_console_mcp/templates/report.html.j2` with colors and fonts driven by `branding.json`.

To customize without touching the package, create your own `branding.json` in the XDG config directory:

```
~/.config/mcp-google-search-console/branding.json
```

Example:

```json
{
  "brand_name": "Acme SEO Studio",
  "logo": "logo.png",
  "font_family": "Poppins",
  "font_url": "https://fonts.googleapis.com/css2?family=Poppins:wght@400;500;600;700&display=swap",
  "colors": {
    "primary": "#ff6b35",
    "primary_dark": "#cc4a1f",
    "secondary": "#004e89",
    "accent": "#00b894",
    "danger": "#e74c3c",
    "warning": "#f39c12",
    "text": "#004e89",
    "text_muted": "#5a6c7d",
    "text_light": "#8395a7",
    "bg": "#f8f9fc",
    "surface": "#ffffff",
    "border": "#e1e8ed"
  }
}
```

The `logo` field accepts either a local file name (resolved against the XDG config dir, then the package dir) or a full URL. Local files are automatically base64-encoded into the HTML so the report stays self-contained.

You can also pass a custom branding file per report via the `branding_path` parameter of `gsc_audit`:

> "Generate an audit of example.com using the branding at `/path/to/client-branding.json`"

## FAQ

### What is an MCP server?

MCP (Model Context Protocol) is an open protocol that lets AI assistants like Claude or Cursor talk to external data sources and tools through a standard interface. An MCP server exposes a set of tools (functions) and resources that the assistant can call during a conversation. This project is an MCP server that exposes Google Search Console as tools your assistant can use.

### Does this work with Claude Desktop, Claude Code, Cursor, Zed, and Continue?

Yes. Anything that can speak MCP over stdio can use this server. Ready-to-paste configuration snippets for each client are in [Client configuration](#client-configuration).

### Can this server change or delete data in my Search Console account?

No. The server only requests the `webmasters.readonly` scope from Google, which is read-only by design. It cannot submit sitemaps, request indexing, or modify any property settings.

### How do I obtain the OAuth client credentials?

Create a Google Cloud project, enable the Google Search Console API, then create an **OAuth 2.0 Client ID** of type **Desktop app** and download the JSON. Full steps are in the [Configuration](#configuration) section.

### Can I use a service account instead of OAuth?

Not currently. The Search Console API requires that the identity has been granted access to the property, and Google's own docs recommend OAuth user credentials for most use cases. If you need service account support, open an issue.

### Can I customize the SEO audit report?

Yes. Drop a `branding.json` file in `~/.config/mcp-google-search-console/` to override logo, font, and the full color palette. See [Customizing the audit report](#customizing-the-audit-report). You can also pass a per-report `branding_path` parameter when calling `gsc_audit`, which is ideal for agencies producing white-label audits for multiple clients.

### Where are the audit reports saved?

`gsc_audit` writes a self-contained HTML file to `~/gsc-reports/` and returns the path. The file is fully inlined (CSS, charts, images base64-encoded) so you can share it without worrying about external assets.

### What's the difference between `sc-domain:` and URL-prefix properties?

`sc-domain:example.com` covers the entire domain, including all subdomains and both `http`/`https`. `https://example.com/` only covers that specific prefix. Use whichever matches how you verified the property in Search Console.

### Does it work on headless servers or in Docker?

Yes. Set `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` as environment variables and skip the browser `auth` flow. The server is fully stateless in this mode and never writes to disk.

## Security

- Never commit `oauth_credentials.json`, `token.json`, or `.env` files with real secrets.
- The XDG config directory is the default storage location and is outside the repository.
- The server only requests the `webmasters.readonly` scope.

## Troubleshooting

- **401 Unauthorized on first call**: token expired or missing. Run `mcp-google-search-console auth` or set `GSC_REFRESH_TOKEN`.
- **"No OAuth client credentials found"**: neither env vars nor files are configured. See the Configuration section.
- **Browser flow fails on headless machines**: skip `auth` entirely and export `GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN` as environment variables.

## Migration from legacy installs (pre-`f2fe60e`)

The package was restructured in commit `f2fe60e` and no longer ships a top-level `server.py`. If your MCP client was configured to launch the server with `python server.py`, it will now fail at startup with:

```
can't open file '.../server.py': [Errno 2] No such file or directory
```

Update your client config to use the installed entry-point instead:

```json
"google-search-console": {
  "command": "uvx",
  "args": ["mcp-google-search-console"]
}
```

Equivalent forms are listed under [Client configuration](#client-configuration).

## License

[MIT](LICENSE) © Andrea Camolese. Not affiliated with Google or Anthropic. "Google Search Console" is a trademark of Google LLC.
