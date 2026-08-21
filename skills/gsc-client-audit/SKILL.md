---
name: gsc-client-audit
description: Produce a white-label HTML SEO audit report for a client property, branded, in English or Italian. Use when the user asks for a client report, a branded or white-label SEO audit, a deliverable to send to a client, or an audit document rather than an answer in chat.
---

# White-label client audit

This produces a document someone else will read. Get the inputs right before
generating it: regenerating is cheap, sending a client a report with the wrong
brand terms is not.

## 1. Confirm the inputs

Ask for anything not already known:

- **Property** — exact string. `gsc_sites` lists what the account can read.
- **Period** — never assume. The 28-day default is rarely what a client report
  wants; monthly or quarterly usually is. `period="last_month"` gives a clean
  calendar month.
- **Language** — `language="en"` or `language="it"`.
- **Brand terms** — the words that mark a query as branded. Without them the
  first label of the domain is used, which is wrong for abbreviations, holding
  companies and invented names, and it silently mislabels the brand split. Ask
  for the brand, its common misspellings and any sub-brands.

## 2. Branding

Colours, logo and report name come from a `branding.json`. Pass it with
`branding_path`, or place it at
`~/.config/mcp-google-search-console/branding.json` to apply it by default.
It can also carry `thresholds` and a `ctr_curve` for a vertical that behaves
differently from the default curve.

## 3. Generate

`gsc_audit` with `site_url`, the period, `language`, `brand_terms`, and
`output="both"` so you get the file and the document. `output_dir` sets where it
lands.

`inspect_top_pages` defaults to 10 and costs one URL Inspection call each against
a 2,000/day quota; set it to 0 to skip that section entirely.

## 4. Hand it over

The first content block is a compact JSON summary. Use it to tell the user, in
their language, what the report says: headline KPIs with their changes, how many
issues by severity, the top quick wins, and the roadmap. Then give them the file
path.

Read the summary before summarising it. If `brand.source` is `domain_label`, the
brand terms were guessed — say so and offer to regenerate with real ones.
