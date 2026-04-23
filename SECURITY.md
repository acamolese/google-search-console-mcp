# Security Policy

## Reporting a vulnerability

If you discover a security issue in `mcp-google-search-console`, please report it privately so the maintainer can address it before it becomes public.

**Preferred channel:** open a private advisory via GitHub Security Advisories at
<https://github.com/acamolese/google-search-console-mcp/security/advisories/new>.

If you cannot use GitHub advisories, you can email the maintainer through the contact details on the GitHub profile [@acamolese](https://github.com/acamolese).

Please include:

- a clear description of the issue and its impact
- steps to reproduce, ideally with a minimal proof of concept
- the affected version(s) of the package
- any suggested mitigation

You will receive an acknowledgement within 5 business days. Fixes are released as patch versions of `mcp-google-search-console` on PyPI.

## Supported versions

| Version   | Supported          |
|-----------|--------------------|
| 2.x       | :white_check_mark: |
| < 2.0     | :x:                |

Only the latest `2.x` minor is actively supported with security fixes. Older versions should be upgraded.

## Security model and scope

This MCP server talks to the Google Search Console API on behalf of the user. A few design choices keep the blast radius small:

- **Read-only OAuth scope.** The server only requests `https://www.googleapis.com/auth/webmasters.readonly`. It cannot submit sitemaps, request indexing, modify property settings, or delete anything in Search Console.
- **Local execution only.** The server runs locally on the user's machine via `stdio` transport. It does not expose a network socket and is not meant to be hosted as a public service.
- **No telemetry.** The server does not phone home, does not ship analytics, and does not send data anywhere except to Google's official APIs.
- **Credential storage.** Credentials are stored in the user's XDG config directory (`~/.config/mcp-google-search-console/`) with default OS permissions, or supplied through environment variables for stateless/CI use. No credential is embedded in the package, logged, or written outside the user's configured path.
- **Audit reports stay local.** `gsc_audit` writes the HTML report to `~/gsc-reports/` on the user's machine. Nothing is uploaded.

## User responsibilities

- Never commit `oauth_credentials.json`, `token.json`, or `.env` files with real secrets. The shipped `.gitignore` excludes these paths.
- Rotate the OAuth client secret and refresh token if a machine that held them is lost or compromised. You can revoke access at <https://myaccount.google.com/permissions>.
- Keep the package up to date with `uvx --upgrade mcp-google-search-console` or `pipx upgrade mcp-google-search-console`.

## Dependencies

Runtime dependencies are pinned to minimum versions in `pyproject.toml`. The direct dependency surface is intentionally small (official Google auth libraries, the MCP SDK, and Jinja2). Dependabot / Renovate-style bumps are welcome via pull request.
