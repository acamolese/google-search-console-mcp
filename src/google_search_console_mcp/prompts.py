"""MCP prompts: the three workflows people actually repeat.

Each one names the tools to call, in order, and what to do with the numbers.
They exist so a recurring task does not depend on the operator remembering which
tool answers which question.
"""

from __future__ import annotations


def register_all(mcp) -> None:
    @mcp.prompt(title="Weekly Search Console review")
    def gsc_weekly_report(site_url: str) -> str:
        """Weekly performance review for one property: what moved and what to do."""
        return f"""Produce a weekly Search Console review for {site_url}.

Run these tools, in this order:
1. `gsc_performance_overview` with period="last_7_days" and compare_previous=true.
2. `gsc_alerts` with window_days=7.
3. `gsc_traffic_drops` with period="last_7_days".
4. `gsc_quick_wins` with period="last_28_days" (a week is too short to size an
   opportunity reliably).

Then write the review:
- Open with the headline: clicks, impressions, CTR and average position, each
  with its change. Take the numbers from the tool output, do not recompute them.
- List what actually moved, worst first, using the `diagnosis` column to say
  whether it was ranking, demand, CTR or a page dropping out. Do not invent a
  cause the data does not support; if the diagnosis is "mixed", say so.
- Close with the two or three opportunities worth acting on this week, each with
  its estimated uplift.
- If nothing moved past the thresholds, say the week was quiet. Do not pad.
"""

    @mcp.prompt(title="Indexing audit")
    def gsc_indexing_audit(site_url: str) -> str:
        """Check what Google has indexed for a property and what is blocking the rest."""
        return f"""Audit the indexing state of {site_url}.

Run these tools:
1. `gsc_query` with dimensions="page", period="last_28_days", row_limit=20 to get
   the pages that matter.
2. `gsc_indexing_issues` with those page URLs.
3. `gsc_sitemaps`.

Then report:
- Which of the top pages are not in a PASS state, with their coverage_state
  verbatim. Group them by cause: canonical chosen by Google, crawled but not
  indexed, discovered but not indexed, blocked, fetch failure.
- What each cause means for this site and the fix it needs, in priority order.
- Any sitemap carrying errors or warnings, and whether its submitted and indexed
  counts diverge.
- Note the URL Inspection quota (2,000 per day per property) if the property is
  large enough for that to matter.
"""

    @mcp.prompt(title="Content opportunities")
    def gsc_content_opportunities(site_url: str) -> str:
        """Build a content plan from the queries the site nearly ranks for."""
        return f"""Build a content plan for {site_url} from Search Console data.

Run these tools with period="last_3_months":
1. `gsc_quick_wins`.
2. `gsc_ctr_gaps` with entity="page".
3. `gsc_cannibalization`.
4. `gsc_content_decay` with months=6.

Then produce the plan:
- Pages to rewrite, because they rank but do not earn the clicks their position
  implies. Give the current and expected CTR for each.
- Pages to strengthen, for the queries sitting just off the first page, with the
  estimated uplift.
- Pages to merge or re-point, where several URLs compete for one query. Name the
  page that should win and why.
- Pages to refresh, where clicks have declined month after month.
- Order the whole plan by estimated click gain, and state the thresholds the
  tools applied so the reader knows what was left out.
"""
