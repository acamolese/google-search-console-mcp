"""A failed optional call must be reported, not dressed up as a clean empty section."""

from __future__ import annotations

from google_search_console_mcp.audit import run_audit
from google_search_console_mcp.config import Settings
from google_search_console_mcp.errors import GSCError


class _Client:
    def __init__(self, *, fail_sitemaps=False, fail_analytics_months=False):
        self.fail_sitemaps = fail_sitemaps
        self.fail_analytics_months = fail_analytics_months

    async def search_analytics(self, site_url, body):
        # The decay history is the only call asking for 1,000 rows by page.
        if (
            self.fail_analytics_months
            and body.get("dimensions") == ["page"]
            and body.get("rowLimit") == 1_000
        ):
            raise GSCError(429, "Quota exceeded")
        return {"rows": []}

    async def list_sitemaps(self, site_url):
        if self.fail_sitemaps:
            raise GSCError(403, "User does not have sufficient permission")
        return []

    async def inspect_many(self, site_url, urls):
        return []


async def _audit(client, language="en"):
    return await run_audit(
        client,
        "sc-domain:example.com",
        "2026-09-01",
        "2026-09-28",
        language=language,
        write_file=False,
        settings=Settings(),
    )


async def test_a_failed_sitemaps_call_is_surfaced_in_summary_and_report():
    result = await _audit(_Client(fail_sitemaps=True))

    skipped = result.summary["skipped_sections"]
    assert [item["section"] for item in skipped] == ["sitemaps"]
    assert skipped[0]["status"] == 403
    assert "Sitemaps were not checked" in result.html
    assert "skipped-note" in result.html


async def test_a_failed_monthly_history_is_surfaced_as_content_decay():
    result = await _audit(_Client(fail_analytics_months=True), language="it")

    sections = {item["section"] for item in result.summary["skipped_sections"]}
    assert sections == {"content_decay"}
    assert "content decay" in result.html


async def test_a_clean_run_reports_nothing_skipped():
    result = await _audit(_Client())

    assert result.summary["skipped_sections"] == []
    assert "skipped-note" not in result.html.split("</style>", 1)[1]
