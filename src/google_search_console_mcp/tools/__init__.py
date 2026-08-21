"""Tool registration. One module per Search Console area."""

from __future__ import annotations

from . import analytics, audit, diagnostics, inspection, sitemaps, sites

MODULES = (sites, analytics, inspection, sitemaps, diagnostics, audit)


def register_all(mcp) -> None:
    for module in MODULES:
        module.register(mcp)
