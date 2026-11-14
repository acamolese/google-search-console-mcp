# Changelog

All notable changes to `mcp-google-search-console` are documented in this file. The format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project adheres to [Semantic Versioning](https://semver.org/).

## [Unreleased]

_Nothing yet._

## [4.0.0] - 2026-11-14

4.0 is about trust. Every number the server reports now says what it is based on,
and nothing incomplete is presented as a finding: windows hold whole days,
truncated reads and skipped sections are declared, and the rules that produced
false alarms on real properties have been corrected.

### Breaking changes

- **Comparison windows end on the last day with final data.** When no end date
  is given, `gsc_performance_overview` (with a comparison), `gsc_compare_periods`,
  `gsc_traffic_drops`, `gsc_alerts`, `gsc_portfolio` and `gsc_audit` anchor rolling
  windows to the last day Search Console has final data for, usually three or four
  days ago, and report it as `data_through`. On a real property a 7-day window
  ending today held about five and a half days of data and started 15-20% down.
  `gsc_query` is unchanged and still matches the Search Console UI. Pass `date_to`
  to keep the old behaviour.
- **`gsc_content_decay` compares complete calendar months only.** The month in
  progress is left out (`last_month` and `partial_month_excluded` in the meta);
  half a month next to whole months made almost every page look in decline. The
  audit does the same.
- **The traffic-drop diagnosis `demand_decline` is now `fewer_impressions`.** Page
  data shows fewer impressions at a stable position; it cannot tell lower demand
  from a page that ranks for fewer queries. `disappeared` now means the page has
  no impressions at all, not just no clicks.
- **Stricter parameters.** A filter without `dimension` (it used to filter on
  `query`), a filter on `date` or `hour`, `filter_group_type="or"`, an unknown
  `thresholds` key and `dimension=date|hour` in `gsc_compare_periods` are refused
  with a message instead of failing silently or with a 400 from Google.
- **A partial `ctr_curve` is merged with the default** instead of replacing it,
  so overriding positions 1-3 no longer drops positions 4-10 to 1.5%.
- **`gsc_alerts` no longer takes `thresholds`.** Its rules are fixed so an alert
  means the same thing on every property; the meta lists them under `rules`.
- **Audit summary.** `brand.brand_clicks_pct` is replaced by `brand_pct`,
  `non_brand_pct`, `anonymized_pct` and `basis`; the quick win
  `canonicalize_pagination` is replaced by `review_pagination`.
- **Meta values with spaces are quoted** in the TSV header line, so a filter
  expression or a warning no longer breaks `key=value` parsing.

### Added

- `gsc_brand_split`: brand, non-brand and undisclosed clicks month by month,
  computed over every query with server-side regex filters, so no row limit
  applies. Complete months only.
- `compare="year"` on `gsc_performance_overview`, `gsc_compare_periods`,
  `gsc_traffic_drops`, `gsc_alerts` and `gsc_audit`. Whole months compare with the
  same months last year; other ranges move back 364 days so weekdays line up.
- `filters` and `type` on `gsc_quick_wins`, `gsc_ctr_gaps`, `gsc_cannibalization`,
  `gsc_traffic_drops`, `gsc_content_decay`, `gsc_alerts`, `gsc_compare_periods` and
  `gsc_performance_overview`, with the same syntax as `gsc_query`.
- `brand_terms` on `gsc_cannibalization`.
- `baseline_warning` when a baseline starts before the 16 months Search Console
  keeps, instead of a half-empty baseline reading as a collapse.
- In the audit: brand totals over every query, a "Pages in steady decline"
  section, a "How to read this report" section (comparison, thresholds, brand
  terms, the CTR curve), translated inspection verdicts, a data table behind the
  trend chart, and `content_decay_top5`, `compare` and `truncated` in the summary.
- `mypy` runs in CI, and the release workflow refuses a tag that does not match
  the version every manifest declares.

### Fixed

- **Truncation is declared.** Analysis tools report `truncated` in the meta, and a
  page missing from a current period read only up to its row limit is no longer
  reported as disappeared by `gsc_traffic_drops`, `gsc_alerts` or the audit.
  `gsc_compare_periods` flags each side; `gsc_portfolio` reports `total_properties`.
- **Failed URL Inspections are no longer indexing problems.** In the audit they
  are listed in `skipped_sections` (with how many pages went unchecked) and the raw
  error no longer reaches the client's table. `NEUTRAL` and `PARTIAL` verdicts are
  a medium finding; only `FAIL` is high.
- **The audit inspects the pages that lost the most clicks first**, then the top
  pages, which are indexed almost by definition.
- **Pagination rule.** It recognised only `?p=`, which is WordPress's default post
  permalink, rated it high and advised a canonical to page one, which Google
  advises against. It now recognises `page`, `paged`, `pg` and `/page/N/` (and `p`
  only when the same path ranks without it), is a low, informational finding, and
  advises self-referencing canonicals.
- **Brand terms match whole words.** A short brand such as "nova" no longer claims
  "innovazione", and "arte" no longer claims "partenza". Spaces inside a term are
  still tolerated.
- **Cannibalisation** leaves out brand queries and queries where one page sits in
  the top three with most of the clicks, and judges size on impressions, so a split
  that leaves every page without clicks is no longer filtered out.
- **One definition of a low CTR.** The two CTR issues use the expected-CTR curve,
  like the CTR-gap section, instead of fixed 2% and 1.5% ceilings.
- **Thresholds per kind of row.** The audit computes them separately on queries and
  on pages, and reads 5,000 queries and pages (25,000 pairs), like the tools.
- **The estimated uplift no longer double counts.** It sums the top 10 page-two
  opportunities and says so, instead of adding query and page opportunities for the
  same clicks.
- **`gsc_alerts` and `gsc_content_decay` report the cut-offs they actually apply**
  instead of adaptive thresholds they ignored.
- **Report copy.** No FAQPage markup advice, roadmap steps for backlinks and
  competitors only when the data points there, content hubs only for themes with at
  least ten queries, a proper title for the lost-pages table, and "brand" instead of
  "di marca" in Italian.
- **Accessibility.** Charts have a text alternative, table headers carry `scope`,
  headings no longer skip a level, and the default light text and warning colours
  pass WCAG AA contrast.
- **Client.** A `Retry-After` longer than 60 seconds fails fast with a hint instead
  of blocking the tool, and the `cache` meta covers every request of the call
  (`hit`, `miss` or `mixed`) instead of the last one.
- The trend chart sorts its rows by date instead of relying on the API's order.
- `gsc_audit` no longer turns a failed optional call into a clean-looking empty
  section: sitemaps, page history and brand totals are listed in
  `skipped_sections` and marked "not checked" in the report. Reported in #2.

## [3.0.2] - 2026-11-13

### Security

- `auth` no longer prints the OAuth client secret and the refresh token to stdout. Terminal scrollback, CI logs and agent transcripts kept a long-lived credential in plain text. The `export GSC_*` lines are now printed only with the new `--print-env` flag.

## [3.0.1] - 2026-08-22

### Fixed

- Restored the `mcp-name: io.github.acamolese/google-search-console-mcp` marker at the top of the README. The MCP registry reads it from the published PyPI page to prove the package and the server entry belong to the same owner, and the 3.0.0 README rewrite dropped it, so `mcp-publisher publish` was refused. A test now fails the build if it goes missing again.

## [3.0.0] - 2026-08-21

### Breaking changes

- **Default response format is TSV, not JSON.** Every tabular tool opens with a `# meta key=value ...` line and returns tab-separated rows. A 100-row query cost roughly 3,400 tokens as pretty-printed JSON and costs about 1,100 as TSV. Pass `response_format="json"` for a compact `{"meta": ..., "rows": [...]}` object; the old indented form is gone.
- **Metrics are numbers.** `ctr` and `position` used to be returned as strings (`"0.0223"`, `"6.4"`). They are now a float rounded to 4 and 1 decimals.
- **`row_limit` defaults to 100 and is capped at 1,000 per call.** It accepted 25,000 with no guard, which is roughly 850k tokens in one response. Use `start_row` to page; the cap is reported in the meta rather than applied silently.
- **`data_state` defaults to `all`**, matching what the Search Console UI shows, including today's partial data. Pass `data_state="final"` for the old behaviour.
- **The audit report defaults to English.** Set `language="it"` or `GSC_REPORT_LANGUAGE=it` for Italian.
- **`gsc_audit` returns a JSON summary first**, then the report path or the document, instead of a bare `{"report_path": ...}`. The range is now `range: [from, to]` rather than separate `date_from` / `date_to` keys.
- **`gsc_inspect_url` returns structured output** with snake_case fields instead of a JSON string of Google's raw payload.
- The `audit` module is now a package, and `auth` is a package. Anything importing `google_search_console_mcp.audit.generate_audit` or `google_search_console_mcp.auth.run_oauth_flow` directly needs updating; the MCP surface is unaffected.

No tool was renamed or removed, and no environment variable changed.

### Added

- **Seven analysis tools**: `gsc_quick_wins`, `gsc_ctr_gaps`, `gsc_cannibalization`, `gsc_traffic_drops`, `gsc_content_decay`, `gsc_alerts`, `gsc_portfolio`. Each runs its rule server-side and reports the thresholds it applied, so the answer can be checked rather than trusted. `gsc_traffic_drops` distinguishes a ranking loss from falling demand, a collapsed CTR and a page dropping out of the index.
- `gsc_compare_periods`: joins two periods on one dimension and ranks the biggest movers in both directions.
- `gsc_doctor` and a `doctor` CLI command: auth mode, token expiry, accessible properties, cache counters, defaults and paths. Secrets masked. This is the first thing to run when a client reports the server will not start.
- **Relative dates**: `period` (`last_7_days`, `last_28_days`, `last_3_months`, `last_month`, `this_month`, `last_16_months`) and `days`, resolved server-side in UTC. With no dates at all, tools use the last 28 days. Out-of-range requests are refused with the earliest available date named.
- **Fuller API coverage** on `gsc_query`: `type`, `dataState`, `dimensionFilterGroups` including regex operators, `startRow`, `aggregationType`, and the `searchAppearance` and `hour` dimensions. `hour` sets the hourly data state and enforces the 10-day window.
- **Service account and Application Default Credentials**, alongside the existing OAuth flow.
- **Three MCP prompts**: `gsc_weekly_report`, `gsc_indexing_audit`, `gsc_content_opportunities`.
- **Distribution**: a Claude Code plugin with five skills and the repository as its own marketplace, a Cursor plugin, an `.mcpb` bundle for Claude Desktop, and a Dockerfile serving streamable HTTP.
- `scripts/render_sample_report.py` renders the report from committed synthetic data with no credentials; `scripts/smoke_stdio.py` and `scripts/smoke_http.py` verify a real install over each transport; `scripts/sync_versions.py` keeps the five manifests in step.
- A test suite of 280+ tests at 93% coverage, run against both `mcp` majors on Linux, macOS and Windows.

### Changed

- **The transport is async.** Tools issued synchronous `urllib` calls that blocked the event loop. Everything now goes through one shared `httpx.AsyncClient` with retries on 429 and 5xx (four attempts, exponential backoff with jitter, honouring `Retry-After`), no retry on a daily quota error, a six-hour response cache, and a concurrency cap on URL inspections. `gsc_audit` collects in parallel instead of making nineteen calls in sequence.
- **Credentials are resolved once per process.** In environment-variable mode the old code forced the token expiry to 1970, so every API call refreshed first: `gsc_audit` turned 19 calls into 38 round trips. A lock now coalesces concurrent refreshes.
- **Errors carry Google's reason and a hint.** A 403 now says whether it is a property-format problem, a permissions problem, a per-minute rate limit or an exhausted daily quota, and what to do about it.
- **The audit report is genuinely self-contained.** Chart.js 4.5.1 is vendored and inlined, the default font stack is the system one, and a test asserts the document contains no external URL. The 2.x report loaded both from a CDN.
- **Report thresholds adapt to the property.** The hardcoded 2,000 and 5,000 impression floors produced an empty report on a small site and flagged half the catalogue on a large one. They are now percentiles of the data with a floor, overridable per call or per client.
- **Report copy moved into `i18n/`**, English and Italian, with locale-aware number formatting and correct singular forms. The Italian strings that named a former client's product categories are gone.
- **Tool argument documentation moved into the JSON schema**, where clients render it. The whole tool-description surface went from over 5,000 characters to about 3,500.
- The interactive OAuth flow uses `InstalledAppFlow`: PKCE, a `state` parameter, a free port instead of a hardcoded 8080, and a five-minute timeout. Refreshed tokens are written atomically with `0600` permissions, and only when they came from a file.
- The CLI takes real subcommands (`serve`, `auth`, `doctor`, `version`) with `--transport`, `--host` and `--port`.
- The URL Inspection quota is documented correctly: 600 per minute and 2,000 per day per property, not the "~60 per minute" the old docstrings claimed.

### Fixed

- `gsc_indexing_issues` ran its inspections one at a time; they now run concurrently behind a semaphore, with per-URL error isolation, and the call is refused above 100 URLs rather than quietly burning quota.
- The expected-CTR curve clamped at position 10, so a result at position 25 was credited with a first-page CTR and the gap rules under-reported.
- `gsc_sitemaps` now reports the submitted and indexed URL counts Google returns.

## [2.0.4] - 2026-08-21

### Fixed

- **The server no longer fails to start on a clean install.** `mcp` 2.0.0 removed `mcp.server.fastmcp`, and the dependency was declared as `mcp>=1.0.0` with no upper bound, so `pip install mcp-google-search-console` or `uvx mcp-google-search-console` resolved the new major and died with `ModuleNotFoundError: No module named 'mcp.server.fastmcp'`. The dependency is now `mcp>=1.12,<3` and a new `_compat` module imports the high-level server class from whichever major is installed.
- Token expiry is now written as an offset-aware ISO timestamp and parsed back into the naive UTC value `google-auth` expects. Expiry values written by 2.0.x are still read correctly. Replaces the deprecated `datetime.utcnow()`.

### Added

- `_compat` module: the single place that knows about SDK differences (`FastMCP`/`MCPServer`, `ToolError`, transport options).
- Test suite (`pytest`) covering the shim, the tool registry and expiry handling, run in CI against both `mcp<2` and `mcp>=2`.
- `scripts/smoke_stdio.py`: builds nothing, installs nothing, just starts the published entry point over stdio and asserts the tool list comes back. Wired into a `fresh-install` CI job on Linux, macOS and Windows.
- `.github/workflows/release.yml`: tagged releases run the suite, build, publish to PyPI with trusted publishing and open a GitHub Release from the CHANGELOG.
- `docs/RELEASING.md` and `docs/DECISIONS.md`.

### Changed

- The `lint` CI job no longer carries `continue-on-error`: `ruff check` and `ruff format --check` now gate the build, with a stricter rule set (`E`, `F`, `I`, `UP`, `B`, `BLE`, `DTZ`, `S`, `SIM`).
- `__version__` is read from the installed package metadata instead of being hardcoded (it had drifted to `2.0.0`).

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
