"""Minimal i18n infrastructure for SpireScope.

Usage in templates: {{ t("nav.cards") }} or {{ t("common.win_rate") }}
Usage in Python:    from sts2.i18n import get_translator; t = get_translator("en")

To add a new language:
1. Copy locales/en.json to locales/<code>.json
2. Translate the values (not the keys)
3. Set STS2_LANG=<code> environment variable

The shared navigation chrome (base.html) and the settings page are wrapped;
most page bodies are not, so contributions there are welcome. Entity text —
card, relic, enemy and event names and descriptions — is translated
separately, from the player's own game install, via `python -m sts2 localize`.
"""
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

_CODE_RE = re.compile(r"[a-z]{2,8}")

_LOCALES_DIR = Path(__file__).parent / "locales"
_cache: dict[str, dict] = {}
_content_cache: dict[str, dict] = {}


def is_valid_code(code: str) -> bool:
    """A locale code is a bare 2-8 letter tag — never a path fragment.

    Without this, 'content/de' resolves to the content-overlay directory
    and persists as a language nobody can select back out of.
    """
    return bool(_CODE_RE.fullmatch(code or ""))


def _load_locale(code: str) -> dict:
    """Load a locale file, falling back to English.

    The code is validated here rather than trusted from the caller. Every
    current caller does check first, but this builds a filesystem path out
    of the value, and a guard that lives only in callers is one new call
    site away from being absent — 'de/../../../etc/passwd' would otherwise
    resolve straight out of the locales directory.
    """
    if not is_valid_code(code):
        code = "en"
    if code in _cache:
        return _cache[code]
    path = _LOCALES_DIR / f"{code}.json"
    if not path.exists():
        path = _LOCALES_DIR / "en.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Not cached: a transient lock (virus scanner, partial write) would
        # otherwise leave this locale untranslated until the process restarts
        logging.getLogger(__name__).warning(
            "Could not load locale %s", path, exc_info=True)
        return {}
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
        node: Any = locale
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


def load_content_overlay(code: str = "") -> dict:
    """Official game-text overlay for a locale (sts2/locales/content/<code>.json).

    Returns {} for English, unknown codes, and unreadable files — callers
    treat an empty overlay as "render the shipped English data".
    """
    if not code:
        code = get_language()
    if not is_valid_code(code):
        return {}
    if code in _content_cache:
        return _content_cache[code]
    path = _LOCALES_DIR / "content" / f"{code}.json"
    if code == "en" or not path.exists():
        _content_cache[code] = {}
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        # Never cache a read failure: a transient lock (AV scan, partial
        # write) would otherwise pin this locale to English until restart.
        logging.getLogger(__name__).warning(
            "Could not load content overlay %s", path, exc_info=True)
        return {}
    if not isinstance(data, dict):
        logging.getLogger(__name__).warning(
            "Content overlay %s is not an object, ignoring", path)
        data = {}
    _content_cache[code] = data
    return data


def _settings_path():
    from sts2.config import state_path
    return state_path("settings.json")


def get_language() -> str:
    """Active UI language: STS2_LANG env wins, else persisted setting, else en."""
    env = os.environ.get("STS2_LANG")
    if env:
        return env
    try:
        settings = json.loads(_settings_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return "en"
    # A settings.json holding valid-but-wrong JSON (e.g. []) used to raise
    # here — during application import, taking the whole app down with it.
    if not isinstance(settings, dict):
        return "en"
    lang = settings.get("language", "en")
    # A truthy non-string value (e.g. ["de"], 5) used to be returned as-is
    # and flow unvalidated into locale loading — an unhashable value like a
    # list then raised in _load_locale's cache lookup, taking application
    # import down with it.
    return lang if isinstance(lang, str) and is_valid_code(lang) else "en"


def set_language(code: str) -> bool:
    """Persist the UI language choice. Only known locales are accepted."""
    if not is_valid_code(code) or not (_LOCALES_DIR / f"{code}.json").exists():
        return False
    path = _settings_path()
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        settings = {}
    if not isinstance(settings, dict):
        # Same valid-but-wrong-JSON hole as get_language: settings[] made this
        # a TypeError 500. The file is corrupt state, not user prose — replace.
        settings = {}
    settings["language"] = code
    from sts2.persist import write_json_atomic
    # Callers turn False into "Unknown language.", which is the wrong story
    # when the locale was fine and the state dir was simply unwritable —
    # exactly the Docker case, where this failed silently for every user.
    return write_json_atomic(path, settings)


def available_languages() -> list[dict]:
    """[{code, name}] for every locale file present."""
    langs = []
    for p in sorted(_LOCALES_DIR.glob("*.json")):
        meta = _load_locale(p.stem).get("_meta", {})
        langs.append({"code": p.stem, "name": meta.get("language", p.stem)})
    return langs
