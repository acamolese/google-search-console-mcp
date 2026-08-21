# Decisions

One line per choice that the brief did not cover, newest last.

| Date | Decision | Why |
|---|---|---|
| 2026-08-21 | `uv.lock` stays untracked (added to `.gitignore`). | The project ships as a library on PyPI and CI installs from `pyproject.toml`; a lock file would only pin the developer's machine. |
| 2026-08-21 | `_compat.py` exports the 2.x class under the historical name `FastMCP`. | Keeps every call site identical across majors instead of branching on the SDK version at each usage. |
| 2026-08-21 | `Credentials.expiry` is kept naive UTC in memory and written as offset-aware ISO on disk. | `google-auth` compares `expiry` against a naive UTC "now" and raises on aware values; the on-disk format stays unambiguous for future readers. |
| 2026-08-21 | `E501` is exempted for `audit.py` in 2.0.4 only. | The long lines are the hardcoded Italian report copy; they move into `i18n/it.json` in 3.0.0 and the exemption goes with them. |
| 2026-08-21 | `urllib` call sites carry `# noqa: S310` instead of being rewritten in the hotfix. | 2.0.4 must not change runtime behaviour; the transport moves to `httpx` in 3.0.0. |
| 2026-08-21 | The classic `www.googleapis.com/webmasters/v3` host is kept for analytics, sites and sitemaps. | The discovery document lists `searchconsole.googleapis.com` as canonical, but both work and the old host is the one already proven against real properties. Inspection uses the v1 host, as it must. |
| 2026-08-21 | Per-argument documentation lives in the JSON schema (`Annotated` + `Field`), not in the docstrings. | The schema is where clients render argument help, and moving it there took the whole tool-description surface from over 5,000 characters to about 3,500 while keeping every tool under the 1,200-character budget. |
| 2026-08-21 | `filter_group_type` accepts only `and`. | The API's `groupType` enum has a single value; multiple groups are OR-ed together, filters inside one group are AND-ed. |
| 2026-08-21 | Chart.js is pinned at 4.5.1 (MIT), vendored under `static/` with its licence. | The report has to open without a network. The version is pinned so a silent upgrade cannot change how a client report renders. |
| 2026-08-21 | Plurals are handled with a `_one` key variant, chosen when the count is exactly 1. | English and Italian share the same one/other split. A full plural-rules library would be a dependency for two languages that do not need it. |
| 2026-08-21 | The report's expected-CTR curve collapses to a single low value past position 10. | The 2.x code clamped to position 10, so a result at position 25 was credited with a first-page CTR and the gap rules under-reported. |
| 2026-08-21 | `content_decay` only considers pages present in every month of the window. | A page missing from a month has no click figure to compare, and treating the gap as zero would invent a decline that did not happen. |
| 2026-08-21 | The MCPB manifest does not declare the prompts. | The bundle format wants each prompt's full text inline, which would duplicate `prompts.py` and drift from it. The server still serves all three over `prompts/list`. |
| 2026-08-21 | The bundle launches `uvx` rather than embedding a Python runtime. | The MCPB spec's native `uv` runtime is still experimental. Requiring `uv` on the machine is documented in the manifest and both READMEs; revisit when the runtime stabilises. |
| 2026-08-21 | The Docker image was not built locally during this work. | No Docker daemon was running on the machine. The `docker` CI job builds it and asserts the container answers `tools/list` over streamable HTTP. |
| 2026-08-21 | The bundle icon is generated from `mcpb/icon.source.html` with headless Chrome. | Keeps the source of the artwork in the repository and editable, with no image-editing dependency and no third-party generation service. |

