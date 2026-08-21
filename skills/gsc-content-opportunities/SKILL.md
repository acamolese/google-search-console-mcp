---
name: gsc-content-opportunities
description: Build a content plan from Search Console data - pages to rewrite, pages to strengthen, pages to merge and pages to refresh, ranked by estimated click gain. Use when the user asks what to write next, wants a content or SEO plan, or asks where the easy wins are.
---

# Content opportunities

## 1. Gather

Run all four with `period="last_3_months"`:

1. `gsc_quick_wins` — queries close enough to the top that a push pays off
2. `gsc_ctr_gaps` with `entity="page"` — pages that rank but are not clicked
3. `gsc_cannibalization` — queries split across several pages
4. `gsc_content_decay` with `months=6` — pages sliding down month after month

They answer different questions and the plan needs all four. Decay in particular
is invisible to any period comparison: a page that halves over six months never
shows a sharp drop in any single month.

## 2. Sort the work into four buckets

- **Rewrite** (from `ctr_gaps`): the ranking is already there, the snippet is not
  earning the click. Cheapest work on the list. Quote the current CTR against the
  expected one.
- **Strengthen** (from `quick_wins`): queries just off the first page. Quote the
  estimated uplift, which is the clicks the query would earn at position 3.
- **Merge or re-point** (from `cannibalization`): name the page that should win.
- **Refresh** (from `content_decay`): quote the peak month and the last month so
  the decline is visible.

## 3. Rank and state the limits

Order the whole plan by estimated click gain, not by bucket. Then state the
thresholds the tools applied — every response's meta line carries them — so the
reader knows what was filtered out. On a small property the floors do most of the
filtering.

Two things to be honest about:

- The uplift figures assume the page reaches the target position. They size the
  opportunity; they are not a forecast.
- `themes` output, where you use it, is word frequency across queries. It is a
  starting point for topic ideas, not evidence of demand.

## 4. Optional

If the user wants the plan as a document rather than a message, `gsc_audit`
produces a self-contained HTML report covering the same ground plus the
technical issues.
