"""Interactive OAuth authorization.

Replaces the hand-rolled loopback server of 2.x, which bound port 8080 with no
PKCE, no `state` parameter and no timeout. `InstalledAppFlow` handles all three
and picks a free port, so a second server or a busy 8080 no longer breaks setup.

This module is the CLI side of the package: it is the one place allowed to write
to stdout, because it never runs while the stdio transport is serving.
"""

from __future__ import annotations

from typing import Any

from .. import config
from .credentials import SCOPES, _write_secret

# Long enough for a password manager and a 2FA prompt, short enough that a
# forgotten terminal does not hold a listener open forever. Choosing between
# several Google accounts can take longer, hence --timeout.
FLOW_TIMEOUT_SECONDS = 300


def run_oauth_flow(open_browser: bool = True, timeout_seconds: int = FLOW_TIMEOUT_SECONDS) -> dict[str, Any]:
    """Authorize the app and store the resulting token. Returns the saved payload."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    client = config.load_oauth_client()
    flow = InstalledAppFlow.from_client_config(
        {"installed": client},
        scopes=SCOPES,
    )

    if not open_browser:
        print("Open this URL in a browser on this machine to authorize:")

    credentials = flow.run_local_server(
        port=0,
        timeout_seconds=timeout_seconds,
        open_browser=open_browser,
        authorization_prompt_message="Authorize this app at: {url}",
        success_message="Authorization complete. You can close this window.",
    )

    payload = {
        "client_id": credentials.client_id,
        "refresh_token": credentials.refresh_token,
        "access_token": credentials.token,
        "expiry": config.serialize_expiry(getattr(credentials, "expiry", None)),
        "scopes": list(credentials.scopes or SCOPES),
    }

    path = config.token_file_path()
    _write_secret(path, payload)

    print(f"\nToken saved to {path}")
    print("\nFor a stateless setup (Docker, CI, a remote host), export these instead:\n")
    print(f'export GSC_CLIENT_ID="{client["client_id"]}"')
    print(f'export GSC_CLIENT_SECRET="{client["client_secret"]}"')
    print(f'export GSC_REFRESH_TOKEN="{credentials.refresh_token}"')
    print("\nRun `mcp-google-search-console doctor` to verify the setup.")
    return payload
