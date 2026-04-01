"""Lightweight update checker — queries GitHub releases on startup."""
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

_RELEASES_URL = "https://api.github.com/repos/thequantumfalcon/Spirescope/releases/latest"

_latest_version: str | None = None
_update_url: str | None = None
_checked = False


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into (1, 2, 3)."""
    tag = tag.lstrip("vV")
    parts = []
    for p in tag.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts) or (0,)


def update_checks_enabled() -> bool:
    """Disable automatic update checks in frozen builds unless opted in."""
    raw = os.environ.get("SPIRESCOPE_CHECK_UPDATES")
    if raw is not None:
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return not getattr(sys, "frozen", False)


def check_for_update(current_version: str) -> None:
    """Check GitHub for a newer release (runs in background thread)."""
    global _checked
    if not update_checks_enabled():
        _checked = True
        return

    def _check():
        global _latest_version, _update_url, _checked
        try:
            req = urllib.request.Request(
                _RELEASES_URL,
                headers={"User-Agent": "Spirescope", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            if tag and _parse_version(tag) > _parse_version(current_version):
                _latest_version = tag.lstrip("vV")
                _raw_url = data.get("html_url", "")
                _update_url = _raw_url if _raw_url.startswith("https://github.com/") else ""
                log.info("Update available: %s (current: %s)", _latest_version, current_version)
        except Exception:
            pass  # Network errors are fine — this is best-effort
        finally:
            _checked = True

    threading.Thread(target=_check, daemon=True).start()


def get_update_info() -> dict | None:
    """Return update info if a newer version is available, else None."""
    if _latest_version:
        return {"version": _latest_version, "url": _update_url}
    return None
