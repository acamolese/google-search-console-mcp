#!/usr/bin/env python3
"""Check that every manifest declares the same version.

Five files carry the version now: pyproject.toml, server.json (twice), the
Claude Code plugin, the Cursor plugin and the MCPB manifest. 2.0.3 shipped with
PyPI at 2.0.2 and the registry rejecting the mismatch, which is exactly what
this guards against.

    python scripts/sync_versions.py          # check, exit 1 on a mismatch
    python scripts/sync_versions.py --write  # rewrite them all from pyproject
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"

# path -> list of dotted keys carrying the version
JSON_TARGETS = {
    "server.json": ["version", "packages.0.version"],
    ".claude-plugin/plugin.json": ["version"],
    ".claude-plugin/marketplace.json": ["plugins.0.version"],
    ".cursor-plugin/plugin.json": ["version"],
    "mcpb/manifest.json": ["version"],
}

VERSION_RE = re.compile(r'^version\s*=\s*"([^"]+)"', re.MULTILINE)


def pyproject_version() -> str:
    match = VERSION_RE.search(PYPROJECT.read_text(encoding="utf-8"))
    if not match:
        raise SystemExit("Could not find the version in pyproject.toml")
    return match.group(1)


def dig(data, dotted: str):
    node = data
    for part in dotted.split("."):
        node = node[int(part)] if part.isdigit() else node[part]
    return node


def put(data, dotted: str, value: str) -> None:
    parts = dotted.split(".")
    node = data
    for part in parts[:-1]:
        node = node[int(part)] if part.isdigit() else node[part]
    last = parts[-1]
    if last.isdigit():
        node[int(last)] = value
    else:
        node[last] = value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true", help="rewrite the manifests from pyproject")
    args = parser.parse_args()

    expected = pyproject_version()
    problems: list[str] = []

    for relative, keys in JSON_TARGETS.items():
        path = REPO_ROOT / relative
        if not path.exists():
            problems.append(f"{relative}: missing")
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        changed = False
        for key in keys:
            try:
                found = dig(data, key)
            except (KeyError, IndexError, TypeError):
                problems.append(f"{relative}: no `{key}`")
                continue
            if found == expected:
                continue
            if args.write:
                put(data, key, expected)
                changed = True
            else:
                problems.append(f"{relative}: `{key}` is {found}, expected {expected}")
        if changed:
            path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            print(f"updated {relative}")

    if problems and not args.write:
        print(f"Version mismatch against pyproject.toml ({expected}):", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1

    print(f"All manifests declare {expected}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
