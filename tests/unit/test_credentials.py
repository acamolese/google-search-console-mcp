"""Credential resolution, refresh coalescing and on-disk hygiene."""

from __future__ import annotations

import asyncio
import json
import os
import stat
import sys
from datetime import timedelta

import pytest

from google_search_console_mcp import config
from google_search_console_mcp.auth.credentials import (
    MODE_ADC,
    MODE_OAUTH,
    MODE_SERVICE_ACCOUNT,
    CredentialProvider,
    mask,
)
from google_search_console_mcp.errors import GSCError

SERVICE_ACCOUNT_INFO = {
    "type": "service_account",
    "project_id": "example",
    "private_key_id": "abc",
    "private_key": "-----BEGIN PRIVATE KEY-----\nfake\n-----END PRIVATE KEY-----\n",
    "client_email": "gsc@example.iam.gserviceaccount.com",
    "client_id": "123",
    "token_uri": "https://oauth2.googleapis.com/token",
}


class FakeCredentials:
    """Stands in for a google-auth Credentials object."""

    def __init__(self, token=None, expiry=None, **kwargs):
        self.token = token
        self.expiry = expiry
        self.refresh_calls = 0
        self.client_id = kwargs.get("client_id")
        self.scopes = kwargs.get("scopes")
        self.valid = token is not None

    def refresh(self, _request):
        self.refresh_calls += 1
        self.token = f"refreshed-{self.refresh_calls}"
        self.expiry = config.now_utc().replace(tzinfo=None) + timedelta(hours=1)
        self.valid = True


@pytest.fixture
def oauth_env(monkeypatch):
    monkeypatch.setenv("GSC_CLIENT_ID", "client-id-value")
    monkeypatch.setenv("GSC_CLIENT_SECRET", "client-secret-value")
    monkeypatch.setenv("GSC_REFRESH_TOKEN", "refresh-token-value")


@pytest.fixture
def patch_oauth_credentials(monkeypatch):
    """Swap google-auth's Credentials for the fake, and record the instance."""
    created = []

    def factory(**kwargs):
        instance = FakeCredentials(**kwargs)
        created.append(instance)
        return instance

    import google.oauth2.credentials as google_credentials

    monkeypatch.setattr(google_credentials, "Credentials", factory)
    return created


# -- precedence -------------------------------------------------------------


def test_environment_oauth_wins_over_a_token_file(oauth_env, tmp_config_dir, patch_oauth_credentials):
    (tmp_config_dir / "token.json").write_text(json.dumps({"refresh_token": "from-file"}))
    (tmp_config_dir / "oauth_credentials.json").write_text(
        json.dumps({"client_id": "file-id", "client_secret": "file-secret"})
    )

    provider = CredentialProvider()
    info = provider.describe()

    assert info["mode"] == MODE_OAUTH
    assert info["source"] == "environment variables"
    assert patch_oauth_credentials[0].client_id == "client-id-value"


def test_a_service_account_file_wins_over_oauth_env(oauth_env, tmp_path, monkeypatch):
    path = tmp_path / "sa.json"
    path.write_text(json.dumps(SERVICE_ACCOUNT_INFO))
    monkeypatch.setenv("GSC_SERVICE_ACCOUNT_FILE", str(path))

    from google.oauth2 import service_account

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_file",
        classmethod(lambda cls, p, scopes: FakeCredentials(token="sa-token")),
    )

    provider = CredentialProvider()
    assert provider.describe()["mode"] == MODE_SERVICE_ACCOUNT


def test_an_inline_service_account_json_is_accepted(monkeypatch):
    monkeypatch.setenv("GSC_SERVICE_ACCOUNT_JSON", json.dumps(SERVICE_ACCOUNT_INFO))

    from google.oauth2 import service_account

    monkeypatch.setattr(
        service_account.Credentials,
        "from_service_account_info",
        classmethod(lambda cls, info, scopes: FakeCredentials(token="sa-token")),
    )

    provider = CredentialProvider()
    info = provider.describe()
    assert info["mode"] == MODE_SERVICE_ACCOUNT
    assert info["source"] == "env:GSC_SERVICE_ACCOUNT_JSON"


def test_broken_inline_service_account_json_is_reported(monkeypatch):
    monkeypatch.setenv("GSC_SERVICE_ACCOUNT_JSON", "{not json")
    assert "not valid JSON" in CredentialProvider().describe()["detail"]


def test_a_token_file_is_used_when_no_environment_variable_is_set(tmp_config_dir, patch_oauth_credentials):
    (tmp_config_dir / "oauth_credentials.json").write_text(
        json.dumps({"installed": {"client_id": "file-id", "client_secret": "file-secret"}})
    )
    (tmp_config_dir / "token.json").write_text(
        json.dumps({"refresh_token": "file-refresh", "expiry": "2026-08-21T10:00:00"})
    )

    provider = CredentialProvider()
    info = provider.describe()

    assert info["mode"] == MODE_OAUTH
    assert info["source"].endswith("token.json")
    assert patch_oauth_credentials[0].client_id == "file-id"


def test_application_default_credentials_are_the_last_resort(monkeypatch):
    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes: (FakeCredentials(token="adc"), "proj"))

    provider = CredentialProvider()
    assert provider.describe()["mode"] == MODE_ADC


def test_no_credentials_at_all_produces_a_three_option_message(monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def boom(scopes):
        raise DefaultCredentialsError("nothing here")

    monkeypatch.setattr(google.auth, "default", boom)

    detail = CredentialProvider().describe()["detail"]
    assert "GSC_REFRESH_TOKEN" in detail
    assert "GSC_SERVICE_ACCOUNT_FILE" in detail
    assert "mcp-google-search-console auth" in detail


def test_an_unknown_auth_mode_is_rejected(monkeypatch):
    monkeypatch.setenv("GSC_AUTH_MODE", "magic")
    assert "GSC_AUTH_MODE" in CredentialProvider().describe()["detail"]


def test_an_explicit_auth_mode_overrides_the_precedence(monkeypatch, oauth_env):
    monkeypatch.setenv("GSC_AUTH_MODE", "adc")
    import google.auth

    monkeypatch.setattr(google.auth, "default", lambda scopes: (FakeCredentials(token="adc"), "p"))

    assert CredentialProvider().describe()["mode"] == MODE_ADC


# -- refresh ----------------------------------------------------------------


async def test_a_stale_token_is_refreshed_once_under_concurrency(oauth_env, patch_oauth_credentials):
    provider = CredentialProvider()

    tokens = await asyncio.gather(*(provider.token() for _ in range(20)))

    assert len(set(tokens)) == 1
    assert patch_oauth_credentials[0].refresh_calls == 1


async def test_a_fresh_token_is_not_refreshed(monkeypatch, oauth_env, patch_oauth_credentials):
    monkeypatch.setenv("GSC_ACCESS_TOKEN", "still-good")
    monkeypatch.setenv(
        "GSC_TOKEN_EXPIRY",
        config.serialize_expiry(config.now_utc() + timedelta(hours=2)),
    )

    provider = CredentialProvider()
    token = await provider.token()

    assert token == "still-good"
    assert patch_oauth_credentials[0].refresh_calls == 0


async def test_a_token_expiring_within_a_minute_is_refreshed(monkeypatch, oauth_env, patch_oauth_credentials):
    monkeypatch.setenv("GSC_ACCESS_TOKEN", "about-to-die")
    monkeypatch.setenv(
        "GSC_TOKEN_EXPIRY",
        config.serialize_expiry(config.now_utc() + timedelta(seconds=30)),
    )

    provider = CredentialProvider()
    assert await provider.token() == "refreshed-1"


async def test_a_revoked_refresh_token_produces_an_actionable_error(oauth_env, monkeypatch):
    from google.auth.exceptions import RefreshError

    class Revoked(FakeCredentials):
        def refresh(self, _request):
            raise RefreshError(
                "invalid_grant",
                {"error": "invalid_grant", "error_description": "Token has been expired or revoked."},
            )

    import google.oauth2.credentials as google_credentials

    monkeypatch.setattr(google_credentials, "Credentials", lambda **kw: Revoked(**kw))

    with pytest.raises(GSCError) as excinfo:
        await CredentialProvider().token()

    assert excinfo.value.status == 401
    assert "mcp-google-search-console auth" in excinfo.value.hint


# -- persistence ------------------------------------------------------------


async def test_environment_credentials_are_never_written_to_disk(
    oauth_env, tmp_config_dir, patch_oauth_credentials
):
    await CredentialProvider().token()
    assert not (tmp_config_dir / "token.json").exists()


async def test_a_refreshed_file_token_is_written_back_with_tight_permissions(
    tmp_config_dir, patch_oauth_credentials
):
    (tmp_config_dir / "oauth_credentials.json").write_text(
        json.dumps({"client_id": "file-id", "client_secret": "file-secret"})
    )
    token_path = tmp_config_dir / "token.json"
    token_path.write_text(json.dumps({"refresh_token": "file-refresh"}))

    provider = CredentialProvider()
    await provider.token()

    saved = json.loads(token_path.read_text())
    assert saved["access_token"] == "refreshed-1"
    assert saved["expiry"].endswith("+00:00")
    assert saved["refresh_token"] == "file-refresh"
    assert "__source__" not in saved
    assert not list(tmp_config_dir.glob("*.tmp"))

    if sys.platform != "win32":
        assert stat.S_IMODE(os.stat(token_path).st_mode) == 0o600


async def test_a_token_file_written_by_2_0_x_still_works(tmp_config_dir, patch_oauth_credentials):
    (tmp_config_dir / "oauth_credentials.json").write_text(
        json.dumps({"client_id": "file-id", "client_secret": "file-secret"})
    )
    # 2.0.x wrote the raw Google token response with a naive expiry.
    (tmp_config_dir / "token.json").write_text(
        json.dumps(
            {
                "access_token": "old-access",
                "refresh_token": "old-refresh",
                "scope": "https://www.googleapis.com/auth/webmasters.readonly",
                "token_type": "Bearer",
                "expiry": "2026-04-01T12:00:00",
            }
        )
    )

    provider = CredentialProvider()
    assert await provider.token() == "refreshed-1"
    assert provider.describe()["token_expiry"].endswith("+00:00")


# -- diagnostics ------------------------------------------------------------


def test_describe_never_returns_a_usable_secret(oauth_env, patch_oauth_credentials):
    info = CredentialProvider().describe()
    assert "client-secret-value" not in json.dumps(info)
    assert "refresh-token-value" not in json.dumps(info)
    assert info["client_id"].endswith("****")


def test_mask_keeps_a_recognisable_prefix():
    assert mask("276929388059-abcdef.apps.googleusercontent.com", keep=12) == "276929388059...****"
    assert mask("short") == "*****"
    assert mask("") == ""
