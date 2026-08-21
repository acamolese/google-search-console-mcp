#!/usr/bin/env python3
"""Fresh-install smoke test: start the published entry point and list its tools.

Runs the `mcp-google-search-console` console script as a subprocess, speaks MCP
over stdio with the `mcp` client, and fails if the handshake breaks or fewer
tools than expected come back. No Google credentials are needed: `tools/list`
never touches the API.

Usage:
    python scripts/smoke_stdio.py [--command PATH] [--min-tools N]
"""

from __future__ import annotations

import argparse
import asyncio
import os
import shutil
import sys

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

DEFAULT_COMMAND = "mcp-google-search-console"
DEFAULT_MIN_TOOLS = 8


async def list_tools(command: str, args: list[str]) -> list[str]:
    params = StdioServerParameters(
        command=command,
        args=args,
        # A stray credential in the environment must not turn this into a live test.
        env={k: v for k, v in os.environ.items() if not k.startswith("GSC_")},
    )
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()
        return [tool.name for tool in result.tools]


def resolve_command(explicit: str | None) -> tuple[str, list[str]]:
    if explicit:
        return explicit, ["serve"]
    found = shutil.which(DEFAULT_COMMAND)
    if found:
        return found, ["serve"]
    # Fall back to the module entry point in the current interpreter.
    return sys.executable, ["-m", "google_search_console_mcp", "serve"]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default=None, help="path to the server executable")
    parser.add_argument("--min-tools", type=int, default=DEFAULT_MIN_TOOLS)
    parsed = parser.parse_args()

    command, args = resolve_command(parsed.command)
    print(f"smoke: launching {command} {' '.join(args)}", file=sys.stderr)

    try:
        names = asyncio.run(asyncio.wait_for(list_tools(command, args), timeout=60))
    except Exception as exc:  # noqa: BLE001 - any failure here is a failed smoke test
        print(f"smoke: FAILED to complete the stdio handshake: {exc!r}", file=sys.stderr)
        return 1

    print(f"smoke: {len(names)} tools -> {', '.join(sorted(names))}", file=sys.stderr)
    if len(names) < parsed.min_tools:
        print(
            f"smoke: FAILED, expected at least {parsed.min_tools} tools, got {len(names)}",
            file=sys.stderr,
        )
        return 1

    print("smoke: OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
