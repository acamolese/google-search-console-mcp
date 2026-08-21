"""Opt-in checks against the real Google API.

Never run in CI. Enable with:

    GSC_LIVE_TESTS=1 GSC_LIVE_SITE=sc-domain:example.com pytest -m live

Credentials come from the environment exactly as the server reads them.
"""

from __future__ import annotations

import os

import pytest

pytestmark = pytest.mark.live

LIVE_ENABLED = os.environ.get("GSC_LIVE_TESTS") == "1"


@pytest.fixture(autouse=True)
def require_opt_in():
    if not LIVE_ENABLED:
        pytest.skip("set GSC_LIVE_TESTS=1 to run the live tests")


@pytest.fixture
async def live_client():
    from google_search_console_mcp.client import close_client, get_client

    client = get_client()
    yield client
    await close_client()


@pytest.fixture
def live_site(live_client):
    site = os.environ.get("GSC_LIVE_SITE")
    if site:
        return site
    pytest.skip("set GSC_LIVE_SITE to the property to test against")
    return None


async def test_the_account_can_read_at_least_one_property(live_client):
    sites = await live_client.list_sites()
    assert sites
    assert all("siteUrl" in entry for entry in sites)


async def test_a_seven_day_query_returns_rows(live_client, live_site):
    from google_search_console_mcp import dates
    from google_search_console_mcp.tools.analytics import _search

    start, end, _label = dates.resolve_range(days=7)
    rows = await _search(live_site, start, end, ["query"], row_limit=10)
    assert isinstance(rows, list)


async def test_the_doctor_reports_working_credentials():
    from google_search_console_mcp.tools.diagnostics import collect_async

    doctor = await collect_async("stdio")
    assert doctor.auth["status"] == "ok"
    assert doctor.properties["status"] == "ok"
    assert doctor.properties["accessible"] >= 1
