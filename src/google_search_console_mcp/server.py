"""The MCP server instance.

Nothing here writes to stdout: the stdio transport uses it for the protocol.
Logging goes to stderr, always.
"""

from __future__ import annotations

import logging
import os
import sys

from ._compat import FastMCP
from .tools import register_all

INSTRUCTIONS = """Google Search Console, read-only.

Property format matters: `sc-domain:example.com` for a domain property, \
`https://example.com/` (trailing slash) for a URL-prefix one. Call gsc_sites \
when unsure, gsc_doctor when something fails.

Dates are optional: with none given, tools use the last 28 days ending today \
(UTC) and data_state=all, which matches the Search Console UI including today's \
partial data.

Use gsc_audit for a full client-facing report; use the individual tools for \
specific questions. Every response opens with a `# meta ...` line: quote those \
numbers exactly, and do not invent causes for a drop the data does not show."""


def configure_logging() -> None:
    level = os.environ.get("GSC_LOG_LEVEL", "WARNING").upper()
    logging.basicConfig(
        stream=sys.stderr,
        level=getattr(logging, level, logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
    )


def build_server() -> FastMCP:
    configure_logging()
    server = FastMCP("google-search-console", instructions=INSTRUCTIONS)
    register_all(server)
    from .prompts import register_all as register_prompts

    register_prompts(server)
    return server


mcp = build_server()
