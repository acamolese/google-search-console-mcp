"""The SDK shim must work identically on mcp 1.x and 2.x."""

from __future__ import annotations

import inspect

import pytest

from google_search_console_mcp import _compat


def test_shim_exports_everything_the_server_needs():
    assert _compat.MCP_MAJOR in (1, 2)
    assert inspect.isclass(_compat.FastMCP)
    assert inspect.isclass(_compat.ToolError)
    assert issubclass(_compat.ToolError, Exception)
    assert _compat.Context is not None
    assert _compat.ToolAnnotations is not None


def test_tool_decorator_accepts_annotations_and_structured_output():
    params = inspect.signature(_compat.FastMCP.tool).parameters
    assert "annotations" in params
    assert "structured_output" in params


def test_mcp_version_is_reported():
    version = _compat.mcp_version()
    assert version != "unknown"
    assert version[0].isdigit()


@pytest.mark.asyncio
async def test_the_server_builds_and_registers_its_tools_on_either_major():
    from google_search_console_mcp.server import mcp

    names = sorted(tool.name for tool in await mcp.list_tools())
    # The eight tools 2.x shipped must survive every rename-free release.
    assert set(names) >= {
        "gsc_audit",
        "gsc_indexing_issues",
        "gsc_inspect_url",
        "gsc_performance_overview",
        "gsc_query",
        "gsc_site_details",
        "gsc_sitemaps",
        "gsc_sites",
    }


def test_run_server_passes_http_options_on_both_majors():
    calls = {}

    class FakeSettings:
        host = ""
        port = 0
        stateless_http = False

    class FakeServer:
        settings = FakeSettings()

        def run(self, transport, **kwargs):
            calls["transport"] = transport
            calls["kwargs"] = kwargs

    server = FakeServer()
    _compat.run_server(server, "streamable-http", host="0.0.0.0", port=9000)

    assert calls["transport"] == "streamable-http"
    if _compat.MCP_MAJOR >= 2:
        assert calls["kwargs"]["host"] == "0.0.0.0"
        assert calls["kwargs"]["port"] == 9000
    else:
        assert server.settings.host == "0.0.0.0"
        assert server.settings.port == 9000


def test_run_server_stdio_takes_no_http_options():
    calls = {}

    class FakeServer:
        def run(self, transport, **kwargs):
            calls["transport"] = transport
            calls["kwargs"] = kwargs

    _compat.run_server(FakeServer(), "stdio")
    assert calls == {"transport": "stdio", "kwargs": {}}
