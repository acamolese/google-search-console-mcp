# Releasing

Every release goes out from `main` with a green CI run.

## 1. Prepare

```bash
uv venv && uv pip install -e ".[dev]"
ruff check src tests scripts && ruff format --check src tests scripts
pytest -q
```

- Bump the version in `pyproject.toml` and `server.json` (both `version` and
  `packages[0].version`).
- Add a dated section to `CHANGELOG.md` with `Added` / `Changed` / `Fixed` /
  `Removed` entries. Breaking changes get their own note at the top of the section.
- Record any decision the brief did not cover in `docs/DECISIONS.md`.

## 2. Verify a clean install

The failure mode this guards against is a dependency that only breaks on a fresh
resolve, which is exactly how 2.0.3 shipped a server that could not start.

```bash
python -m build
uv venv /tmp/fresh
uv pip install --python /tmp/fresh/bin/python --no-cache dist/*.whl
/tmp/fresh/bin/python scripts/smoke_stdio.py --command /tmp/fresh/bin/mcp-google-search-console
```

## 3. Tag

```bash
git tag -a vX.Y.Z -m "vX.Y.Z"
git push origin vX.Y.Z
```

The `Release` workflow runs the suite, builds the distributions, publishes them to
PyPI with trusted publishing, and opens a GitHub Release carrying the matching
CHANGELOG section.

### PyPI trusted publishing, one-time setup

The `publish` job authenticates with an OIDC token instead of an API key, which
means there is no secret to leak or rotate. It has to be registered on pypi.org
once, under the project's *Publishing* settings:

| Field | Value |
|---|---|
| PyPI project name | `mcp-google-search-console` |
| Owner | `acamolese` |
| Repository name | `google-search-console-mcp` |
| Workflow name | `release.yml` |
| Environment name | `pypi` |

Until that exists, the job fails with `invalid-publisher: valid token, but no
corresponding publisher`, and prints the claims it presented. Those claims are
what the table above has to match.

The `pypi` environment also has to exist under the repository's Settings →
Environments. Adding a required reviewer there turns every publish into an
explicit approval, which is worth doing.

## 4. Publish to the MCP registry (manual)

The registry validates the version against PyPI, so publish to PyPI first and wait
for the release to be visible.

```bash
mcp-publisher login github
mcp-publisher publish
```

## 5. Check what the storefronts say

Four places carry a description, and three of them only change when something is
published:

| Where | Source | Updates when |
|---|---|---|
| PyPI summary | `pyproject.toml` `description` | a release is published |
| PyPI page body | `README.md` | a release is published |
| MCP registry | `server.json` `description` (≤ 100 chars) | `mcp-publisher publish` |
| GitHub repo | repo description and topics | edited directly, any time |

The GitHub Release body is extracted from the CHANGELOG section matching the tag.
A patch release therefore shows only the patch note, even though it is the one
marked *Latest* and the first thing a visitor reads. When a patch follows a major,
edit the release body to lead with what the major brought:

```bash
gh release edit vX.Y.Z --notes-file notes.md
```

## 6. Refresh the directories

Glama, Smithery and PulseMCP re-read the repository on their own schedule; only
touch them if the listing is still stale a few days later.
