"""Google API errors turned into something a model can act on.

The Search Console API answers failures with a JSON body that names the reason
(`forbidden`, `quotaExceeded`, `rateLimitExceeded`, ...). Before 3.0.0 that body
was discarded and the tool surfaced a bare HTTP status, which told the caller
nothing about whether to retry, fix the property format, or wait until tomorrow.
"""

from __future__ import annotations

import json
from typing import Any

READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

PROPERTY_FORMAT_HINT = (
    "Check the property format (`sc-domain:example.com` for a domain property vs "
    "`https://example.com/` for a URL-prefix property) and that the authenticated "
    "account has access. Call gsc_sites to list the exact properties available."
)

RETRYABLE_STATUSES = frozenset({429, 500, 502, 503, 504})
RETRYABLE_REASONS = frozenset({"rateLimitExceeded", "userRateLimitExceeded", "backendError"})
# Daily quota is not a transient condition: retrying only burns the remaining budget.
DAILY_QUOTA_REASONS = frozenset({"quotaExceeded", "dailyLimitExceeded"})


class GSCError(Exception):
    """A failed Search Console API call, with a hint aimed at the caller."""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        reason: str | None = None,
        hint: str = "",
        retryable: bool = False,
    ) -> None:
        self.status = status
        self.message = message
        self.reason = reason
        self.hint = hint
        self.retryable = retryable
        super().__init__(str(self))

    def __str__(self) -> str:
        label = f"Error {self.status}"
        if self.reason:
            label += f" ({self.reason})"
        text = f"{label}: {self.message}"
        if self.hint:
            text += f" Hint: {self.hint}"
        return text

    # -- constructors -------------------------------------------------------

    @classmethod
    def from_response(cls, status: int, body: Any) -> GSCError:
        """Build an error from an HTTP status and whatever Google sent back."""
        message, reason = _extract(body)
        hint, retryable = _classify(status, reason, message)
        return cls(status, message, reason=reason, hint=hint, retryable=retryable)

    @classmethod
    def transport(cls, exc: Exception) -> GSCError:
        """A connection-level failure: no status, always worth retrying."""
        return cls(
            0,
            f"Could not reach the Search Console API ({type(exc).__name__}: {exc}).",
            reason="transport",
            hint="Transient network or timeout problem. The request was retried and kept failing.",
            retryable=True,
        )


def _extract(body: Any) -> tuple[str, str | None]:
    """Pull `error.message` and `error.errors[0].reason` out of a Google error body."""
    data: Any = body
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8", "replace")
    if isinstance(body, str):
        try:
            data = json.loads(body)
        except (TypeError, ValueError):
            return (body.strip() or "The API returned an error with no body."), None

    if not isinstance(data, dict):
        return "The API returned an error with no readable body.", None

    error = data.get("error")
    if isinstance(error, str):
        # Token endpoints answer with {"error": "invalid_grant", "error_description": ...}
        return str(data.get("error_description") or error), error
    if not isinstance(error, dict):
        return "The API returned an error with no readable body.", None

    message = str(error.get("message") or "The API returned an error with no message.")
    reason = None
    details = error.get("errors")
    if isinstance(details, list) and details and isinstance(details[0], dict):
        reason = details[0].get("reason")
    if reason is None:
        status_reason = error.get("status")
        if isinstance(status_reason, str):
            reason = status_reason
    return message, reason


def _classify(status: int, reason: str | None, message: str) -> tuple[str, bool]:
    """Return the hint shown to the caller and whether the call may be retried."""
    lowered = message.lower()

    if reason in DAILY_QUOTA_REASONS:
        return (
            "Daily quota exhausted for this property (URL Inspection allows 2,000 calls "
            "per day). Retrying will not help; try again tomorrow.",
            False,
        )

    if status == 401 or reason == "invalid_grant":
        return (
            "The refresh token was revoked or has expired. Run "
            "`mcp-google-search-console auth` again, or update GSC_REFRESH_TOKEN.",
            False,
        )

    if status == 403:
        if reason in RETRYABLE_REASONS:
            return ("Per-minute rate limit hit. Slow down and retry.", True)
        if reason == "insufficientPermissions" or "insufficient permission" in lowered:
            return (PROPERTY_FORMAT_HINT, False)
        if reason in ("forbidden", "accessNotConfigured") or "forbidden" in lowered:
            return (PROPERTY_FORMAT_HINT, False)
        return (PROPERTY_FORMAT_HINT, False)

    if status == 404:
        return ("Property not found for this account. Call gsc_sites for the exact list.", False)

    if status == 429:
        return ("Rate limit hit. The request was retried with backoff and kept failing.", True)

    if status in RETRYABLE_STATUSES:
        return ("Google-side error. The request was retried with backoff and kept failing.", True)

    if status == 400:
        # Google's 400 messages name the offending field; passing them through is
        # more useful than any hint this server could invent.
        return ("", False)

    return ("", status in RETRYABLE_STATUSES)
