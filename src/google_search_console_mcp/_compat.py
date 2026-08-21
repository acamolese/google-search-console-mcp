"""Compatibility shim across MCP Python SDK major versions.

`mcp` 2.0.0 removed `mcp.server.fastmcp` and renamed the high-level server
class to `MCPServer` under `mcp.server.mcpserver`. Everything this package
needs is re-exported from here so the rest of the codebase never imports
`mcp.server.*` directly.

The public alias stays `FastMCP` so call sites read the same on both majors.
"""

from __future__ import annotations

from typing import Any

try:  # mcp >= 2
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError

    MCP_MAJOR = 2
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import Context, FastMCP
    from mcp.server.fastmcp.exceptions import ToolError

    MCP_MAJOR = 1

from mcp.types import EmbeddedResource, TextContent, TextResourceContents, ToolAnnotations

__all__ = [
    "MCP_MAJOR",
    "Context",
    "EmbeddedResource",
    "FastMCP",
    "TextContent",
    "TextResourceContents",
    "ToolAnnotations",
    "ToolError",
    "mcp_version",
    "run_server",
]


def mcp_version() -> str:
    """Installed version of the `mcp` package, or "unknown"."""
    from importlib.metadata import PackageNotFoundError, version

    try:
        return version("mcp")
    except PackageNotFoundError:  # pragma: no cover - defensive
        return "unknown"


def run_server(
    server: Any,
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
) -> None:
    """Start `server` on `transport`, hiding the 1.x/2.x transport-option split.

    On 1.x the HTTP bind address lives on `server.settings`; on 2.x it is passed
    as keyword arguments to `run()`.
    """
    if transport == "stdio":
        server.run("stdio")
        return

    if MCP_MAJOR >= 2:
        server.run(transport, host=host, port=port, stateless_http=True)
        return

    settings = getattr(server, "settings", None)
    if settings is not None:
        settings.host = host
        settings.port = port
        if hasattr(settings, "stateless_http"):
            settings.stateless_http = True
    server.run(transport)
