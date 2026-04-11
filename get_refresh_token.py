"""OAuth2 refresh token helper for Google Search Console."""

import json
import http.server
import urllib.parse
import webbrowser
import urllib.request

CREDENTIALS_FILE = "credentials/oauth_credentials.json"
TOKEN_FILE = "credentials/token.json"

SCOPES = [
    "https://www.googleapis.com/auth/webmasters.readonly",
]

PORT = 8080


def main():
    with open(CREDENTIALS_FILE) as f:
        creds = json.load(f)["installed"]

    client_id = creds["client_id"]
    client_secret = creds["client_secret"]

    auth_url = (
        "https://accounts.google.com/o/oauth2/auth?"
        + urllib.parse.urlencode(
            {
                "client_id": client_id,
                "redirect_uri": f"http://localhost:{PORT}",
                "response_type": "code",
                "scope": " ".join(SCOPES),
                "access_type": "offline",
                "prompt": "consent",
            }
        )
    )

    authorization_code = None

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            nonlocal authorization_code
            query = urllib.parse.urlparse(self.path).query
            params = urllib.parse.parse_qs(query)
            authorization_code = params.get("code", [None])[0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(b"<h1>Authorization complete. You can close this window.</h1>")

        def log_message(self, format, *args):
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
            "redirect_uri": f"http://localhost:{PORT}",
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

    with open(TOKEN_FILE, "w") as f:
        json.dump(token_response, f, indent=2)

    print(f"\nToken saved to {TOKEN_FILE}")
    print(f"Refresh token: {token_response.get('refresh_token', 'NOT PRESENT')}")


if __name__ == "__main__":
    main()
