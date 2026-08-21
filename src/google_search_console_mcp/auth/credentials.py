"""One `Credentials` object per process, refreshed at most once at a time.

Before 3.0.0 every tool call rebuilt credentials from scratch and, in
environment-variable mode, forced `expiry` to 1970 so the very next call had to
refresh the token first. A `gsc_audit` run turned 19 API calls into 38 round
trips. Here the credentials are built once, the refresh happens only when the
token is actually near expiry, and an `asyncio.Lock` keeps concurrent callers
from refreshing in parallel.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import timedelta
from pathlib import Path
from typing import Any

from .. import config
from ..errors import GSCError

logger = logging.getLogger(__name__)

READONLY_SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"
SCOPES = [READONLY_SCOPE]

# Refresh a little before the token actually dies so an in-flight request cannot
# race the expiry.
REFRESH_MARGIN = timedelta(seconds=60)

MODE_OAUTH = "oauth"
MODE_SERVICE_ACCOUNT = "service_account"
MODE_ADC = "adc"
MODES = (MODE_OAUTH, MODE_SERVICE_ACCOUNT, MODE_ADC)

NO_CREDENTIALS_MESSAGE = (
    "No Google credentials found. Set one of:\n"
    "  1. GSC_CLIENT_ID, GSC_CLIENT_SECRET and GSC_REFRESH_TOKEN (stateless OAuth), or\n"
    "  2. GSC_SERVICE_ACCOUNT_FILE / GSC_SERVICE_ACCOUNT_JSON (service account), or\n"
    "  3. run `mcp-google-search-console auth` once to store a token on disk.\n"
    "Application Default Credentials are used as a last resort."
)


def mask(value: str | None, keep: int = 6) -> str:
    """Show enough of a secret to recognise it, never enough to use it."""
    if not value:
        return ""
    if len(value) <= keep:
        return "*" * len(value)
    return f"{value[:keep]}...{'*' * 4}"


def _write_secret(path: Path, payload: dict) -> None:
    """Write atomically, then tighten the permissions (best effort on Windows)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)
    except OSError:  # pragma: no cover - Windows and exotic filesystems
        logger.debug("Could not chmod %s", tmp)
    os.replace(tmp, path)
    try:
        os.chmod(path, 0o600)
    except OSError:  # pragma: no cover
        logger.debug("Could not chmod %s", path)


class CredentialProvider:
    """Resolves credentials once, then hands out access tokens."""

    def __init__(self, settings: config.Settings | None = None) -> None:
        self._settings = settings or config.Settings.from_env()
        self._lock = asyncio.Lock()
        self._credentials: Any = None
        self._mode: str = ""
        self._source: str = ""
        self._refreshes = 0

    # -- resolution ---------------------------------------------------------

    def _resolve(self) -> None:
        """Build the credentials object, honouring the documented precedence."""
        if self._credentials is not None:
            return

        requested = os.environ.get("GSC_AUTH_MODE", "").strip().lower()
        if requested and requested not in MODES:
            raise GSCError(
                400,
                f"GSC_AUTH_MODE must be one of {', '.join(MODES)}, got {requested!r}.",
                reason="badRequest",
            )

        if requested == MODE_SERVICE_ACCOUNT:
            self._credentials, self._source = self._service_account()
            self._mode = MODE_SERVICE_ACCOUNT
            return
        if requested == MODE_ADC:
            self._credentials, self._source = self._adc()
            self._mode = MODE_ADC
            return
        if requested == MODE_OAUTH:
            self._credentials, self._source = self._oauth()
            self._mode = MODE_OAUTH
            return

        if os.environ.get("GSC_SERVICE_ACCOUNT_FILE") or os.environ.get("GSC_SERVICE_ACCOUNT_JSON"):
            self._credentials, self._source = self._service_account()
            self._mode = MODE_SERVICE_ACCOUNT
            return

        try:
            self._credentials, self._source = self._oauth()
            self._mode = MODE_OAUTH
            return
        except FileNotFoundError:
            pass

        self._credentials, self._source = self._adc()
        self._mode = MODE_ADC

    def _oauth(self) -> tuple[Any, str]:
        from google.oauth2.credentials import Credentials

        client = config.load_oauth_client()
        token = config.load_token()
        credentials = Credentials(
            token=token.get("access_token"),
            refresh_token=token["refresh_token"],
            token_uri=client.get("token_uri", "https://oauth2.googleapis.com/token"),
            client_id=client["client_id"],
            client_secret=client["client_secret"],
            scopes=SCOPES,
        )
        # A missing or unreadable expiry means "refresh before the first call".
        credentials.expiry = config.parse_expiry(token.get("expiry")) or config.EPOCH_NAIVE_UTC
        return credentials, token.get("__source__", "unknown")

    def _service_account(self) -> tuple[Any, str]:
        from google.oauth2 import service_account

        inline = os.environ.get("GSC_SERVICE_ACCOUNT_JSON")
        if inline:
            try:
                info = json.loads(inline)
            except ValueError as exc:
                raise GSCError(
                    400,
                    "GSC_SERVICE_ACCOUNT_JSON is not valid JSON.",
                    reason="badRequest",
                ) from exc
            return (
                service_account.Credentials.from_service_account_info(info, scopes=SCOPES),
                "env:GSC_SERVICE_ACCOUNT_JSON",
            )

        path_value = os.environ.get("GSC_SERVICE_ACCOUNT_FILE", "")
        if not path_value:
            raise GSCError(
                400,
                "Service account mode requires GSC_SERVICE_ACCOUNT_FILE or GSC_SERVICE_ACCOUNT_JSON.",
                reason="badRequest",
            )
        path = Path(path_value).expanduser()
        if not path.exists():
            raise GSCError(
                400,
                f"Service account file not found: {path}",
                reason="badRequest",
            )
        return (
            service_account.Credentials.from_service_account_file(str(path), scopes=SCOPES),
            str(path),
        )

    def _adc(self) -> tuple[Any, str]:
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        try:
            credentials, _project = google.auth.default(scopes=SCOPES)
        except DefaultCredentialsError as exc:
            raise GSCError(401, NO_CREDENTIALS_MESSAGE, reason="noCredentials") from exc
        return credentials, "application-default-credentials"

    # -- token --------------------------------------------------------------

    async def token(self) -> str:
        """A valid access token, refreshing at most once across concurrent callers."""
        async with self._lock:
            self._resolve()
            if self._needs_refresh():
                await self._refresh()
            token = getattr(self._credentials, "token", None)
            if not token:
                raise GSCError(
                    401,
                    "Google returned no access token for these credentials.",
                    reason="noAccessToken",
                    hint="Re-run `mcp-google-search-console auth` or check GSC_REFRESH_TOKEN.",
                )
            return str(token)

    def _needs_refresh(self) -> bool:
        credentials = self._credentials
        if not getattr(credentials, "token", None):
            return True
        expiry = getattr(credentials, "expiry", None)
        if expiry is None:
            return not getattr(credentials, "valid", False)
        return config.now_utc().replace(tzinfo=None) >= (expiry - REFRESH_MARGIN)

    async def _refresh(self) -> None:
        from google.auth.exceptions import RefreshError
        from google.auth.transport.requests import Request

        def _do_refresh() -> None:
            self._credentials.refresh(Request())

        try:
            await asyncio.to_thread(_do_refresh)
        except RefreshError as exc:
            raise GSCError.from_response(401, _refresh_error_body(exc)) from exc

        self._refreshes += 1
        self._persist()

    def _persist(self) -> None:
        """Persist the refreshed access token, but only when it came from a file."""
        if self._mode != MODE_OAUTH:
            return
        source = self._source
        if not source or source in ("env", "unknown"):
            return
        path = Path(source)
        if not path.exists():
            return
        try:
            stored = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Could not update the token file at %s", path)
            return
        stored["access_token"] = self._credentials.token
        stored["expiry"] = config.serialize_expiry(getattr(self._credentials, "expiry", None))
        stored.pop("__source__", None)
        _write_secret(path, stored)

    # -- diagnostics --------------------------------------------------------

    def describe(self) -> dict[str, Any]:
        """Auth summary for `gsc_doctor`. Never returns a usable secret."""
        try:
            self._resolve()
        except (GSCError, FileNotFoundError) as exc:
            return {"status": "error", "detail": str(exc)}

        credentials = self._credentials
        expiry = getattr(credentials, "expiry", None)
        info: dict[str, Any] = {
            "status": "ok",
            "mode": self._mode,
            "source": self._source if self._source != "env" else "environment variables",
            "scopes": list(getattr(credentials, "scopes", None) or SCOPES),
            "token_expiry": config.serialize_expiry(expiry),
            "refreshes_this_process": self._refreshes,
        }
        client_id = getattr(credentials, "client_id", None)
        if client_id:
            info["client_id"] = mask(client_id, keep=12)
        email = getattr(credentials, "service_account_email", None)
        if email:
            info["service_account_email"] = email
        return info


def _refresh_error_body(exc: Exception) -> Any:
    """`RefreshError` carries Google's JSON body as its second argument."""
    args = getattr(exc, "args", ())
    if len(args) > 1 and isinstance(args[1], dict):
        return args[1]
    return {"error": {"message": str(exc), "errors": [{"reason": "invalid_grant"}]}}
