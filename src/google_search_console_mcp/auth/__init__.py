"""Credential resolution and the interactive OAuth flow."""

from __future__ import annotations

from .credentials import READONLY_SCOPE, SCOPES, CredentialProvider

__all__ = ["READONLY_SCOPE", "SCOPES", "CredentialProvider", "run_oauth_flow"]


def run_oauth_flow(*args, **kwargs):
    """Lazy re-export: importing oauth pulls in google-auth-oauthlib."""
    from .oauth import run_oauth_flow as _run

    return _run(*args, **kwargs)
