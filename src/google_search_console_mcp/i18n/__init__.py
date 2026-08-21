"""Report translations.

The report used to be Italian-only, with the strings written into `audit.py`.
They now live in one JSON file per language, with the same keys in each; the
insight rules emit keys and parameters, and translation happens at render time.
"""

from __future__ import annotations

import contextlib
import json
import logging
from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

I18N_DIR = Path(__file__).parent
DEFAULT_LANGUAGE = "en"


def available_languages() -> list[str]:
    return sorted(path.stem for path in I18N_DIR.glob("*.json"))


@lru_cache(maxsize=8)
def _load_file(language: str) -> dict:
    path = I18N_DIR / f"{language}.json"
    if not path.exists():
        raise FileNotFoundError(f"No translations for language {language!r}")
    return json.loads(path.read_text(encoding="utf-8"))


class Translator:
    """Key lookup with a fallback to English and locale-aware number formatting."""

    def __init__(self, language: str = DEFAULT_LANGUAGE) -> None:
        self.language = language if language in available_languages() else DEFAULT_LANGUAGE
        self._strings = _load_file(self.language)
        self._fallback = _load_file(DEFAULT_LANGUAGE) if self.language != DEFAULT_LANGUAGE else None

    @property
    def locale(self) -> str:
        return str(self._strings.get("locale", "en-US"))

    def raw(self, key: str) -> Any:
        value = _dig(self._strings, key)
        if value is None and self._fallback is not None:
            value = _dig(self._fallback, key)
            if value is not None:
                logger.warning("Missing %s translation for key %r, using English", self.language, key)
        return value

    def t(self, key: str, /, **params: Any) -> str:
        """Translate `key`, interpolating `params`. Unknown keys return the key."""
        value = self.raw(key)
        if value is None:
            logger.warning("Unknown translation key %r", key)
            return key
        if isinstance(value, list):
            return "\n".join(str(item) for item in value)
        text = str(value)
        if not params:
            return text
        try:
            return text.format(**params)
        except (KeyError, IndexError):
            logger.warning("Missing parameters for translation key %r", key)
            return text

    def plural(self, key: str, count: float, /, **params: Any) -> str:
        """Translate `key`, preferring a `_one` variant when `count` is exactly 1.

        English and Italian share the same one/other split, so a single check
        covers both. A language that needs more forms would need more variants.
        """
        if count == 1 and self.raw(f"{key}_one") is not None:
            return self.t(f"{key}_one", **params)
        return self.t(key, **params)

    def list(self, key: str, /, **params: Any) -> list[str]:
        """Translate a key whose value is a list of strings."""
        value = self.raw(key)
        if not isinstance(value, list):
            return []
        out = []
        for item in value:
            text = str(item)
            if params:
                # A strategy line that does not use the parameters is fine.
                with contextlib.suppress(KeyError, IndexError):
                    text = text.format(**params)
            out.append(text)
        return out

    def stopwords(self) -> set[str]:
        value = self.raw("stopwords")
        return {str(word).lower() for word in value} if isinstance(value, Sequence) else set()

    def question_words(self) -> tuple[str, ...]:
        value = self.raw("question_words")
        return tuple(str(word).lower() for word in value) if isinstance(value, Sequence) else ()

    # -- numbers ------------------------------------------------------------

    def number(self, value: float, decimals: int = 0) -> str:
        return format_number(value, self.language, decimals)

    def pct(self, value: float | None, decimals: int = 1, signed: bool = False) -> str:
        return format_pct(value, self.language, decimals, signed)


def _dig(data: Mapping[str, Any], key: str) -> Any:
    current: Any = data
    for part in key.split("."):
        if not isinstance(current, Mapping) or part not in current:
            return None
        current = current[part]
    return current


# Locales that group with a dot and decimalise with a comma.
COMMA_DECIMAL_LANGUAGES = {"it", "de", "es", "pt", "nl", "da", "tr"}


def format_number(value: float, language: str = DEFAULT_LANGUAGE, decimals: int = 0) -> str:
    """Group thousands and place the decimal separator the way the locale does."""
    text = f"{value:,.{decimals}f}"
    if language in COMMA_DECIMAL_LANGUAGES:
        # Swap , and . in one pass.
        text = text.translate(str.maketrans({",": ".", ".": ","}))
    return text


def format_pct(
    value: float | None,
    language: str = DEFAULT_LANGUAGE,
    decimals: int = 1,
    signed: bool = False,
) -> str:
    if value is None:
        return "n/a"
    text = format_number(abs(value), language, decimals)
    if signed:
        sign = "+" if value >= 0 else "−"
        return f"{sign}{text}%"
    return f"{text}%" if value >= 0 else f"−{text}%"


def load(language: str = DEFAULT_LANGUAGE) -> Translator:
    return Translator(language)
