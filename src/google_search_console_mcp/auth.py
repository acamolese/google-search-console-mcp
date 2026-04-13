"""OAuth2 authorization flow for Google Search Console.

Runs a local loopback authorization flow (opens the system browser, listens
on 127.0.0.1:8080, exchanges the code for a refresh token) and saves the
result to the XDG token file.

If the user prefers not to run a browser flow (e.g. on a headless machine),
they can export GSC_REFRESH_TOKEN directly and skip this step entirely.
"""

from __future__ import annotations

import http.server
import json
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime, timedelta

from . import config

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
]

PORT = 8080
REDIRECT_URI = f"http://localhost:{PORT}"


def run_oauth_flow() -> None:
    """Walk the user through an interactive OAuth authorization."""
    oauth = config.load_oauth_client()
    client_id = oauth["client_id"]
    client_secret = oauth["client_secret"]

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": REDIRECT_URI,
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )

    authorization_code: str | None = None

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):  # noqa: N802
            nonlocal authorization_code
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            authorization_code = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<h1>Authorization complete</h1><p>You can close this window.</p>"
            )

        def log_message(self, format, *args):  # noqa: A002
            pass

    print("Opening browser for authorization...")
    webbrowser.open(auth_url)

    server = http.server.HTTPServer(("localhost", PORT), Handler)
    server.handle_request()

    if not authorization_code:
        print("Error: no authorization code received.")
        return

    print("Code received, exchanging for refresh token...")
    token_data = urllib.parse.urlencode(
        {
            "code": authorization_code,
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": REDIRECT_URI,
            "grant_type": "authorization_code",
        }
    ).encode()

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=token_data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        token_response = json.loads(resp.read())

    expires_in = int(token_response.get("expires_in", 3599))
    token_response["expiry"] = (
        datetime.utcnow() + timedelta(seconds=expires_in - 60)
    ).isoformat()

    config.save_token(token_response)

    token_path = config.token_file_path()
    print(f"\nToken saved to {token_path}")
    print(f"Refresh token: {token_response.get('refresh_token', 'NOT PRESENT')}")
    print(
        "\nYou can now run `google-search-console-mcp` to start the MCP server, or "
        "export GSC_REFRESH_TOKEN for a stateless setup."
    )


if __name__ == "__main__":
    run_oauth_flow()
