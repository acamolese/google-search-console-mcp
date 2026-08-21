---
name: gsc-indexing-audit
description: Check what Google has actually indexed for a site and what is blocking the rest, using the URL Inspection API and the submitted sitemaps. Use when the user asks why a page is not indexed, mentions coverage or crawl problems, or wants to know if Google can see their pages.
---

# Indexing audit

## 1. Choose the URLs

Do not inspect the whole site. Start with the pages that matter:

`gsc_query` with `dimensions="page"`, `period="last_28_days"`, `row_limit=20`.

If the user names specific URLs, use theirs instead.

## 2. Inspect

`gsc_indexing_issues` with those URLs. Limits worth knowing:

- 100 URLs per call.
- The API allows 600 inspections per minute and **2,000 per day per property**.
  On a large site that daily cap is the real constraint; say so before running a
  big batch.

Then `gsc_sitemaps` for the submitted sitemaps.

## 3. Group by cause, not by URL

The `coverage_state` is what matters, and each value needs a different fix:

- **Duplicate, Google chose different canonical than user** — Google disagrees
  with the declared canonical. Check what it picked (`google_canonical` against
  `user_canonical`) and whether the content is genuinely distinct.
- **Crawled - currently not indexed** — Google saw it and passed. This is a
  content-quality signal, not a technical one. More internal links will not fix
  a thin page.
- **Discovered - currently not indexed** — Google knows the URL but has not
  fetched it. Usually crawl budget: too many low-value URLs competing for
  attention.
- **Blocked by robots.txt / noindex** — deliberate or a mistake. Confirm which
  before recommending anything.
- **Page fetch failure / soft 404** — a server problem. Reproduce it before
  blaming Google.

## 4. Sitemaps

Report any sitemap with errors or warnings, and compare its submitted count
against its indexed count. A wide gap usually means the sitemap lists URLs that
redirect, 404 or carry noindex.

## 5. Deliver

A prioritised list: what is broken, how many pages it affects, what to change,
and how to verify. Note that indexing changes take days to weeks to show, so a
recheck belongs two to three weeks out, not tomorrow.
