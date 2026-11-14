"""Date range resolution and validation.

Search Console keeps 16 months of daily data, so every range this server builds
is validated against that window before a request goes out. Ranges are resolved
server-side in UTC: the client only has to say "last 28 days".
"""

from __future__ import annotations

from datetime import date, timedelta

from .errors import GSCError

DEFAULT_DAYS = 28
MAX_HISTORY_MONTHS = 16
# Hourly data is only retained for the last 10 days.
HOURLY_MAX_DAYS = 10

PERIODS = (
    "last_7_days",
    "last_28_days",
    "last_3_months",
    "last_month",
    "this_month",
    "last_16_months",
)


def today_utc() -> date:
    from .config import now_utc

    return now_utc().date()


def _months_ago(anchor: date, months: int) -> date:
    """`anchor` shifted back by whole months, clamped to the last valid day."""
    total = anchor.year * 12 + (anchor.month - 1) - months
    year, month = divmod(total, 12)
    month += 1
    day = min(anchor.day, _days_in_month(year, month))
    return date(year, month, day)


def _days_in_month(year: int, month: int) -> int:
    if month == 12:
        return 31
    return (date(year, month + 1, 1) - timedelta(days=1)).day


def earliest_available(today: date) -> date:
    return _months_ago(today, MAX_HISTORY_MONTHS)


def _parse(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise GSCError(
            400,
            f"`{field}` must be a date in YYYY-MM-DD format, got {value!r}.",
            reason="badRequest",
        ) from exc


def resolve_period(period: str, today: date) -> tuple[date, date, str]:
    if period == "last_7_days":
        return today - timedelta(days=6), today, period
    if period == "last_28_days":
        return today - timedelta(days=27), today, period
    if period == "last_3_months":
        return today - timedelta(days=89), today, period
    if period == "last_16_months":
        return earliest_available(today), today, period
    if period == "this_month":
        return today.replace(day=1), today, period
    if period == "last_month":
        first_of_this = today.replace(day=1)
        last_of_previous = first_of_this - timedelta(days=1)
        return last_of_previous.replace(day=1), last_of_previous, period
    raise GSCError(
        400,
        f"Unknown period {period!r}. Use one of: {', '.join(PERIODS)}.",
        reason="badRequest",
    )


def resolve_range(
    date_from: str = "",
    date_to: str = "",
    days: int | None = None,
    period: str = "",
    today: date | None = None,
) -> tuple[str, str, str]:
    """Resolve a range to `(start, end, label)`.

    Precedence: explicit dates, then `period`, then `days`, then the 28-day default.
    A single explicit date is enough to pin that end of the range.
    """
    anchor = today or today_utc()

    if date_from or date_to:
        start = _parse(date_from, "date_from") if date_from else None
        end = _parse(date_to, "date_to") if date_to else anchor
        if start is None:
            span = days if days and days > 0 else DEFAULT_DAYS
            start = end - timedelta(days=span - 1)
        label = "custom"
    elif period:
        start, end, label = resolve_period(period, anchor)
    else:
        span = days if days and days > 0 else DEFAULT_DAYS
        end = anchor
        start = end - timedelta(days=span - 1)
        label = f"last_{span}_days"

    validate_range(start, end, anchor)
    return start.isoformat(), end.isoformat(), label


def validate_range(start: date, end: date, today: date | None = None) -> None:
    """Reject ranges Search Console cannot answer, with the reason spelled out."""
    anchor = today or today_utc()

    if start > end:
        raise GSCError(
            400,
            f"date_from ({start.isoformat()}) is after date_to ({end.isoformat()}).",
            reason="badRequest",
        )
    if start > anchor:
        raise GSCError(
            400,
            f"date_from ({start.isoformat()}) is in the future; today is {anchor.isoformat()}.",
            reason="badRequest",
        )
    limit = earliest_available(anchor)
    if start < limit:
        raise GSCError(
            400,
            (
                f"date_from ({start.isoformat()}) is older than the {MAX_HISTORY_MONTHS} months "
                f"Search Console retains. The earliest available date is {limit.isoformat()}."
            ),
            reason="badRequest",
        )


def validate_hourly_range(start: str, end: str, today: date | None = None) -> None:
    """The HOUR dimension only covers the last 10 days."""
    anchor = today or today_utc()
    start_date = _parse(start, "date_from")
    if (anchor - start_date).days >= HOURLY_MAX_DAYS:
        earliest = (anchor - timedelta(days=HOURLY_MAX_DAYS - 1)).isoformat()
        raise GSCError(
            400,
            (
                f"Hourly data only covers the last {HOURLY_MAX_DAYS} days. "
                f"date_from ({start}) is too far back; use {earliest} or later."
            ),
            reason="badRequest",
        )


COMPARE_MODES = ("previous", "year")

# Periods that roll back from today. Anchoring them to the last complete day of
# data keeps both sides of a comparison whole; calendar periods keep their meaning.
ROLLING_PERIODS = ("", "last_7_days", "last_28_days", "last_3_months", "last_16_months")


def previous_range(start: str, end: str) -> tuple[str, str]:
    """The equally long range ending the day before `start`."""
    start_date = _parse(start, "date_from")
    end_date = _parse(end, "date_to")
    span = (end_date - start_date).days + 1
    prev_end = start_date - timedelta(days=1)
    prev_start = prev_end - timedelta(days=span - 1)
    return prev_start.isoformat(), prev_end.isoformat()


def span_days(start: str, end: str) -> int:
    return (_parse(end, "date_to") - _parse(start, "date_from")).days + 1


def range_of_span(date_from: str, date_to: str, span: int) -> tuple[str, str]:
    """A range of `span` days from whichever end was given."""
    if date_from:
        start = _parse(date_from, "prev_date_from")
        end = start + timedelta(days=span - 1)
    else:
        end = _parse(date_to, "prev_date_to")
        start = end - timedelta(days=span - 1)
    validate_range(start, end)
    return start.isoformat(), end.isoformat()


def _is_whole_months(start: date, end: date) -> bool:
    last_day = _days_in_month(end.year, end.month)
    return start.day == 1 and end.day == last_day


def year_ago_range(start: str, end: str) -> tuple[str, str]:
    """The same range one year earlier.

    Whole calendar months map to the same months last year, so "October" compares
    with last October. Any other range moves back 364 days, which keeps the
    weekdays aligned: a Monday-to-Sunday week compares with a Monday-to-Sunday week.
    """
    start_date = _parse(start, "date_from")
    end_date = _parse(end, "date_to")
    if _is_whole_months(start_date, end_date):
        prev_start = _months_ago(start_date, 12)
        prev_end_month = _months_ago(end_date.replace(day=1), 12)
        prev_end = prev_end_month.replace(day=_days_in_month(prev_end_month.year, prev_end_month.month))
        return prev_start.isoformat(), prev_end.isoformat()
    shift = timedelta(days=364)
    return (start_date - shift).isoformat(), (end_date - shift).isoformat()


def baseline_range(start: str, end: str, compare: str = "previous") -> tuple[str, str]:
    """The range a period is compared against: the one before it, or a year earlier."""
    mode = (compare or "previous").strip().lower()
    if mode == "previous":
        return previous_range(start, end)
    if mode == "year":
        return year_ago_range(start, end)
    raise GSCError(
        400,
        f"compare must be one of {', '.join(COMPARE_MODES)}, got {compare!r}.",
        reason="badRequest",
    )


def baseline_warning(prev_start: str, today: date | None = None) -> str | None:
    """Say so when the baseline starts before the data Search Console still keeps.

    The API answers such a request with the part it has, so a baseline that is
    half empty would otherwise read as a real collapse in the earlier period.
    """
    limit = earliest_available(today or today_utc())
    if _parse(prev_start, "prev_date_from") < limit:
        return f"baseline starts before {limit.isoformat()}, the oldest day Search Console keeps"
    return None


def last_complete_month_end(anchor: str) -> str:
    """The last day of the last calendar month that is over at `anchor`."""
    day = _parse(anchor, "date_to")
    if day.day == _days_in_month(day.year, day.month):
        return day.isoformat()
    return (day.replace(day=1) - timedelta(days=1)).isoformat()


def month_ranges(end: str, months: int, *, complete_only: bool = False) -> list[tuple[str, str, str]]:
    """The last `months` calendar months up to `end`, as `(label, start, end)`.

    With `complete_only`, a month still in progress at `end` is left out: half a
    month of clicks next to whole months reads as a decline that did not happen.
    """
    anchor = _parse(last_complete_month_end(end) if complete_only else end, "date_to")
    out: list[tuple[str, str, str]] = []
    cursor = anchor.replace(day=1)
    for _ in range(months):
        month_start = cursor
        month_end = min(
            anchor,
            date(cursor.year, cursor.month, _days_in_month(cursor.year, cursor.month)),
        )
        out.append((month_start.strftime("%Y-%m"), month_start.isoformat(), month_end.isoformat()))
        cursor = (cursor - timedelta(days=1)).replace(day=1)
    out.reverse()
    return out
