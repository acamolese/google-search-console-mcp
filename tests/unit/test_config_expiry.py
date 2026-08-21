"""Expiry serialization must stay readable by google-auth and by older installs."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from google_search_console_mcp import config


def test_parse_expiry_reads_naive_values_written_by_2_0_x():
    parsed = config.parse_expiry("2026-08-21T10:00:00")
    assert parsed == datetime(2026, 8, 21, 10, 0)
    assert parsed.tzinfo is None


def test_parse_expiry_converts_offset_aware_values_to_naive_utc():
    parsed = config.parse_expiry("2026-08-21T12:00:00+02:00")
    assert parsed == datetime(2026, 8, 21, 10, 0)
    assert parsed.tzinfo is None


def test_parse_expiry_returns_none_for_missing_or_broken_values():
    assert config.parse_expiry(None) is None
    assert config.parse_expiry("") is None
    assert config.parse_expiry("not-a-date") is None


def test_serialize_expiry_always_writes_an_offset():
    naive = config.serialize_expiry(datetime(2026, 8, 21, 10, 0))
    aware = config.serialize_expiry(datetime(2026, 8, 21, 12, 0, tzinfo=timezone(timedelta(hours=2))))
    assert naive == "2026-08-21T10:00:00+00:00"
    assert aware == "2026-08-21T10:00:00+00:00"
    assert config.serialize_expiry(None) is None


def test_roundtrip_is_stable():
    original = datetime(2026, 8, 21, 10, 0)
    assert config.parse_expiry(config.serialize_expiry(original)) == original


def test_now_utc_is_offset_aware():
    assert config.now_utc().tzinfo is not None


def test_update_saved_token_writes_an_offset_aware_expiry(tmp_config_dir):
    (tmp_config_dir / "token.json").write_text(
        json.dumps({"refresh_token": "r", "access_token": "old"}), encoding="utf-8"
    )
    config.update_saved_token("new", datetime(2026, 8, 21, 10, 0))

    saved = json.loads((tmp_config_dir / "token.json").read_text(encoding="utf-8"))
    assert saved["access_token"] == "new"
    assert saved["expiry"] == "2026-08-21T10:00:00+00:00"
    assert "__source__" not in saved


def test_env_tokens_are_never_written_to_disk(monkeypatch, tmp_config_dir):
    monkeypatch.setenv("GSC_REFRESH_TOKEN", "from-env")
    config.update_saved_token("new", datetime(2026, 8, 21, 10, 0))
    assert not (tmp_config_dir / "token.json").exists()
