"""Minimal i18n infrastructure for SpireScope.

Usage in templates: {{ t("nav.cards") }} or {{ t("common.win_rate") }}
Usage in Python:    from sts2.i18n import get_translator; t = get_translator("en")

To add a new language:
1. Copy locales/en.json to locales/<code>.json
2. Translate the values (not the keys)
3. Set STS2_LANG=<code> environment variable

No templates are wrapped yet — this is infrastructure for future contributors.
"""
import json
import os
from pathlib import Path

_LOCALES_DIR = Path(__file__).parent / "locales"
_cache: dict[str, dict] = {}


def _load_locale(code: str) -> dict:
    """Load a locale file, falling back to English."""
    if code in _cache:
        return _cache[code]
    path = _LOCALES_DIR / f"{code}.json"
    if not path.exists():
        path = _LOCALES_DIR / "en.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        data = {}
    _cache[code] = data
    return data


def get_translator(code: str = ""):
    """Return a translation function for the given locale code."""
    if not code:
        code = os.environ.get("STS2_LANG", "en")
    locale = _load_locale(code)
    fallback = _load_locale("en") if code != "en" else locale

    def t(key: str) -> str:
        """Look up a dotted key like 'nav.cards'. Falls back to English, then the key itself."""
        parts = key.split(".")
        # Try requested locale
        node = locale
        for p in parts:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                node = None
                break
        if isinstance(node, str):
            return node
        # Fallback to English
        node = fallback
        for p in parts:
            if isinstance(node, dict) and p in node:
                node = node[p]
            else:
                return key  # Key itself as last resort
        return node if isinstance(node, str) else key

    return t
