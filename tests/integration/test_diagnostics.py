"""`gsc_doctor` has to answer even when nothing is configured."""

from __future__ import annotations

import json

import httpx
import respx

from google_search_console_mcp.client import WEBMASTERS_BASE
from tests.conftest import call_tool, load_fixture

SITES_URL = f"{WEBMASTERS_BASE}/sites"


@respx.mock
async def test_the_doctor_reports_versions_defaults_and_property_count(server, wired_client):
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    _text, structured = await call_tool(server, "gsc_doctor", {})

    assert structured["package_version"]
    assert structured["mcp_major"] in (1, 2)
    assert structured["properties"] == {"status": "ok", "accessible": 3}
    assert structured["defaults"]["data_state"] == "all"
    assert structured["defaults"]["default_days"] == 28
    assert structured["cache"]["requests"] == 1


@respx.mock
async def test_the_doctor_reports_an_api_failure_instead_of_raising(server, wired_client):
    respx.get(SITES_URL).mock(
        return_value=httpx.Response(403, json=load_fixture("errors", "403_permission.json"))
    )

    _text, structured = await call_tool(server, "gsc_doctor", {})

    assert structured["properties"]["status"] == "error"
    assert "403" in structured["properties"]["detail"]


async def test_the_doctor_still_answers_without_credentials(server, monkeypatch):
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError

    def boom(scopes):
        raise DefaultCredentialsError("nothing configured")

    monkeypatch.setattr(google.auth, "default", boom)

    _text, structured = await call_tool(server, "gsc_doctor", {})

    assert structured["auth"]["status"] == "error"
    assert structured["properties"]["status"] == "skipped"
    assert structured["package_version"]


@respx.mock
async def test_the_doctor_never_prints_a_secret(server, monkeypatch, wired_client):
    monkeypatch.setenv("GSC_CLIENT_ID", "276929388059-secretpart.apps.googleusercontent.com")
    monkeypatch.setenv("GSC_CLIENT_SECRET", "super-secret-value")
    monkeypatch.setenv("GSC_REFRESH_TOKEN", "1//refresh-secret-value")
    respx.get(SITES_URL).mock(return_value=httpx.Response(200, json=load_fixture("sites.json")))

    _text, structured = await call_tool(server, "gsc_doctor", {})

    dumped = json.dumps(structured)
    assert "super-secret-value" not in dumped
    assert "refresh-secret-value" not in dumped
    assert "secretpart" not in dumped
