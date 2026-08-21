"""Shared fixtures. No test in this suite is allowed to touch the network."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"

GSC_ENV_VARS = (
    "GSC_CLIENT_ID",
    "GSC_CLIENT_SECRET",
    "GSC_REFRESH_TOKEN",
    "GSC_ACCESS_TOKEN",
    "GSC_TOKEN_EXPIRY",
    "GSC_AUTH_MODE",
    "GSC_SERVICE_ACCOUNT_FILE",
    "GSC_SERVICE_ACCOUNT_JSON",
    "GSC_REPORT_LANGUAGE",
    "GSC_DATA_STATE",
    "GSC_CACHE_TTL_SECONDS",
    "GSC_INSPECT_CONCURRENCY",
    "GSC_LOG_LEVEL",
    "GOOGLE_APPLICATION_CREDENTIALS",
)


def load_fixture(*parts: str) -> dict:
    """Read a JSON fixture by path parts relative to tests/fixtures/."""
    return json.loads(FIXTURES.joinpath(*parts).read_text(encoding="utf-8"))


@pytest.fixture(autouse=True)
def clean_env(monkeypatch, tmp_path, request):
    """Isolate every test from the developer's real credentials and config.

    Live tests are the exception: they exist to exercise the real credentials,
    so stripping the environment would leave them nothing to authenticate with.
    """
    if request.node.get_closest_marker("live"):
        return tmp_path
    for name in GSC_ENV_VARS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    # config.legacy_creds_dir() resolves against the CWD; keep it inside tmp_path.
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def tmp_config_dir(clean_env):
    """The XDG config dir the package will use during a test."""
    path = Path(os.environ["XDG_CONFIG_HOME"]) / "mcp-google-search-console"
    path.mkdir(parents=True, exist_ok=True)
    return path


class FakeProvider:
    """A credential provider that never touches Google."""

    def __init__(self, token_value: str = "fake-access-token") -> None:
        self._token = token_value
        self.calls = 0

    async def token(self) -> str:
        self.calls += 1
        return self._token

    def describe(self) -> dict:
        return {"status": "ok", "mode": "fake", "source": "tests", "scopes": []}


@pytest.fixture
def fake_provider():
    return FakeProvider()


@pytest.fixture
def settings():
    """Settings with no retry sleeping and a short cache, for fast tests."""
    from google_search_console_mcp.config import Settings

    return Settings(retry_base_delay_seconds=0.0)


@pytest.fixture
async def http_client():
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        yield client


@pytest.fixture
async def gsc_client(fake_provider, http_client, settings):
    from google_search_console_mcp.client import GSCClient

    return GSCClient(fake_provider, http_client, settings=settings)


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch, request):
    """Retry backoff must not actually delay the suite; record the delays instead."""
    import asyncio

    recorded: list[float] = []
    if request.node.get_closest_marker("live"):
        # A live test talking to Google must be allowed to back off for real.
        return recorded
    real_sleep = asyncio.sleep

    async def fake_sleep(delay, *args, **kwargs):
        recorded.append(delay)
        return await real_sleep(0, *args, **kwargs)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return recorded


@pytest.fixture(autouse=True)
def reset_singletons(request):
    """Never let one test's shared client leak into the next."""
    from google_search_console_mcp import client as client_module

    if request.node.get_closest_marker("live"):
        # A live test builds one real client and closes it itself.
        yield
        return
    client_module.reset_client()
    yield
    client_module.reset_client()


async def call_tool(server, name: str, arguments: dict | None = None):
    """Call a tool and return `(text, structured)`, normalized across SDK majors.

    mcp 1.x returns a content sequence (or a tuple with the structured payload),
    2.x returns a CallToolResult. Tests should not care which.
    """
    from google_search_console_mcp._compat import ToolError

    try:
        result = await server.call_tool(name, arguments or {})
    except ToolError as exc:
        # Over the wire this becomes CallToolResult(isError=True); the in-process
        # API raises instead. Tests assert on the message either way.
        return str(exc), None

    content = getattr(result, "content", None)
    structured = getattr(result, "structured_content", None)
    if content is None:
        if isinstance(result, tuple):
            content, structured = result[0], result[1]
        else:
            content = result

    texts = [getattr(block, "text", "") for block in content or []]
    return "\n".join(t for t in texts if t), structured


@pytest.fixture
def server():
    """A fresh server instance with every tool registered."""
    from google_search_console_mcp._compat import FastMCP
    from google_search_console_mcp.tools import register_all

    instance = FastMCP("google-search-console-test")
    register_all(instance)
    return instance


@pytest.fixture
def wired_client(monkeypatch, gsc_client):
    """Point the tools' shared client at the mocked one."""
    from google_search_console_mcp import client as client_module

    monkeypatch.setattr(client_module, "get_client", lambda: gsc_client)
    return gsc_client
