#!/usr/bin/env python3
"""Check a running server over streamable HTTP: connect, initialize, list tools.

Used by the Docker CI job against the container, and usable by hand against any
deployment.

    python scripts/smoke_http.py --url http://127.0.0.1:8765/mcp
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from contextlib import asynccontextmanager

from mcp import ClientSession

DEFAULT_URL = "http://127.0.0.1:8765/mcp"
DEFAULT_MIN_TOOLS = 17


@asynccontextmanager
async def transport(url: str):
    """Open the transport, hiding the rename between mcp 1.x and 2.x."""
    import mcp.client.streamable_http as http

    connect = getattr(http, "streamable_http_client", None) or http.streamablehttp_client
    async with connect(url) as streams:
        # 1.x yields (read, write, get_session_id); 2.x yields a two-item tuple.
        yield streams[0], streams[1]


async def list_tools(url: str) -> list[str]:
    async with transport(url) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        result = await session.list_tools()
        return [tool.name for tool in result.tools]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--min-tools", type=int, default=DEFAULT_MIN_TOOLS)
    parser.add_argument("--timeout", type=float, default=60.0)
    parsed = parser.parse_args()

    print(f"smoke: connecting to {parsed.url}", file=sys.stderr)
    try:
        names = asyncio.run(asyncio.wait_for(list_tools(parsed.url), timeout=parsed.timeout))
    except Exception as exc:  # noqa: BLE001 - any failure is a failed smoke test
        print(f"smoke: FAILED: {exc!r}", file=sys.stderr)
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
