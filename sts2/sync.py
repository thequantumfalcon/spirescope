"""Aggregate stats sync client — upload/download to a remote service.

Opt-in via STS2_SYNC_URL environment variable. Uses stdlib urllib to avoid
adding runtime dependencies. Downloaded data is validated and merged through
the existing anti-manipulation caps in sts2.aggregate.
"""
from __future__ import annotations

import ipaddress
import json
import logging
import socket
import urllib.error
import urllib.parse
import urllib.request

from sts2.config import SYNC_API_KEY, SYNC_URL

log = logging.getLogger(__name__)

_TIMEOUT = 15  # seconds
_MAX_SIZE = 5_000_000  # 5 MB, matches save_aggregate limit


class SyncError(Exception):
    """Raised when a sync operation fails."""


def _validate_url(url: str) -> str:
    """Validate sync URL: require HTTPS and reject private/loopback addresses.

    Caveat: DNS-rebinding TOCTOU is not fully closed — between validation here
    and the actual urlopen() request, an attacker-controlled DNS server could
    return a public IP on first lookup and 127.0.0.1 on the second. A complete
    fix requires a custom connection adapter that pins the validated IP at
    socket level. Out of scope for current sync use (opt-in only).
    """
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https":
        raise ValueError(f"Sync URL must use HTTPS (got {parsed.scheme or 'no scheme'})")

    hostname = parsed.hostname
    if not hostname:
        raise ValueError("Sync URL has no hostname")

    def _disallowed_reason(addr: ipaddress._BaseAddress) -> str | None:
        # Block private, loopback, reserved, multicast, link-local (cloud-
        # metadata 169.254.169.254 is link-local — must be explicit).
        if addr.is_loopback:
            return "loopback"
        if addr.is_link_local:
            return "link-local (cloud metadata)"
        if addr.is_private:
            return "private"
        if addr.is_reserved:
            return "reserved"
        if addr.is_multicast:
            return "multicast"
        if addr.is_unspecified:
            return "unspecified"
        # Carrier-grade NAT (RFC 6598). ipaddress does not treat it as private,
        # so 100.64.0.0/10 was reachable despite being non-routable.
        if addr.version == 4 and addr in ipaddress.ip_network("100.64.0.0/10"):
            return "carrier-grade NAT"
        return None

    # Try parsing hostname as a literal IP first.
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        addr = None
    if addr is not None:
        reason = _disallowed_reason(addr)
        if reason:
            raise ValueError(
                f"Sync URL must not point to {reason} address ({hostname})"
            )
        return url

    # Hostname is a DNS name — resolve and check every returned address.
    try:
        infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for _family, _type, _proto, _canonname, sockaddr in infos:
            try:
                resolved = ipaddress.ip_address(sockaddr[0])
            except (ValueError, IndexError):
                continue
            reason = _disallowed_reason(resolved)
            if reason:
                raise ValueError(
                    f"Sync URL resolves to {reason} address ({sockaddr[0]})"
                )
    except socket.gaierror:
        pass  # DNS resolution failure — let urllib handle it at request time

    return url


class _ValidatingRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Re-check every redirect hop, and never forward the API key off-origin.

    urlopen() follows 3xx by default and only the originally configured URL was
    ever validated, so a single Location header voided every check in
    _validate_url — a sync endpoint could bounce the request into 127.0.0.1,
    the user's LAN, or cloud metadata. CPython's redirect handler also copies
    all headers except content-length/content-type, so X-Api-Key travelled to
    whatever host the redirect named, over cleartext http if it chose.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _validate_url(newurl)
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and _origin(newurl) != _origin(req.full_url):
            new.headers.pop("X-api-key", None)
            new.headers.pop("X-Api-Key", None)
        return new


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urllib.parse.urlparse(url)
    return (parsed.scheme, (parsed.hostname or "").lower(), parsed.port)


def _open(req):
    """Open a request through an opener that validates redirects."""
    opener = urllib.request.build_opener(_ValidatingRedirectHandler)
    return opener.open(req, timeout=_TIMEOUT)


def _headers() -> dict[str, str]:
    from sts2.config import VERSION
    h = {"Content-Type": "application/json", "User-Agent": f"Spirescope/{VERSION}"}
    if SYNC_API_KEY:
        h["X-Api-Key"] = SYNC_API_KEY
    return h


def upload_stats(data: dict) -> dict:
    """Upload aggregate stats to sync service. Returns server response."""
    if not SYNC_URL:
        raise SyncError("Sync not configured. Set STS2_SYNC_URL environment variable.")

    # A malformed STS2_SYNC_URL is a configuration error, not a crash: the
    # CLI catches SyncError only, so a bare ValueError was a raw traceback.
    try:
        _validate_url(SYNC_URL)
    except ValueError as e:
        raise SyncError(f"Invalid sync URL: {e}") from e
    url = SYNC_URL.rstrip("/") + "/api/v1/aggregate"
    payload = json.dumps(data).encode("utf-8")
    if len(payload) > _MAX_SIZE:
        raise SyncError(f"Payload too large ({len(payload)} bytes, max {_MAX_SIZE}).")

    req = urllib.request.Request(url, data=payload, headers=_headers(), method="POST")
    try:
        with _open(req) as resp:
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

    try:
        _validate_url(SYNC_URL)
    except ValueError as e:
        raise SyncError(f"Invalid sync URL: {e}") from e
    url = SYNC_URL.rstrip("/") + "/api/v1/aggregate"
    req = urllib.request.Request(url, headers=_headers(), method="GET")
    try:
        with _open(req) as resp:
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
