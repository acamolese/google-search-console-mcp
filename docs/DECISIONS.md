# Decisions

One line per choice that the brief did not cover, newest last.

| Date | Decision | Why |
|---|---|---|
| 2026-08-21 | `uv.lock` stays untracked (added to `.gitignore`). | The project ships as a library on PyPI and CI installs from `pyproject.toml`; a lock file would only pin the developer's machine. |
| 2026-08-21 | `_compat.py` exports the 2.x class under the historical name `FastMCP`. | Keeps every call site identical across majors instead of branching on the SDK version at each usage. |
| 2026-08-21 | `Credentials.expiry` is kept naive UTC in memory and written as offset-aware ISO on disk. | `google-auth` compares `expiry` against a naive UTC "now" and raises on aware values; the on-disk format stays unambiguous for future readers. |
| 2026-08-21 | `E501` is exempted for `audit.py` in 2.0.4 only. | The long lines are the hardcoded Italian report copy; they move into `i18n/it.json` in 3.0.0 and the exemption goes with them. |
| 2026-08-21 | `urllib` call sites carry `# noqa: S310` instead of being rewritten in the hotfix. | 2.0.4 must not change runtime behaviour; the transport moves to `httpx` in 3.0.0. |
