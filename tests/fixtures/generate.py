#!/usr/bin/env python3
"""Generate the synthetic dataset the audit and insight tests run on.

Fixed seed, committed output: no client data ever enters the repository, and the
numbers stay stable so a test can assert on the top three results.

    python tests/fixtures/generate.py
"""

from __future__ import annotations

import json
import random
from pathlib import Path

OUT_DIR = Path(__file__).parent / "site_medium"
SEED = 20260821
SITE = "sc-domain:example.com"

TOPICS = [
    "widgets",
    "blue widgets",
    "widget repair",
    "widget parts",
    "cheap widgets",
    "widget guide",
    "how to fix a widget",
    "what is a widget",
    "widget vs gadget",
    "widget sizes",
]
BRAND = ["exampleco", "exampleco shop", "exampleco reviews", "exampleco login"]


def metrics(rng, clicks, impressions, position):
    ctr = round(clicks / impressions, 4) if impressions else 0.0
    return {"clicks": clicks, "impressions": impressions, "ctr": ctr, "position": round(position, 1)}


def build(rng):
    queries = []
    for name in BRAND:
        impressions = rng.randint(1200, 4000)
        clicks = int(impressions * rng.uniform(0.25, 0.4))
        queries.append({"query": name, **metrics(rng, clicks, impressions, rng.uniform(1.0, 2.2))})

    for index, name in enumerate(TOPICS):
        impressions = rng.randint(800, 9000)
        position = rng.uniform(3.5, 18.0)
        # Two deliberately poor performers so the CTR rules have something to find.
        ctr = 0.004 if index in (1, 4) else rng.uniform(0.01, 0.09)
        clicks = max(0, int(impressions * ctr))
        queries.append({"query": name, **metrics(rng, clicks, impressions, position)})
    queries.sort(key=lambda row: row["clicks"], reverse=True)

    pages = []
    for index in range(24):
        impressions = rng.randint(400, 12000)
        position = rng.uniform(2.5, 19.0)
        ctr = 0.003 if index in (2, 7) else rng.uniform(0.008, 0.07)
        clicks = max(0, int(impressions * ctr))
        url = f"https://example.com/widgets/{index}"
        if index == 5:
            url = "https://example.com/widgets/list?p=2"
        if index == 6:
            url = "http://example.com/widgets/legacy"
        if index == 8:
            url = "https://www.example.com/widgets/duplicate"
        pages.append({"page": url, **metrics(rng, clicks, impressions, position)})
    pages.sort(key=lambda row: row["clicks"], reverse=True)

    prev_queries = [
        {
            **row,
            **metrics(
                rng,
                int(row["clicks"] * rng.uniform(0.8, 1.4)),
                row["impressions"],
                row["position"] + rng.uniform(-1.5, 1.5),
            ),
        }
        for row in queries
    ]
    prev_pages = []
    for index, row in enumerate(pages):
        factor = 2.2 if index in (1, 3) else rng.uniform(0.8, 1.3)
        prev_pages.append(
            {
                **row,
                **metrics(
                    rng,
                    int(row["clicks"] * factor),
                    int(row["impressions"] * factor),
                    row["position"] + rng.uniform(-1.0, 1.0),
                ),
            }
        )

    devices = [
        {"device": "MOBILE", **metrics(rng, 2100, 96000, 11.4)},
        {"device": "DESKTOP", **metrics(rng, 1400, 42000, 8.1)},
        {"device": "TABLET", **metrics(rng, 90, 3800, 12.2)},
    ]
    countries = [
        {"country": "usa", **metrics(rng, 2400, 88000, 9.8)},
        {"country": "gbr", **metrics(rng, 700, 24000, 10.4)},
        {"country": "irl", **metrics(rng, 260, 7400, 9.1)},
        {"country": "aus", **metrics(rng, 180, 9000, 14.6)},
    ]
    trend = [
        {
            "date": f"2026-07-{day:02d}" if day <= 31 else "",
            **metrics(rng, rng.randint(80, 190), rng.randint(3000, 6500), rng.uniform(8.5, 12.0)),
        }
        for day in range(25, 32)
    ] + [
        {
            "date": f"2026-08-{day:02d}",
            **metrics(rng, rng.randint(80, 190), rng.randint(3000, 6500), rng.uniform(8.5, 12.0)),
        }
        for day in range(1, 22)
    ]

    query_page = []
    for row in queries[:8]:
        page_count = 3 if row["query"] in ("widgets", "blue widgets") else 1
        for index in range(page_count):
            share = 0.5 if index == 0 else 0.25
            query_page.append(
                {
                    "query": row["query"],
                    "page": f"https://example.com/widgets/{index}",
                    **metrics(
                        rng,
                        int(row["clicks"] * share),
                        int(row["impressions"] * share),
                        row["position"] + index,
                    ),
                }
            )

    # A page in steady decline for the content-decay rule.
    monthly_by_page = {}
    for index, row in enumerate(pages[:6]):
        base = max(30, row["clicks"])
        if index == 0:
            series = [
                base,
                int(base * 0.9),
                int(base * 0.7),
                int(base * 0.55),
                int(base * 0.4),
                int(base * 0.3),
            ]
        else:
            series = [max(5, base + rng.randint(-8, 8)) for _ in range(6)]
        months = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
        monthly_by_page[row["page"]] = list(zip(months, series, strict=True))

    sitemaps = [
        {
            "path": "https://example.com/sitemap.xml",
            "lastSubmitted": "2026-08-01T09:12:33.000Z",
            "lastDownloaded": "2026-08-20T04:11:02.000Z",
            "isPending": False,
            "isSitemapsIndex": True,
            "warnings": "4",
            "errors": "1",
        }
    ]
    indexing = [
        {"url": pages[0]["page"], "verdict": "PASS", "coverage_state": "Submitted and indexed"},
        {
            "url": pages[1]["page"],
            "verdict": "FAIL",
            "coverage_state": "Duplicate, Google chose different canonical than user",
        },
        {"url": pages[2]["page"], "verdict": "PASS", "coverage_state": "Submitted and indexed"},
    ]

    current = metrics(rng, 3590, 141800, 10.3)
    previous = metrics(rng, 4300, 138900, 9.7)

    return {
        "site_url": SITE,
        "date_from": "2026-07-25",
        "date_to": "2026-08-21",
        "prev_from": "2026-06-27",
        "prev_to": "2026-07-24",
        "data_state": "all",
        "current": current,
        "previous": previous,
        "queries": queries,
        "prev_queries": prev_queries,
        "pages": pages,
        "prev_pages": prev_pages,
        "devices": devices,
        "countries": countries,
        "trend": trend,
        "query_page": query_page,
        "monthly_by_page": {
            page: [list(item) for item in series] for page, series in monthly_by_page.items()
        },
        "sitemaps": sitemaps,
        "indexing": indexing,
    }


def main() -> None:
    rng = random.Random(SEED)  # noqa: S311 - deterministic test data, not crypto
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    dataset = build(rng)
    (OUT_DIR / "dataset.json").write_text(
        json.dumps(dataset, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(f"wrote {OUT_DIR / 'dataset.json'}")


if __name__ == "__main__":
    main()
