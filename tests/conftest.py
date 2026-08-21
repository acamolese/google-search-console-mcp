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
def clean_env(monkeypatch, tmp_path):
    """Isolate every test from the developer's real credentials and config."""
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
