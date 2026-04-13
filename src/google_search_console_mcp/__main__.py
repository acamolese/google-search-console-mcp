"""Command-line entry point for the Google Search Console MCP server.

Usage:
    google-search-console-mcp              # start the MCP server (default)
    google-search-console-mcp serve        # start the MCP server
    google-search-console-mcp auth         # run the OAuth authorization flow

The same entry point dispatches both the server and the auth helper so that
users installing via `pip`, `pipx` or `uvx` only need one command.
"""

from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    command = args[0] if args else "serve"

    if command in ("serve", ""):
        from .server import mcp
        mcp.run()
        return 0

    if command == "auth":
        from .auth import run_oauth_flow
        run_oauth_flow()
        return 0

    if command in ("-h", "--help", "help"):
        print(__doc__)
        return 0

    print(f"Unknown command: {command}\n", file=sys.stderr)
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
