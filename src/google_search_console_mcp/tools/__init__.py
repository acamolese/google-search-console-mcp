"""Tool registration. One module per Search Console area."""

from __future__ import annotations

from . import analytics, audit, diagnostics, insights, inspection, sitemaps, sites

MODULES = (sites, analytics, insights, inspection, sitemaps, diagnostics, audit)


def register_all(mcp) -> None:
    for module in MODULES:
        module.register(mcp)
