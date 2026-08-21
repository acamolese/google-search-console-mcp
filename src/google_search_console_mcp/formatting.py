"""Row normalization and the two response formats.

Default output is TSV, not pretty-printed JSON. On a 100-row query the old
`json.dumps(indent=2)` payload cost roughly 3,400 tokens; the same rows in TSV
cost around 1,100, and the numbers stay numbers instead of becoming strings.

Every response opens with a `# meta ...` line so the model can quote the exact
range, row count and cache state it is looking at.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

METRIC_COLUMNS = ("clicks", "impressions", "ctr", "position")


def normalize_row(row: Mapping[str, Any], dimensions: Sequence[str]) -> dict[str, Any]:
    """Turn one Search Console API row into a flat dict keyed by dimension name."""
    out: dict[str, Any] = {}
    keys = row.get("keys") or []
    for index, dimension in enumerate(dimensions):
        out[dimension] = keys[index] if index < len(keys) else ""
    out["clicks"] = int(row.get("clicks", 0) or 0)
    out["impressions"] = int(row.get("impressions", 0) or 0)
    out["ctr"] = round(float(row.get("ctr", 0) or 0), 4)
    out["position"] = round(float(row.get("position", 0) or 0), 1)
    return out


def normalize_rows(rows: Iterable[Mapping[str, Any]], dimensions: Sequence[str]) -> list[dict]:
    return [normalize_row(row, dimensions) for row in rows]


def _cell(value: Any) -> str:
    """TSV is column-positional: a tab or newline inside a value would shift columns."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    text = f"{value:.10g}" if isinstance(value, float) else str(value)
    return text.replace("\t", " ").replace("\r", " ").replace("\n", " ")


def format_meta(meta: Mapping[str, Any]) -> str:
    """The `# meta key=value ...` header line."""
    parts = [f"{key}={_cell(value)}" for key, value in meta.items() if value is not None and value != ""]
    return "# meta " + " ".join(parts)


def to_tsv(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    meta: Mapping[str, Any],
) -> str:
    lines = [format_meta(meta), "\t".join(columns)]
    lines.extend("\t".join(_cell(row.get(column)) for column in columns) for row in rows)
    return "\n".join(lines)


def to_json(rows: Sequence[Mapping[str, Any]], meta: Mapping[str, Any]) -> str:
    """Compact JSON: no indent, no ASCII escaping."""
    return json.dumps({"meta": dict(meta), "rows": list(rows)}, ensure_ascii=False, separators=(",", ":"))


def render(
    rows: Sequence[Mapping[str, Any]],
    columns: Sequence[str],
    meta: Mapping[str, Any],
    response_format: str,
) -> str:
    if response_format == "json":
        return to_json(rows, meta)
    if response_format == "tsv":
        return to_tsv(rows, columns, meta)
    from .errors import GSCError

    raise GSCError(
        400,
        f"Unknown response_format {response_format!r}. Use 'tsv' or 'json'.",
        reason="badRequest",
    )


def columns_for(dimensions: Sequence[str], extra: Sequence[str] = ()) -> list[str]:
    return [*dimensions, *METRIC_COLUMNS, *extra]
