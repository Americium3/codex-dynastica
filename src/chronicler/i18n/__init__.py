"""Minimal i18n for CLI user-facing strings.

Design constraints
------------------
- No external deps. Two flat JSON dicts (en / zh) loaded at import time.
- Lookup by key; falls back to English if the key is missing in the
  active locale, and falls back to the key itself if it is missing in
  English too. Missing keys are logged in DEBUG (not raised) — a stray
  string should never break the CLI.
- Locale is picked from `CHRONICLER_LOCALE` env var (`en` or `zh`).
  Default is `en`.

`_(key, **params)` substitutes Python's `str.format` placeholders.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Literal

log = logging.getLogger(__name__)

Locale = Literal["en", "zh"]
SUPPORTED_LOCALES: tuple[Locale, ...] = ("en", "zh")
DEFAULT_LOCALE: Locale = "en"

_HERE = Path(__file__).parent
_TABLES: dict[str, dict[str, str]] = {}


def _load() -> None:
    for loc in SUPPORTED_LOCALES:
        path = _HERE / f"{loc}.json"
        if not path.exists():
            log.warning("i18n: missing %s, locale %s will fall back", path, loc)
            _TABLES[loc] = {}
            continue
        with path.open("r", encoding="utf-8") as f:
            _TABLES[loc] = json.load(f)


_load()


def current_locale() -> Locale:
    raw = (os.environ.get("CHRONICLER_LOCALE") or DEFAULT_LOCALE).lower()
    if raw.startswith("zh"):
        return "zh"
    return "en"


def set_locale(locale: Locale) -> None:
    """Override at runtime — primarily for tests and CLI --lang flag."""
    if locale not in SUPPORTED_LOCALES:
        raise ValueError(f"Unsupported locale: {locale}")
    os.environ["CHRONICLER_LOCALE"] = locale


def _(key: str, /, **params: object) -> str:
    """Lookup `key` in the active locale; format with `params`.

    Fallback order: active locale → English → raw key.
    """
    locale = current_locale()
    table = _TABLES.get(locale, {})
    text = table.get(key)
    if text is None:
        text = _TABLES.get(DEFAULT_LOCALE, {}).get(key)
    if text is None:
        log.debug("i18n: missing key %r in all locales", key)
        text = key
    if params:
        try:
            return text.format(**params)
        except (KeyError, IndexError) as e:
            log.debug("i18n: format error for %r: %s", key, e)
            return text
    return text


def available_locales() -> tuple[Locale, ...]:
    return SUPPORTED_LOCALES
