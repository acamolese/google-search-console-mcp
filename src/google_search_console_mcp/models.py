"""Pydantic models for the tools that return structured output.

The MCP SDK derives a tool's output schema from its return annotation, so a
client gets typed fields instead of a JSON string it has to re-parse.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class Totals(BaseModel):
    """Aggregate metrics for one period."""

    clicks: int = 0
    impressions: int = 0
    ctr: float = Field(default=0.0, description="Click-through rate as a fraction, 4 decimals")
    position: float = Field(default=0.0, description="Average position, 1 decimal")


class Delta(BaseModel):
    """Percentage change between two periods. Position improves when it goes down."""

    clicks_pct: float | None = None
    impressions_pct: float | None = None
    ctr_pct: float | None = None
    position_delta: float | None = Field(
        default=None,
        description="Absolute change in average position; negative means an improvement",
    )


class Overview(BaseModel):
    """Site totals for a period, optionally compared with the preceding one."""

    site_url: str
    date_from: str
    date_to: str
    data_state: str = "all"
    current: Totals
    previous: Totals | None = None
    previous_range: list[str] | None = None
    delta: Delta | None = None


class InspectionResult(BaseModel):
    """The URL Inspection payload for one page, with the sub-objects left as-is."""

    site_url: str
    page_url: str
    verdict: str = ""
    coverage_state: str = ""
    index_status: dict[str, Any] = Field(default_factory=dict)
    mobile_usability: dict[str, Any] = Field(default_factory=dict)
    rich_results: dict[str, Any] = Field(default_factory=dict)
    amp: dict[str, Any] = Field(default_factory=dict)
    inspection_result_link: str = ""


class Doctor(BaseModel):
    """Everything `gsc_doctor` reports. Secrets are masked before they get here."""

    package_version: str
    mcp_version: str
    mcp_major: int
    python_version: str
    platform: str
    transport: str
    auth: dict[str, Any]
    properties: dict[str, Any]
    cache: dict[str, Any]
    defaults: dict[str, Any]
    paths: dict[str, Any]


def pct_change(current: float, previous: float) -> float | None:
    """Percent change, or None when there is no baseline to compare against."""
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 1)


def build_delta(current: Totals, previous: Totals) -> Delta:
    return Delta(
        clicks_pct=pct_change(current.clicks, previous.clicks),
        impressions_pct=pct_change(current.impressions, previous.impressions),
        ctr_pct=pct_change(current.ctr, previous.ctr),
        position_delta=round(current.position - previous.position, 1),
    )
