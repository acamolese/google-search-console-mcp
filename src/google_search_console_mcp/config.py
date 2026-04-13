"""Configuration and credential resolution for the GSC MCP server.

Credentials are resolved in this order (highest priority first):

1. Environment variables
   - GSC_CLIENT_ID, GSC_CLIENT_SECRET, GSC_REFRESH_TOKEN (required together)
2. XDG config directory
   - $XDG_CONFIG_HOME/google-search-console-mcp/oauth_credentials.json
   - $XDG_CONFIG_HOME/google-search-console-mcp/token.json
   - Defaults to ~/.config/google-search-console-mcp/ on Linux/macOS
3. Legacy per-project directory (backward compatibility)
   - ./credentials/oauth_credentials.json
   - ./credentials/token.json
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path


APP_NAME = "google-search-console-mcp"


# ---------------------------------------------------------------------------
# Directories
# ---------------------------------------------------------------------------

def xdg_config_home() -> Path:
    env = os.environ.get("XDG_CONFIG_HOME")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".config"


def config_dir() -> Path:
    """Return the XDG config dir for this app, creating it on demand."""
    path = xdg_config_home() / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def legacy_creds_dir() -> Path:
    """Legacy credentials directory (relative to CWD, pre-2.0 layout)."""
    return Path.cwd() / "credentials"


# ---------------------------------------------------------------------------
# OAuth client (client_id + client_secret)
# ---------------------------------------------------------------------------

def _oauth_from_env() -> dict | None:
    cid = os.environ.get("GSC_CLIENT_ID")
    secret = os.environ.get("GSC_CLIENT_SECRET")
    if cid and secret:
        return {
            "client_id": cid,
            "client_secret": secret,
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        }
    return None


def _oauth_from_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    # Google console credential files wrap the useful bits under "installed"
    if "installed" in data:
        return data["installed"]
    return data


def load_oauth_client() -> dict:
    """Return the OAuth client config as a dict with client_id, client_secret, token_uri."""
    env_data = _oauth_from_env()
    if env_data:
        return env_data

    for candidate in (config_dir() / "oauth_credentials.json", legacy_creds_dir() / "oauth_credentials.json"):
        data = _oauth_from_file(candidate)
        if data:
            return data

    raise FileNotFoundError(
        "No OAuth client credentials found. Set GSC_CLIENT_ID and GSC_CLIENT_SECRET "
        f"environment variables, or place oauth_credentials.json in {config_dir()}/ "
        f"or {legacy_creds_dir()}/."
    )


# ---------------------------------------------------------------------------
# Token (access_token + refresh_token + expiry)
# ---------------------------------------------------------------------------

def _token_from_env() -> dict | None:
    refresh = os.environ.get("GSC_REFRESH_TOKEN")
    if refresh:
        return {
            "refresh_token": refresh,
            "access_token": os.environ.get("GSC_ACCESS_TOKEN"),
            "expiry": os.environ.get("GSC_TOKEN_EXPIRY"),
            "__source__": "env",
        }
    return None


def _token_from_file(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    data["__source__"] = str(path)
    return data


def token_file_path() -> Path:
    """Preferred path where a refreshed token should be written."""
    xdg = config_dir() / "token.json"
    if xdg.exists():
        return xdg
    legacy = legacy_creds_dir() / "token.json"
    if legacy.exists():
        return legacy
    # Default to XDG for new installations
    return xdg


def load_token() -> dict:
    """Return the token dict. Includes a `__source__` marker describing where it came from."""
    env_data = _token_from_env()
    if env_data:
        return env_data

    for candidate in (config_dir() / "token.json", legacy_creds_dir() / "token.json"):
        data = _token_from_file(candidate)
        if data:
            return data

    raise FileNotFoundError(
        "No OAuth token found. Set GSC_REFRESH_TOKEN environment variable, or run "
        "`google-search-console-mcp auth` to authorize the app and generate one."
    )


def save_token(token: dict) -> None:
    """Persist the token to the token file (unless it originated from env vars)."""
    if token.get("__source__") == "env":
        return
    path = token_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    to_write = {k: v for k, v in token.items() if not k.startswith("__")}
    path.write_text(json.dumps(to_write, indent=2), encoding="utf-8")


def update_saved_token(access_token: str, expiry: datetime | None) -> None:
    """Update only the access_token and expiry on disk, preserving the rest."""
    token = load_token()
    if token.get("__source__") == "env":
        return
    token["access_token"] = access_token
    if expiry:
        token["expiry"] = expiry.isoformat()
    save_token(token)
