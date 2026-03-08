"""Aggregate stats sync client — upload/download to a remote service.

Opt-in via STS2_SYNC_URL environment variable. Uses stdlib urllib to avoid
adding runtime dependencies. Downloaded data is validated and merged through
the existing anti-manipulation caps in sts2.aggregate.
"""
from __future__ import annotations

import json
import logging
import urllib.request
import urllib.error

from sts2.config import SYNC_URL, SYNC_API_KEY

log = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds
_MAX_SIZE = 5_000_000  # 5 MB, matches save_aggregate limit


class SyncError(Exception):
    """Raised when a sync operation fails."""


def _headers() -> dict[str, str]:
    h = {"Content-Type": "application/json", "User-Agent": "Spirescope/2.1"}
    if SYNC_API_KEY:
        h["X-Api-Key"] = SYNC_API_KEY
    return h


def upload_stats(data: dict) -> dict:
    """Upload aggregate stats to sync service. Returns server response."""
    if not SYNC_URL:
        raise SyncError("Sync not configured. Set STS2_SYNC_URL environment variable.")

    url = SYNC_URL.rstrip("/") + "/api/v1/aggregate"
    payload = json.dumps(data).encode("utf-8")
    if len(payload) > _MAX_SIZE:
        raise SyncError(f"Payload too large ({len(payload)} bytes, max {_MAX_SIZE}).")

    req = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read(_MAX_SIZE))
    except urllib.error.HTTPError as e:
        raise SyncError(f"Server returned {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SyncError(f"Connection failed: {e.reason}") from e
    except (json.JSONDecodeError, OSError) as e:
        raise SyncError(f"Invalid response: {e}") from e


def download_stats() -> dict:
    """Download community aggregate from sync service."""
    if not SYNC_URL:
        raise SyncError("Sync not configured. Set STS2_SYNC_URL environment variable.")

    url = SYNC_URL.rstrip("/") + "/api/v1/aggregate"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            raw = resp.read(_MAX_SIZE + 1)
            if len(raw) > _MAX_SIZE:
                raise SyncError("Downloaded data too large.")
            data = json.loads(raw)
            if not isinstance(data, dict) or "run_count" not in data:
                raise SyncError("Invalid aggregate format from server.")
            return data
    except urllib.error.HTTPError as e:
        raise SyncError(f"Server returned {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise SyncError(f"Connection failed: {e.reason}") from e
    except (json.JSONDecodeError, OSError) as e:
        raise SyncError(f"Invalid response: {e}") from e
