#!/usr/bin/env python3
"""Render the audit report from the committed fixture, with no credentials.

Useful for reviewing a template change, producing the README screenshot, or
checking a translation without touching a real property.

    python scripts/render_sample_report.py --lang it --out /tmp/report.html
"""

from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "tests" / "fixtures" / "site_medium" / "dataset.json"

sys.path.insert(0, str(REPO_ROOT / "src"))

from google_search_console_mcp import i18n  # noqa: E402
from google_search_console_mcp.audit import branding as branding_module  # noqa: E402
from google_search_console_mcp.audit import render as render_module  # noqa: E402
from google_search_console_mcp.audit import strategy as strategy_module  # noqa: E402
from google_search_console_mcp.insights.issues import detect_issues  # noqa: E402
from google_search_console_mcp.insights.thresholds import Thresholds  # noqa: E402


def load_dataset(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    # JSON has no tuples; the decay rule expects (month, clicks) pairs.
    data["monthly_by_page"] = {
        page: [tuple(item) for item in series] for page, series in data.get("monthly_by_page", {}).items()
    }
    return data


def build(language: str, branding_path: str = "") -> tuple[str, dict]:
    data = load_dataset(FIXTURE)
    translator = i18n.load(language)
    branding = branding_module.load(branding_path)

    th = Thresholds.from_rows(data["queries"] + data["pages"])
    issues = detect_issues(data, th)
    strategy = strategy_module.build(
        data,
        issues,
        th,
        brand_terms=["exampleco"],
        stopwords=sorted(translator.stopwords()),
        question_words=translator.question_words(),
    )
    html = render_module.render(data, issues, strategy, branding, translator)
    summary = render_module.build_summary(data, issues, strategy, language=translator.language)
    return html, summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lang", default="en", choices=i18n.available_languages())
    parser.add_argument("--out", default="", help="output path (default: ./sample-report-<lang>.html)")
    parser.add_argument("--branding", default="", help="path to a branding.json")
    parser.add_argument("--open", action="store_true", help="open the report in a browser")
    parser.add_argument("--summary", action="store_true", help="also print the JSON summary")
    args = parser.parse_args()

    html, summary = build(args.lang, args.branding)
    target = Path(args.out) if args.out else Path(f"sample-report-{args.lang}.html")
    target.write_text(html, encoding="utf-8")

    print(f"wrote {target} ({len(html) / 1024:.0f} KB)")
    if args.summary:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
    if args.open:
        webbrowser.open(target.resolve().as_uri())
    return 0


if __name__ == "__main__":
    sys.exit(main())
