"""White-label configuration for the report.

Everything an agency needs to put its own name on the output lives in one JSON
file: colours, logo, brand terms, the expected-CTR curve and threshold
overrides. The defaults keep the report self-contained, so `allow_external_fonts`
has to be turned on deliberately.
"""

from __future__ import annotations

import base64
import copy
import json
import logging
import mimetypes
from pathlib import Path
from typing import Any

from .. import config

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent.parent
BUILTIN_BRANDING = PACKAGE_DIR / "branding.json"

# A system font stack renders everywhere and costs no external request.
SYSTEM_FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif'
)

DEFAULTS: dict[str, Any] = {
    "brand_name": "SEO audit",
    "logo": "",
    "font_family": SYSTEM_FONT_STACK,
    "font_url": "",
    "allow_external_fonts": False,
    "brand_terms": [],
    "ctr_curve": {},
    "thresholds": {},
    "colors": {
        "primary": "#2b6cb0",
        "primary_dark": "#1a365d",
        "secondary": "#805ad5",
        "accent": "#2f855a",
        "danger": "#c53030",
        "warning": "#b7791f",
        "text": "#1a202c",
        "text_muted": "#4a5568",
        "text_light": "#718096",
        "bg": "#f7fafc",
        "surface": "#ffffff",
        "border": "#e2e8f0",
    },
}


def resolve_path(branding_path: str = "") -> Path:
    """Explicit argument, then the user's config dir, then the built-in file."""
    if branding_path:
        return Path(branding_path).expanduser()
    override = config.config_dir() / "branding.json"
    if override.exists():
        return override
    return BUILTIN_BRANDING


def embed_logo(logo_value: str, allow_external: bool) -> str:
    """Base64-encode a local logo so the report stays one file.

    A remote URL is the only thing that can reach outside the document, and it is
    only kept when external assets are allowed.
    """
    if not logo_value:
        return ""
    if logo_value.startswith("data:"):
        return logo_value
    if logo_value.startswith(("http://", "https://")):
        return logo_value if allow_external else ""

    path = Path(logo_value).expanduser()
    if not path.is_absolute():
        candidates = [config.config_dir() / path, PACKAGE_DIR / path]
        path = next((candidate for candidate in candidates if candidate.exists()), path)
    if not path.exists():
        logger.warning("Logo not found at %s, rendering without it", path)
        return ""
    mime, _ = mimetypes.guess_type(str(path))
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:{mime or 'image/png'};base64,{encoded}"


def load(branding_path: str = "", overrides: dict | None = None) -> dict:
    """Merge the defaults, the branding file and any per-call overrides."""
    branding = copy.deepcopy(DEFAULTS)
    path = resolve_path(branding_path)

    if path.exists():
        try:
            user = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            logger.warning("Ignoring unreadable branding file %s", path)
        else:
            _merge(branding, user)

    if overrides:
        _merge(branding, overrides)

    allow_external = bool(branding.get("allow_external_fonts"))
    if not allow_external:
        # A Google Fonts stylesheet would make the report phone home when opened.
        branding["font_url"] = ""
        if branding.get("font_family") in ("Inter", ""):
            branding["font_family"] = SYSTEM_FONT_STACK
    branding["logo_data"] = embed_logo(str(branding.get("logo", "")), allow_external)
    return branding


def _merge(target: dict, source: dict) -> None:
    colors = source.get("colors")
    if isinstance(colors, dict):
        target["colors"].update(colors)
    for key, value in source.items():
        if key == "colors":
            continue
        if value is not None:
            target[key] = value
