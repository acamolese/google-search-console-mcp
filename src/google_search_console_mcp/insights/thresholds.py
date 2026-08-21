"""Thresholds that adapt to the site being analysed.

2.x hardcoded 2,000 and 5,000 impressions. On a site doing 300 clicks a month
every rule fell below its floor and the report came out empty; on a large
retailer the same numbers flagged half the catalogue. The thresholds are now
percentiles of the actual data, with a floor so a tiny sample cannot produce a
threshold of zero.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

# Rough click-through rate by position, used to size the gap between what a page
# earns and what its position would normally earn. Override per client via
# branding.json when a vertical is known to behave differently.
DEFAULT_CTR_CURVE = {
    1: 0.275,
    2: 0.155,
    3: 0.100,
    4: 0.075,
    5: 0.060,
    6: 0.048,
    7: 0.038,
    8: 0.031,
    9: 0.026,
    10: 0.022,
}
CTR_BEYOND_FIRST_PAGE = 0.015

MIN_IMPRESSIONS_FLOOR = 50
MIN_CLICKS_FLOOR = 10
HIGH_VISIBILITY_FLOOR = 500


def percentile(values: Sequence[float], p: float) -> float:
    """Linear-interpolation percentile. Returns 0.0 for an empty sequence."""
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    rank = (len(ordered) - 1) * (p / 100)
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return float(ordered[low] * (1 - weight) + ordered[high] * weight)


@dataclass(frozen=True)
class Thresholds:
    """The cut-offs every insight rule applies, plus the expected-CTR curve."""

    min_impressions: int = MIN_IMPRESSIONS_FLOOR
    min_clicks: int = MIN_CLICKS_FLOOR
    high_visibility_impressions: int = HIGH_VISIBILITY_FLOOR
    ctr_curve: Mapping[int, float] = field(default_factory=lambda: dict(DEFAULT_CTR_CURVE))

    @classmethod
    def from_rows(
        cls,
        rows: Sequence[Mapping[str, float]],
        overrides: Mapping[str, object] | None = None,
    ) -> Thresholds:
        impressions = [row.get("impressions", 0) for row in rows]
        clicks = [row.get("clicks", 0) for row in rows]

        thresholds = cls(
            min_impressions=max(MIN_IMPRESSIONS_FLOOR, int(percentile(impressions, 70))),
            min_clicks=max(MIN_CLICKS_FLOOR, int(percentile(clicks, 60))),
            high_visibility_impressions=max(HIGH_VISIBILITY_FLOOR, int(percentile(impressions, 90))),
        )
        return thresholds.with_overrides(overrides)

    def with_overrides(self, overrides: Mapping[str, object] | None) -> Thresholds:
        """Caller-supplied values always win over the computed ones."""
        if not overrides:
            return self
        changes: dict[str, object] = {}
        for name in ("min_impressions", "min_clicks", "high_visibility_impressions"):
            if overrides.get(name) is not None:
                changes[name] = int(overrides[name])  # type: ignore[arg-type]
        curve = overrides.get("ctr_curve")
        if isinstance(curve, Mapping) and curve:
            changes["ctr_curve"] = {int(k): float(v) for k, v in curve.items()}
        return replace(self, **changes) if changes else self

    def expected_ctr(self, position: float) -> float:
        """The CTR a result at this position would normally earn.

        Anything past the first page collapses to a single low value: the curve
        stops being meaningful once the result is not on screen.
        """
        if position <= 0:
            return CTR_BEYOND_FIRST_PAGE
        rounded = max(1, int(round(position)))
        return float(self.ctr_curve.get(rounded, CTR_BEYOND_FIRST_PAGE))

    def as_meta(self) -> dict[str, int]:
        return {
            "min_impressions": self.min_impressions,
            "min_clicks": self.min_clicks,
            "high_visibility_impressions": self.high_visibility_impressions,
        }
