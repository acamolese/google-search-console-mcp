"""Output format: token budget, escaping and rounding."""

from __future__ import annotations

import json

import pytest

from google_search_console_mcp.errors import GSCError
from google_search_console_mcp.formatting import (
    columns_for,
    normalize_row,
    normalize_rows,
    render,
    to_json,
    to_tsv,
)

META = {
    "site": "sc-domain:example.com",
    "range": "2026-07-25..2026-08-21",
    "data_state": "all",
    "rows": 2,
}


def api_row(key: str, clicks=1203, impressions=54021, ctr=0.0222695, position=6.43):
    return {"keys": [key], "clicks": clicks, "impressions": impressions, "ctr": ctr, "position": position}


def test_metrics_are_numbers_and_are_rounded():
    row = normalize_row(api_row("camicie uomo"), ["query"])
    assert row == {
        "query": "camicie uomo",
        "clicks": 1203,
        "impressions": 54021,
        "ctr": 0.0223,
        "position": 6.4,
    }
    assert isinstance(row["clicks"], int)
    assert isinstance(row["ctr"], float)


def test_missing_metrics_default_to_zero():
    assert normalize_row({"keys": ["x"]}, ["query"]) == {
        "query": "x",
        "clicks": 0,
        "impressions": 0,
        "ctr": 0.0,
        "position": 0.0,
    }


def test_multiple_dimensions_map_positionally():
    row = normalize_row({"keys": ["shoes", "https://example.com/a"]}, ["query", "page"])
    assert row["query"] == "shoes"
    assert row["page"] == "https://example.com/a"


def test_a_missing_key_becomes_an_empty_string():
    assert normalize_row({"keys": ["only"]}, ["query", "page"])["page"] == ""


def test_tabs_and_newlines_in_values_cannot_shift_columns():
    rows = normalize_rows([api_row("with\ttab"), api_row("with\nnewline")], ["query"])
    tsv = to_tsv(rows, columns_for(["query"]), META)
    body = tsv.split("\n")[2:]

    assert len(body) == 2
    for line in body:
        assert len(line.split("\t")) == 5
    assert "with tab" in tsv
    assert "with newline" in tsv


def test_the_meta_line_comes_first_and_skips_empty_values():
    tsv = to_tsv([], ["query"], {"site": "s", "cache": "", "rows": 0, "next_start_row": None})
    header = tsv.split("\n")[0]
    assert header.startswith("# meta ")
    assert "site=s" in header
    assert "rows=0" in header
    assert "cache=" not in header
    assert "next_start_row" not in header


def test_booleans_render_as_lowercase_words():
    tsv = to_tsv([], ["query"], {"has_more": True, "is_index": False})
    assert "has_more=true" in tsv.split("\n")[0]
    assert "is_index=false" in tsv.split("\n")[0]


def test_json_output_is_compact_and_carries_the_meta():
    rows = normalize_rows([api_row("q")], ["query"])
    payload = to_json(rows, META)
    assert ": " not in payload  # no pretty-printing
    parsed = json.loads(payload)
    assert parsed["meta"]["site"] == "sc-domain:example.com"
    assert parsed["rows"][0]["clicks"] == 1203


def test_one_hundred_rows_stay_under_the_tsv_budget():
    rows = normalize_rows([api_row(f"query number {i}") for i in range(100)], ["query"])
    tsv = to_tsv(rows, columns_for(["query"]), META)
    as_json = to_json(rows, META)

    assert len(tsv.split("\n")) == 102  # meta + header + 100 rows
    assert len(tsv) < 5000
    assert len(tsv) < len(as_json)


def test_render_rejects_an_unknown_format():
    with pytest.raises(GSCError, match="response_format"):
        render([], ["query"], META, "yaml")


def test_columns_put_the_dimensions_before_the_metrics():
    assert columns_for(["query", "page"]) == [
        "query",
        "page",
        "clicks",
        "impressions",
        "ctr",
        "position",
    ]
