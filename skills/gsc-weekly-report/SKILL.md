---
name: gsc-weekly-report
description: Weekly Google Search Console review for one property, covering what moved, why, and what to do next. Use when the user asks how a site is doing in Google Search, wants a weekly or monthly SEO update, or asks whether traffic went up or down.
---

# Weekly Search Console review

## 1. Pick the property

If the user did not name one, call `gsc_sites` and ask which property they mean.
Property strings are exact: `sc-domain:example.com` for a domain property,
`https://example.com/` with the trailing slash for a URL-prefix one.

If several properties are in play, `gsc_portfolio` ranks them worst first in one
call; start with whatever it flags `critical`.

## 2. Gather

Run these, in order:

1. `gsc_performance_overview` — `period="last_7_days"`, `compare_previous=true`
2. `gsc_alerts` — `window_days=7`
3. `gsc_traffic_drops` — `period="last_7_days"`
4. `gsc_quick_wins` — `period="last_28_days"`

Use 28 days for the quick wins even in a weekly review: a single week rarely
holds enough impressions to size an opportunity.

## 3. Write it

- **Headline**: clicks, impressions, CTR and average position, each with its
  change. Copy the numbers from the tool output; do not recompute them. A
  negative `position_delta` is an improvement.
- **What moved**: worst first. Use the `diagnosis` column to say whether it was a
  ranking loss, falling demand, a collapsed CTR or a page dropping out. These
  need different fixes. If the diagnosis is `mixed`, say the data does not
  separate the causes rather than picking one.
- **What to do**: the two or three opportunities worth this week's effort, each
  with the uplift the tool estimated.

Never attribute a drop to a core update, a competitor or a site change unless
the user brought that context. Search Console shows what happened, not why.

If nothing crossed the thresholds, say the week was quiet and stop. The meta
line of each response names the thresholds that were applied; quote them if the
user asks why something is missing.

## Caveats worth stating

- `data_state=all` includes today's partial data, matching the Search Console UI.
  The last day of any range is usually incomplete.
- Search Console keeps 16 months. Anything older is not available at any price.
