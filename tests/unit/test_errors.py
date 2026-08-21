"""Google's error bodies must turn into an actionable message and a retry decision."""

from __future__ import annotations

import pytest

from google_search_console_mcp.errors import GSCError
from tests.conftest import load_fixture

CASES = [
    # fixture, status, reason, retryable, a phrase the hint must contain
    ("403_permission.json", 403, "forbidden", False, "sc-domain:example.com"),
    ("403_quota_daily.json", 403, "quotaExceeded", False, "Daily quota"),
    ("403_rate_limit.json", 403, "rateLimitExceeded", True, "rate limit"),
    ("401_invalid_grant.json", 401, "invalid_grant", False, "refresh token"),
    ("404_not_found.json", 404, "notFound", False, "gsc_sites"),
    ("400_bad_request.json", 400, "badRequest", False, ""),
    ("429_too_many.json", 429, "userRateLimitExceeded", True, "retried"),
    ("503_backend.json", 503, "backendError", True, "retried"),
]


@pytest.mark.parametrize(("fixture", "status", "reason", "retryable", "hint_fragment"), CASES)
def test_error_bodies_are_classified(fixture, status, reason, retryable, hint_fragment):
    error = GSCError.from_response(status, load_fixture("errors", fixture))

    assert error.status == status
    assert error.reason == reason
    assert error.retryable is retryable
    assert hint_fragment.lower() in error.hint.lower()


def test_the_google_message_is_passed_through_verbatim():
    error = GSCError.from_response(400, load_fixture("errors", "400_bad_request.json"))
    assert "Invalid value at 'dimensions[0]'" in error.message
    assert error.hint == ""


def test_the_rendered_message_names_status_reason_and_hint():
    error = GSCError.from_response(403, load_fixture("errors", "403_permission.json"))
    text = str(error)
    assert text.startswith("Error 403 (forbidden):")
    assert "sufficient permission" in text
    assert "Hint:" in text


def test_a_raw_string_body_is_still_usable():
    error = GSCError.from_response(500, "<html>Internal Server Error</html>")
    assert error.status == 500
    assert "Internal Server Error" in error.message
    assert error.retryable is True


def test_an_empty_body_does_not_crash():
    error = GSCError.from_response(502, "")
    assert error.retryable is True
    assert error.message


def test_transport_failures_are_retryable():
    error = GSCError.transport(TimeoutError("read timed out"))
    assert error.status == 0
    assert error.retryable is True
    assert "TimeoutError" in error.message
