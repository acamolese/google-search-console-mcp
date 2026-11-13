"""`auth` must not leak the client secret or the refresh token unless asked."""

from __future__ import annotations

import sys
import types

import pytest

from google_search_console_mcp.auth import oauth

CLIENT = {"client_id": "client-id.apps.googleusercontent.com", "client_secret": "client-secret-value"}


class _FakeCreds:
    client_id = CLIENT["client_id"]
    refresh_token = "1//refresh-secret-value"
    token = "access-token-value"
    expiry = None
    scopes = None


class _FakeFlow:
    @classmethod
    def from_client_config(cls, *_args, **_kwargs):
        return cls()

    def run_local_server(self, **_kwargs):
        return _FakeCreds()


@pytest.fixture
def fake_flow(monkeypatch):
    module = types.ModuleType("google_auth_oauthlib.flow")
    module.InstalledAppFlow = _FakeFlow
    monkeypatch.setitem(sys.modules, "google_auth_oauthlib.flow", module)
    monkeypatch.setattr(oauth.config, "load_oauth_client", lambda: dict(CLIENT))


def test_default_output_has_no_secrets(fake_flow, capsys):
    oauth.run_oauth_flow(open_browser=False)
    out = capsys.readouterr().out
    assert "client-secret-value" not in out
    assert "refresh-secret-value" not in out
    assert "--print-env" in out


def test_print_env_prints_export_lines(fake_flow, capsys):
    oauth.run_oauth_flow(open_browser=False, print_env=True)
    out = capsys.readouterr().out
    assert 'export GSC_CLIENT_SECRET="client-secret-value"' in out
    assert 'export GSC_REFRESH_TOKEN="1//refresh-secret-value"' in out
