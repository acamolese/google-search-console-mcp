---
name: gsc-cannibalization-check
description: Find queries where several pages of the same site compete against each other in Google, and decide which page should win. Use when the user mentions cannibalisation, duplicate or overlapping pages, pages competing for the same keyword, or asks why a page will not rank.
---

# Cannibalisation check

## 1. Run the analysis

`gsc_cannibalization` with `period="last_3_months"`. Three months beats 28 days
here: cannibalisation is a structural problem and a short window hides the
queries where the two pages simply alternated.

Useful arguments:

- `min_pages` (default 2) — raise it to 3 to see only the worst cases.
- `min_share` (default 0.10) — the share of a query's impressions a page must
  hold to count as competing. Lower it on large sites where the split is wide.
- `row_limit` — default 50.

Check the meta line: if `truncated=true` the property exceeded the 25,000 pairs
the API returns in one page, so the tail was not analysed. Say so rather than
implying the list is complete.

## 2. Read the result

Each row is one query with the competing pages, their clicks and their
positions. The pattern matters more than the count:

- **One page far ahead, others trailing** — usually harmless. Google picked a
  winner. Leave it alone unless the trailing pages are near-duplicates.
- **Two pages close together, both mid-page** — the real problem. The signals are
  split and neither ranks as well as one consolidated page would.
- **Different intents on the same words** — not cannibalisation. A category page
  and a guide can legitimately both appear.

## 3. Recommend

For each genuine case, name the page that should win and why (more clicks, better
position, better intent match), then say what to do with the others: canonical to
the winner, merge the content, redirect, or differentiate the targeting.

Do not recommend deleting a page that still earns clicks without saying where
that traffic will go.

## 4. Verify later

After the fix, `gsc_inspect_url` on the losing pages confirms whether Google
honours the declared canonical. That check is worth scheduling two to three
weeks out, not the next day.
