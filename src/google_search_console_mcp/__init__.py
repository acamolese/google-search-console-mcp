"""Google Search Console MCP server."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("mcp-google-search-console")
except PackageNotFoundError:  # pragma: no cover - source checkout without install
    __version__ = "0.0.0.dev0"

__all__ = ["__version__"]
