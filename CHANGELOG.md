# Changelog

All notable changes to `mcp-google-search-console` are documented in this file. The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [2.0.3] - 2026-04-23

### Changed

- Expanded tool docstrings for `gsc_indexing_issues`, `gsc_inspect_url`, and `gsc_sitemaps` so every tool now exposes a clear purpose, argument formats, return-value schema, and quota/scope notes. Improves tool-quality grading on MCP directories like Glama and makes the tools easier to invoke correctly from AI clients.

### Added

- `SECURITY.md` with vulnerability reporting policy and the server's security model.
- `CHANGELOG.md`.
- `glama.json` manifest.
- GitHub Actions CI workflow (build + smoke import across Linux/macOS/Windows and Python 3.10-3.13, plus a `ruff` lint job).
- Issue templates (bug report, feature request) and a PR template.

### Fixed

- Hardened `.gitignore` to exclude `.mcpregistry_*` publish tokens, `.env*` files, and common IDE/cache folders.

## [2.0.2] - 2026-04-14

### Changed

- Shortened the `server.json` description to meet the MCP Registry 100-character limit.
- Prepared metadata for MCP Registry publication.

## [2.0.1] - 2026-04-14

### Added

- Italian translation (`README.it.md`) and language switcher at the top of the README.
- Expanded metadata (keywords, classifiers, project URLs) for discoverability on PyPI.

## [2.0.0] - 2026-04-13

### Changed

- Restructured the project as an installable Python package; the legacy top-level `server.py` entry point is no longer shipped.
- Renamed the PyPI distribution to `mcp-google-search-console`.
- Credentials now read in order from env vars (`GSC_CLIENT_ID`, `GSC_CLIENT_SECRET`, `GSC_REFRESH_TOKEN`), the XDG config directory (`~/.config/mcp-google-search-console/`), and finally the legacy `./credentials/` folder for backward compatibility.

### Added

- Jinja2-based audit report template with `branding.json` support for white-label reports.
- Robust token refresh flow.
- New tools: `gsc_sites`, `gsc_site_details`, `gsc_query`, `gsc_performance_overview`, `gsc_indexing_issues`, `gsc_inspect_url`, `gsc_sitemaps`, `gsc_audit`.

### Removed

- Top-level `server.py` (replaced by the `mcp-google-search-console` console script). See the migration notes in the README.

## [1.x] - earlier

Earlier versions distributed the server as a script. Not recommended, please upgrade to `2.x`.
