"""Command-line entry point.

mcp-google-search-console serve [--transport stdio|streamable-http]
mcp-google-search-console auth [--no-browser]
mcp-google-search-console doctor
mcp-google-search-console version
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcp-google-search-console",
        description="Google Search Console MCP server.",
    )
    sub = parser.add_subparsers(dest="command")

    serve = sub.add_parser("serve", help="start the MCP server (default)")
    serve.add_argument(
        "--transport",
        choices=("stdio", "streamable-http"),
        default=os.environ.get("MCP_TRANSPORT", "stdio"),
    )
    serve.add_argument("--host", default=os.environ.get("MCP_HOST", "127.0.0.1"))
    serve.add_argument("--port", type=int, default=int(os.environ.get("MCP_PORT", "8765")))

    auth = sub.add_parser("auth", help="run the OAuth authorization flow")
    auth.add_argument(
        "--no-browser",
        action="store_true",
        help="print the URL instead of opening a browser (still needs a local redirect)",
    )

    sub.add_parser("doctor", help="report the current configuration and check access")
    sub.add_parser("version", help="print the package version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    # `mcp-google-search-console` with no arguments starts the server, as before.
    if not args:
        args = ["serve"]

    parser = build_parser()
    parsed = parser.parse_args(args)
    command = parsed.command or "serve"

    if command == "version":
        from . import __version__

        print(__version__)
        return 0

    if command == "auth":
        from .auth.oauth import run_oauth_flow

        run_oauth_flow(open_browser=not parsed.no_browser)
        return 0

    if command == "doctor":
        return _doctor()

    from ._compat import run_server
    from .server import mcp

    os.environ["MCP_TRANSPORT"] = parsed.transport
    run_server(mcp, parsed.transport, host=parsed.host, port=parsed.port)
    return 0


def _doctor() -> int:
    from .client import close_client
    from .tools.diagnostics import as_text, collect_async

    async def run() -> tuple[str, bool]:
        try:
            doctor = await collect_async(os.environ.get("MCP_TRANSPORT", "stdio"))
            return as_text(doctor), doctor.auth.get("status") == "ok"
        finally:
            await close_client()

    text, healthy = asyncio.run(run())
    print(text)
    if not healthy:
        print(
            "\nNo usable credentials. Set GSC_CLIENT_ID + GSC_CLIENT_SECRET + "
            "GSC_REFRESH_TOKEN, or GSC_SERVICE_ACCOUNT_FILE / GSC_SERVICE_ACCOUNT_JSON, "
            "or run `mcp-google-search-console auth`.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
