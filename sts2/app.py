"""FastAPI web dashboard for Spirescope — core setup, middleware, background tasks."""
import asyncio
import collections
import contextlib
import hashlib
import hmac
import ipaddress
import logging
import os
import re
import secrets
import struct
import sys
import time

from fastapi import FastAPI, Request
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError, StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sts2.analytics import compute_analytics
from sts2.config import (
    SAVE_DIRS,
    STATIC_DIR,
    TEMPLATES_DIR,
    VERSION,
    ensure_data_dir,
    migrate_state_from_data_dir,
)
from sts2.knowledge import KnowledgeBase
from sts2.saves import get_progress, get_run_history

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# App creation
# ---------------------------------------------------------------------------

_css_path = STATIC_DIR / "style.css"
_CSS_HASH = hashlib.md5(_css_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _css_path.exists() else "0"
_theme_init_path = STATIC_DIR / "theme-init.js"
_THEME_INIT_HASH = hashlib.md5(_theme_init_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _theme_init_path.exists() else "0"
_logo_path = STATIC_DIR / "logo.jpg"
_LOGO_HASH = hashlib.md5(_logo_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _logo_path.exists() else "0"
_hero_bg_path = STATIC_DIR / "hero-bg.jpg"
_HERO_BG_HASH = hashlib.md5(_hero_bg_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _hero_bg_path.exists() else "0"
_deck_js_path = STATIC_DIR / "deck.js"
_DECK_JS_HASH = hashlib.md5(_deck_js_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _deck_js_path.exists() else "0"
_collections_js_path = STATIC_DIR / "collections.js"
_COLLECTIONS_JS_HASH = hashlib.md5(_collections_js_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _collections_js_path.exists() else "0"
_shortcuts_js_path = STATIC_DIR / "shortcuts.js"
_SHORTCUTS_JS_HASH = hashlib.md5(_shortcuts_js_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _shortcuts_js_path.exists() else "0"
_compare_js_path = STATIC_DIR / "compare.js"
_COMPARE_JS_HASH = hashlib.md5(_compare_js_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _compare_js_path.exists() else "0"
_live_js_path = STATIC_DIR / "live.js"
_LIVE_JS_HASH = hashlib.md5(_live_js_path.read_bytes(), usedforsecurity=False).hexdigest()[:8] if _live_js_path.exists() else "0"


@contextlib.asynccontextmanager
async def _lifespan(application):
    from sts2.updater import check_for_data_update, check_for_update
    check_for_update(templates.env.globals.get("version", "0.0.0"))
    check_for_data_update()
    await _prewarm_caches()
    watcher_task = asyncio.create_task(_watch_saves())
    try:
        yield
    finally:
        # Nothing used to run after yield: the watcher task was never
        # cancelled and the watchdog observer threads were never stopped or
        # joined, so shutdown relied on daemon threads dying with the process.
        watcher_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await watcher_task
        for observer in _observers:
            with contextlib.suppress(Exception):
                observer.stop()
        for observer in _observers:
            with contextlib.suppress(Exception):
                await asyncio.to_thread(observer.join, 2.0)
        _observers.clear()


app = FastAPI(title="Spirescope", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["css_hash"] = _CSS_HASH
templates.env.globals["theme_init_hash"] = _THEME_INIT_HASH
templates.env.globals["logo_hash"] = _LOGO_HASH
templates.env.globals["hero_bg_hash"] = _HERO_BG_HASH
templates.env.globals["version"] = VERSION
# How to invoke the CLI, phrased for whoever is actually reading the page.
# Packaged builds have neither Python nor a `spirescope` entry point on PATH,
# so telling that reader to run `python -m sts2 update` is an instruction they
# cannot follow — they have the executable they double-clicked and nothing else.
# Taken from the running executable rather than hardcoded, because the macOS
# build is named `Spirescope` with no extension.
from sts2.__main__ import _program_name  # noqa: E402

templates.env.globals["is_frozen"] = getattr(sys, "frozen", False)
templates.env.globals["cli"] = _program_name()
from sts2 import patches as _patches  # noqa: E402
from sts2.i18n import get_language, get_translator  # noqa: E402

templates.env.globals["t"] = get_translator(get_language())
# Callable, not a snapshot: <html lang> must follow a language change without
# a process restart, and hardcoding lang="en" misdeclared every translated page.
templates.env.globals["ui_lang"] = get_language
templates.env.globals["changed_in"] = _patches.changed_in


def _format_playtime(seconds) -> str:
    """Seconds -> "53h 40m", the way Steam presents playtime.

    The dashboard used to divide by 60 and print the result with an "m"
    suffix, so a 53-hour save read "3220m". That is the same quantity Steam
    shows as roughly 54 hours, but nobody performs that division at a glance,
    and it reads as though the two disagree.
    """
    try:
        total = int(seconds or 0)
    except (TypeError, ValueError):
        return "0m"
    if total < 0:
        total = 0
    hours, minutes = divmod(total // 60, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"


templates.env.filters["playtime"] = _format_playtime
templates.env.globals["current_patch_name"] = (
    lambda: (_patches.current_patch() or {}).get("patch", "")
)
templates.env.globals["deck_js_hash"] = _DECK_JS_HASH
templates.env.globals["collections_js_hash"] = _COLLECTIONS_JS_HASH
templates.env.globals["shortcuts_js_hash"] = _SHORTCUTS_JS_HASH
templates.env.globals["compare_js_hash"] = _COMPARE_JS_HASH
templates.env.globals["live_js_hash"] = _LIVE_JS_HASH

# Repair a half-finished data swap FIRST. A process killed between the
# live->backup and staging->live renames leaves no live dataset, and every
# step below this line reads that directory: seeding would refill it from
# the older bundled copy (making recovery think the live dir is fine and
# abandon the newer backup), and KnowledgeBase would load whatever remained.
# Recovery ran only on the later update-check path before this, which is
# after the damage was already baked in.
try:
    from sts2.updater import recover_data_dir

    if recover_data_dir():
        log.warning("Restored the game data directory from its backup after "
                    "an interrupted update")
except Exception:
    # Never let repair prevent startup; the app degrades on missing data.
    log.debug("Data directory recovery check failed", exc_info=True)

# Frozen builds: seed the writable data dir from bundled data before loading
ensure_data_dir()
# Installs from before the data/state split kept settings, community stats,
# hypotheses and mods inside the data dir. Move them out once, before anything
# reads them, so upgrading users keep their data instead of appearing reset.
_migrated = migrate_state_from_data_dir()
if _migrated:
    log.info("Migrated user state out of the data directory: %s", ", ".join(_migrated))
kb = KnowledgeBase()

_CSRF_SECRET = secrets.token_bytes(32)
_CSRF_MAX_AGE = 14400  # 4 hours


def generate_csrf_token() -> str:
    """Generate an HMAC-signed CSRF token with embedded timestamp."""
    ts = max(0, int(time.time()))
    msg = struct.pack(">Q", ts)
    sig = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{ts:x}.{sig}"


# Expose to templates so the Stop button (and any JS that needs CSRF) can read
# a fresh token from a <meta name="csrf-token"> tag in base.html. Named `csrf`
# to avoid colliding with the per-route `csrf_token` string passed to forms.
templates.env.globals["csrf"] = generate_csrf_token


def tokens_equal(provided: str, expected: str) -> bool:
    """Constant-time token compare that tolerates hostile input.

    compare_digest raises TypeError on non-ASCII str, and every caller here
    feeds it a request header. That turned a 403 into a 500, and in the
    rate-limit middleware it raised before the request was recorded, so a peer
    could stay unthrottled by sending a non-ASCII key. A non-ASCII token can
    never equal these hex/ASCII secrets, so rejecting it early is equivalent.
    """
    if not provided or not provided.isascii():
        return False
    return secrets.compare_digest(provided, expected)


def validate_csrf_token(token: str) -> bool:
    """Validate an HMAC-signed CSRF token and check it's not expired.

    One-sided window: future timestamps (>60s skew) are rejected outright
    so a forged-or-replayed token can't extend its useful life by jumping ts.
    """
    try:
        ts_hex, sig = token.split(".", 1)
        ts = int(ts_hex, 16)
    except (ValueError, AttributeError):
        return False
    now = time.time()
    if ts > now + 60 or now - ts > _CSRF_MAX_AGE:
        return False
    msg = struct.pack(">Q", ts)
    expected = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return tokens_equal(sig, expected)

# Admin endpoints stay disabled until a token is configured. The previous
# auto-generated token was logged at startup, which put a live credential into
# console and container logs; an unset token now just disables the endpoints.
_ADMIN_TOKEN = os.environ.get("SPIRESCOPE_ADMIN_TOKEN", "")
if not _ADMIN_TOKEN:
    log.info("Admin endpoints disabled: set SPIRESCOPE_ADMIN_TOKEN to enable "
             "/api/reload and remote shutdown.")

# ---------------------------------------------------------------------------
# Network authentication (non-loopback binds only)
# ---------------------------------------------------------------------------

_AUTH_COOKIE = "spirescope_auth"
_AUTH_TICKET_MAX_AGE = 7 * 24 * 3600  # one browser sign-in per week


def _issue_auth_ticket() -> str:
    """Signed session ticket set as a cookie after a token sign-in.

    Same HMAC scheme as CSRF but domain-separated with an "auth" prefix, so
    neither artifact can ever be replayed as the other. Signed with the
    per-process secret: a restart signs everyone out, which is the right
    default for a token that gates private data.
    """
    ts = max(0, int(time.time()))
    msg = b"auth" + struct.pack(">Q", ts)
    sig = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{ts:x}.{sig}"


def _validate_auth_ticket(ticket: str) -> bool:
    try:
        ts_hex, sig = ticket.split(".", 1)
        ts = int(ts_hex, 16)
    except (ValueError, AttributeError):
        return False
    now = time.time()
    if ts > now + 60 or now - ts > _AUTH_TICKET_MAX_AGE:
        return False
    msg = b"auth" + struct.pack(">Q", ts)
    expected = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return tokens_equal(sig, expected)

# ---------------------------------------------------------------------------
# Caches
# ---------------------------------------------------------------------------

_rate_limit_store: dict[str, collections.deque] = {}
_RATE_LIMIT_MAX = 60
_RATE_LIMIT_WINDOW = 60.0
_RATE_LIMIT_CLEANUP_INTERVAL = 300.0
_rate_limit_last_cleanup: float = 0

_progress_cache: object = None
_progress_cache_time: float = 0
_PROGRESS_CACHE_TTL = 30.0

_run_cache: list = []
_run_cache_by_id: dict = {}
_run_cache_time: float = 0
_RUN_CACHE_TTL = 30.0

_analytics_cache: dict = {}        # {None: {...}, 5: {...}, ...}
_analytics_cache_time: dict = {}   # {None: float, 5: float, ...}
_ANALYTICS_CACHE_TTL = 60.0

# Single-flight locks: concurrent cold requests used to each run the same
# computation. The generation counter closes the other race — a computation
# that started before _refresh_data cleared the caches must not finish after
# it and re-install pre-refresh data.
_progress_lock = asyncio.Lock()
_runs_lock = asyncio.Lock()
_analytics_lock = asyncio.Lock()
_data_generation = 0


async def _get_progress():
    global _progress_cache, _progress_cache_time
    now = time.monotonic()
    # Use cache_time==0 (never populated) rather than cache is None — get_progress
    # returns None for "no save file" which is a valid cached value.
    if _progress_cache_time != 0 and (now - _progress_cache_time) <= _PROGRESS_CACHE_TTL:
        return _progress_cache
    async with _progress_lock:
        now = time.monotonic()
        if _progress_cache_time == 0 or (now - _progress_cache_time) > _PROGRESS_CACHE_TTL:
            generation = _data_generation
            fresh = await asyncio.to_thread(get_progress)
            if generation == _data_generation:
                _progress_cache = fresh
                _progress_cache_time = time.monotonic()
    return _progress_cache


async def _get_runs():
    global _run_cache, _run_cache_by_id, _run_cache_time
    now = time.monotonic()
    if _run_cache_time != 0 and (now - _run_cache_time) <= _RUN_CACHE_TTL:
        return _run_cache
    async with _runs_lock:
        now = time.monotonic()
        if _run_cache_time == 0 or (now - _run_cache_time) > _RUN_CACHE_TTL:
            generation = _data_generation
            fresh = await asyncio.to_thread(get_run_history)
            if generation == _data_generation:
                _run_cache = fresh
                _run_cache_by_id = {r.id: r for r in fresh}
                _run_cache_time = time.monotonic()
    return _run_cache


async def _get_run_by_id(run_id: str):
    await _get_runs()
    return _run_cache_by_id.get(run_id)


async def _get_analytics(ascension=None):
    global _analytics_cache, _analytics_cache_time
    now = time.monotonic()
    cache_time = _analytics_cache_time.get(ascension, 0)
    if cache_time != 0 and (now - cache_time) <= _ANALYTICS_CACHE_TTL:
        return _analytics_cache[ascension]
    async with _analytics_lock:
        cache_time = _analytics_cache_time.get(ascension, 0)
        now = time.monotonic()
        if cache_time != 0 and (now - cache_time) <= _ANALYTICS_CACHE_TTL:
            return _analytics_cache[ascension]
        generation = _data_generation
        runs = await _get_runs()
        if ascension is not None:
            runs = [r for r in runs if r.ascension == ascension]
        progress = await _get_progress()
        card_stats = progress.card_stats if progress else {}
        result = await asyncio.to_thread(compute_analytics, runs, card_stats, kb)
        if generation == _data_generation:
            _analytics_cache[ascension] = result
            _analytics_cache_time[ascension] = time.monotonic()
        return result


# ---------------------------------------------------------------------------
# Wire up routes
# ---------------------------------------------------------------------------

from sts2.routes import router  # noqa: E402

app.include_router(router)

# CORS
from sts2.config import PORT  # noqa: E402

_cors_env = os.environ.get("STS2_CORS_ORIGINS", "")
_cors_origins = [o.strip() for o in _cors_env.split(",") if o.strip()] if _cors_env else [
    f"http://127.0.0.1:{PORT}", f"http://localhost:{PORT}",
]
app.add_middleware(CORSMiddleware, allow_origins=_cors_origins,
                   allow_methods=["GET", "POST"], allow_headers=["*"],
                   allow_credentials=False)

# ---------------------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------------------


_LOOPBACK_NAMES = ("127.0.0.1", "localhost", "::1")


def _is_loopback_bind(request: Request | None = None) -> bool:
    """Whether this request arrived on a loopback-only deployment.

    Runtime-checked so tests can monkeypatch STS2_HOST without re-importing
    app. The environment variable alone is not trusted: an ASGI embedding
    (uvicorn sts2.app:app --host 0.0.0.0, a gunicorn unit, a parent app that
    mounts this one) can bind every interface while STS2_HOST still reads as
    its 127.0.0.1 default, and skipping authentication on that basis is a
    fail-open default. The ASGI scope's "server" entry is the local address
    the connection actually landed on, so a request that arrived on a
    non-loopback interface is treated as networked no matter what the
    environment claims.
    """
    if os.environ.get("STS2_HOST", "127.0.0.1") not in _LOOPBACK_NAMES:
        return False
    if request is not None:
        server = request.scope.get("server")
        # Only escalate on evidence: a scope host that parses as a real
        # non-loopback IP address. Test transports and some servers put a
        # hostname here instead of the socket address, and a hostname is not
        # proof of anything — treating it as such would refuse legitimate
        # loopback traffic.
        if server and server[0]:
            try:
                if not ipaddress.ip_address(server[0]).is_loopback:
                    return False
            except ValueError:
                pass
    return True


def _allowed_hosts() -> list[str]:
    """Host header values this deployment answers to.

    Without this the app answers to any Host, which is what lets a page that
    has repointed its own hostname at 127.0.0.1 talk to a loopback install as
    same-origin — reading run history and driving CSRF-gated actions, since a
    CSRF token comes free with any rendered page. Loopback deployments know
    exactly which names address them; a network bind is reached by LAN IP or
    hostname, so operators enumerate those in STS2_ALLOWED_HOSTS.
    """
    configured = [h.strip() for h in
                  os.environ.get("STS2_ALLOWED_HOSTS", "").split(",") if h.strip()]
    if configured:
        return configured
    if os.environ.get("STS2_HOST", "127.0.0.1") in _LOOPBACK_NAMES:
        return ["127.0.0.1", "localhost", "[::1]"]
    return ["*"]


@app.middleware("http")
async def require_network_auth(request: Request, call_next):
    """Identity gate for non-loopback binds (runs after rate limiting).

    Loopback binds stay zero-config. On a network bind every request must
    present STS2_AUTH_TOKEN: the X-Auth-Token header for API clients, ?token=
    once for a browser, then a signed cookie. CSRF stays on as the
    browser-intent defense — it proves a POST came from this app's own page,
    which matters exactly because the auth cookie is an ambient credential.
    CSRF alone was never authentication: any client that could GET a page got
    a valid token with it.
    """
    if _is_loopback_bind(request):
        return await call_next(request)
    # Liveness and readiness stay open (Docker healthchecks run in-container
    # against the non-loopback bind); neither serves user data. Preflight
    # carries no auth.
    if request.method == "OPTIONS" or request.url.path in ("/health", "/ready"):
        return await call_next(request)
    auth_token = os.environ.get("STS2_AUTH_TOKEN", "")
    if not auth_token:
        # __main__ refuses to serve this configuration; direct ASGI embeddings
        # get a closed-by-default boundary rather than an open one.
        if os.environ.get("STS2_ALLOW_UNAUTHENTICATED") == "1":
            return await call_next(request)
        return PlainTextResponse(
            "Network binding requires authentication: set STS2_AUTH_TOKEN "
            "(or STS2_ALLOW_UNAUTHENTICATED=1 behind a trusted reverse proxy).",
            status_code=403)
    if tokens_equal(request.headers.get("x-auth-token", ""), auth_token):
        return await call_next(request)
    # The admin token is a strictly stronger credential; a client holding it
    # does not also need the user token.
    if _ADMIN_TOKEN and tokens_equal(request.headers.get("x-admin-token", ""), _ADMIN_TOKEN):
        return await call_next(request)
    if _validate_auth_ticket(request.cookies.get(_AUTH_COOKIE, "")):
        return await call_next(request)
    if tokens_equal(request.query_params.get("token", ""), auth_token):
        # Sign in: drop the token from the URL so it doesn't linger in the
        # address bar or history, and hand the browser a session cookie.
        url = request.url.remove_query_params("token")
        resp = RedirectResponse(str(url), status_code=303)
        # Mark the cookie Secure whenever the exchange is already encrypted,
        # directly or through a terminating proxy. Doing it unconditionally
        # would break the documented plain-HTTP LAN setup outright — the
        # browser would refuse to store the cookie and sign-in would loop —
        # so the flag follows the actual transport instead. Plain HTTP over a
        # network still exposes this credential in transit, which is why the
        # docs point at TLS or a reverse proxy for anything beyond a trusted
        # LAN.
        forwarded_proto = request.headers.get("x-forwarded-proto", "").split(",")[0].strip()
        secure = request.url.scheme == "https" or forwarded_proto == "https"
        resp.set_cookie(_AUTH_COOKIE, _issue_auth_ticket(),
                        max_age=_AUTH_TICKET_MAX_AGE, httponly=True,
                        samesite="lax", secure=secure)
        return resp
    return PlainTextResponse(
        "Authentication required: open ?token=<STS2_AUTH_TOKEN> once in a "
        "browser, or send the X-Auth-Token header.", status_code=401)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Loopback bind = single-user dashboard. Rate-limiting is dead weight there
    # and the unbounded-keys dict is a memory liability if anyone ever spoofs
    # source IPs. Only enforce when bound to a real network interface.
    if _is_loopback_bind():
        return await call_next(request)
    # Exempt static files and CORS preflight. The SSE stream is deliberately
    # NOT exempt: each handshake counts against the window, so one client
    # cannot open connections without limit.
    if request.url.path.startswith("/static/"):
        return await call_next(request)
    if request.method == "OPTIONS":
        return await call_next(request)

    global _rate_limit_last_cleanup
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()

    if now - _rate_limit_last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        stale = [k for k, v in _rate_limit_store.items()
                 if not v or v[-1] < now - _RATE_LIMIT_WINDOW]
        for k in stale:
            del _rate_limit_store[k]
        _rate_limit_last_cleanup = now

    # API key bypass (after cleanup, before sliding window)
    _api_key = os.environ.get("SPIRESCOPE_API_KEY")
    if _api_key:
        provided = request.headers.get("x-api-key", "")
        if tokens_equal(provided, _api_key):
            return await call_next(request)

    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = collections.deque()

    timestamps = _rate_limit_store[ip]
    while timestamps and timestamps[0] < now - _RATE_LIMIT_WINDOW:
        timestamps.popleft()

    remaining = max(0, _RATE_LIMIT_MAX - len(timestamps))
    # The deque holds monotonic stamps (immune to clock changes); the header
    # translates to epoch seconds because process-monotonic values mean
    # nothing to a client.
    if timestamps:
        reset_at = int(time.time() + max(0.0, timestamps[0] + _RATE_LIMIT_WINDOW - now))
    else:
        reset_at = int(time.time() + _RATE_LIMIT_WINDOW)

    if len(timestamps) >= _RATE_LIMIT_MAX:
        resp = PlainTextResponse("Rate limit exceeded. Try again later.", status_code=429)
        resp.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT_MAX)
        resp.headers["X-RateLimit-Remaining"] = "0"
        resp.headers["X-RateLimit-Reset"] = str(reset_at)
        return resp

    timestamps.append(now)
    response = await call_next(request)
    response.headers["X-RateLimit-Limit"] = str(_RATE_LIMIT_MAX)
    response.headers["X-RateLimit-Remaining"] = str(remaining - 1 if remaining > 0 else 0)
    response.headers["X-RateLimit-Reset"] = str(reset_at)
    return response


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    if request.url.path in {"/docs", "/redoc", "/openapi.json"}:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
            "font-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
    else:
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self'; "
            "style-src 'self' 'unsafe-inline'; "
            "font-src 'self'; "
            "img-src 'self' data:; "
            "connect-src 'self'; "
            "frame-ancestors 'none'"
        )
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# ---------------------------------------------------------------------------
# Request body size limit
# ---------------------------------------------------------------------------

# Largest legitimate upload is the 1 MB run import (as multipart, with
# encoding overhead). Everything else is small forms.
_MAX_REQUEST_BODY_BYTES = 2 * 1024 * 1024


class _BodyTooLarge(StarletteHTTPException):
    """413 as an HTTPException subclass: FastAPI wraps generic exceptions
    raised during form parsing into a 400 ("error parsing the body") but
    re-raises HTTPException as-is, so this reaches the 413 handler intact."""

    def __init__(self):
        super().__init__(status_code=413, detail="Request body too large.")


class BodySizeLimitMiddleware:
    """Reject oversized request bodies before any route code parses them.

    The per-route caps (1 MB run import, 500 KB stats import) are checked
    only after Starlette has parsed — and potentially spooled to temp disk —
    the complete multipart body, so a huge upload did all its damage before
    the check ran. Pure ASGI (not BaseHTTPMiddleware) so a declared
    Content-Length is rejected before a single body byte is read, and
    chunked bodies are counted as they stream.
    """

    def __init__(self, app, max_bytes: int = _MAX_REQUEST_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        for name, value in scope.get("headers") or ():
            if name == b"content-length":
                try:
                    declared = int(value)
                except ValueError:
                    declared = self.max_bytes + 1
                if declared > self.max_bytes:
                    return await self._reject(send)
        received = 0
        response_started = False

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise _BodyTooLarge()
            return message

        async def tracking_send(message):
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, counting_receive, tracking_send)
        except _BodyTooLarge:
            if response_started:
                raise
            await self._reject(send)

    @staticmethod
    async def _reject(send):
        await send({"type": "http.response.start", "status": 413,
                    "headers": [(b"content-type", b"text/plain; charset=utf-8")]})
        await send({"type": "http.response.body",
                    "body": b"Request body too large."})


# Added last = outermost: the cheapest rejection runs before any other work.
app.add_middleware(BodySizeLimitMiddleware)

@app.middleware("http")
async def check_host(request: Request, call_next):
    """Refuse a Host header this deployment does not answer to.

    Written here rather than using TrustedHostMiddleware so the allowlist is
    read per request: bound at construction it would freeze whatever the
    environment happened to say at import time, which is both untestable and
    wrong for anything that reconfigures after startup.
    """
    allowed = _allowed_hosts()
    if "*" not in allowed:
        host = (request.headers.get("host", "") or "").split(":")[0]
        # Strip brackets so a literal IPv6 host matches its allowlist entry.
        if host.startswith("[") and host.endswith("]"):
            host = host[1:-1]
        normalized = [h[1:-1] if h.startswith("[") and h.endswith("]") else h
                      for h in allowed]
        if host not in normalized:
            return PlainTextResponse("Invalid host header.", status_code=400)
    return await call_next(request)


# ---------------------------------------------------------------------------
# Exception handlers
# ---------------------------------------------------------------------------

_LOG_SANITIZE_RE = re.compile(r"[\x00-\x1f\x7f]")


def _wants_json(request: Request) -> bool:
    """API paths get JSON errors; pages get the HTML error template.

    Hand-written /api handlers returned a JSON envelope, but anything raised
    past them — request validation, an unknown /api path, an unhandled
    exception — fell through to the HTML page, so a JSON client parsing an
    error got a document instead.
    """
    return request.url.path.startswith("/api/")


@app.exception_handler(StarletteHTTPException)
async def http_error_handler(request: Request, exc: StarletteHTTPException):
    messages = {
        400: "Bad request.",
        403: "Forbidden.",
        404: "Page not found.",
        405: "Method not allowed.",
        413: "Request too large.",
        422: "Invalid request parameters.",
        429: "Too many requests.",
    }
    message = exc.detail if isinstance(getattr(exc, "detail", None), str) else None
    message = message or messages.get(exc.status_code, "Something went wrong.")
    if _wants_json(request):
        return JSONResponse({"error": message, "status": exc.status_code},
                            status_code=exc.status_code)
    return templates.TemplateResponse(request, "error.html", {
        "error_code": exc.status_code,
        "error_message": messages.get(exc.status_code, "Something went wrong."),
    }, status_code=exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError):
    """FastAPI's own 422 shape ({"detail": [...]}) is not this app's error
    envelope; API clients should see one shape from every failure."""
    if _wants_json(request):
        return JSONResponse({"error": "Invalid request parameters.", "status": 422,
                             "detail": jsonable_encoder(exc.errors())},
                            status_code=422)
    return templates.TemplateResponse(request, "error.html", {
        "error_code": 422, "error_message": "Invalid request parameters.",
    }, status_code=422)


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    safe_path = _LOG_SANITIZE_RE.sub("", str(request.url.path))[:200]
    log.exception("Unhandled error on %s", safe_path)
    if _wants_json(request):
        return JSONResponse({"error": "Something went wrong. Please try again.",
                             "status": 500}, status_code=500)
    return templates.TemplateResponse(request, "error.html", {
        "error_code": 500,
        "error_message": "Something went wrong. Please try again.",
    }, status_code=500)


# ---------------------------------------------------------------------------
# Background save watcher
# ---------------------------------------------------------------------------

_save_watcher_last_mtime: float = 0
_save_changed_event = asyncio.Event()


async def _prewarm_caches():
    """Pre-warm caches at startup so first requests don't block the event loop."""
    global _progress_cache, _progress_cache_time
    global _run_cache, _run_cache_by_id, _run_cache_time
    try:
        _progress_cache = await asyncio.to_thread(get_progress)
        _progress_cache_time = time.monotonic()
        _run_cache = await asyncio.to_thread(get_run_history)
        _run_cache_by_id = {r.id: r for r in _run_cache}
        _run_cache_time = time.monotonic()
    except Exception:
        log.debug("Cache pre-warm failed", exc_info=True)


async def _refresh_data():
    """Reload KnowledgeBase, progress, and run caches from disk."""
    global kb, _progress_cache, _progress_cache_time
    global _run_cache, _run_cache_by_id, _run_cache_time
    global _analytics_cache, _analytics_cache_time, _data_generation
    # Invalidate every computation currently in flight: whatever it read, it
    # read before this refresh, and must not be cached after it.
    _data_generation += 1
    log.info("Save files changed, refreshing data")
    _analytics_cache = {}
    _analytics_cache_time = {}
    # A data-bundle install rewrites patches.json underneath us; without this
    # the module-level manifest cache keeps serving the old eras until restart.
    _patches.invalidate_cache()
    new_kb = await asyncio.to_thread(KnowledgeBase)
    new_progress = await asyncio.to_thread(get_progress)
    new_runs = await asyncio.to_thread(get_run_history)
    now = time.monotonic()
    kb = new_kb
    _progress_cache = new_progress
    _progress_cache_time = now
    _run_cache = new_runs
    _run_cache_by_id = {r.id: r for r in new_runs}
    _run_cache_time = now


def _check_mtime() -> float:
    """Latest modification time across save files in EVERY detected tree.

    History merges the vanilla and modded trees, but change detection used
    to watch only the tree that was freshest at startup — switching between
    vanilla and modded play mid-session left the dashboard blind to the
    active one.
    """
    mtime = 0.0
    for save_dir in SAVE_DIRS:
        progress_path = save_dir / "progress.save"
        if progress_path.exists():
            mtime = max(mtime, progress_path.stat().st_mtime)
        history_dir = save_dir / "history"
        if history_dir.exists():
            mtime = max(mtime, history_dir.stat().st_mtime)
            for run_file in history_dir.glob("*.run"):
                try:
                    mtime = max(mtime, run_file.stat().st_mtime)
                except OSError:
                    pass
    return mtime


# Observer handles kept for lifespan shutdown (stop + join).
_observers: list = []


async def _watch_saves():
    global _save_watcher_last_mtime

    # Try watchdog for instant file-change detection — one observer per
    # detected save tree, so vanilla and modded play both trigger refreshes.
    from sts2.watcher import start_observer
    loop = asyncio.get_running_loop()
    for save_dir in SAVE_DIRS:
        if save_dir.exists():
            observer = start_observer(save_dir, loop, _save_changed_event)
            if observer:
                _observers.append(observer)
    use_polling = not _observers

    while True:
        try:
            if use_polling:
                await asyncio.sleep(10)
                if not any(d.exists() for d in SAVE_DIRS):
                    continue
                mtime = _check_mtime()
                changed = mtime > _save_watcher_last_mtime and _save_watcher_last_mtime > 0
                _save_watcher_last_mtime = mtime
            else:
                # Wait for watchdog signal or poll every 30s as a safety net
                try:
                    await asyncio.wait_for(_save_changed_event.wait(), timeout=30.0)
                    _save_changed_event.clear()
                    changed = True
                except asyncio.TimeoutError:
                    changed = False

            if changed:
                await _refresh_data()
                # Signal SSE consumers that fresh data is available.
                # They use wait_for with timeout, so a brief set/clear is enough.
                _save_changed_event.set()
                await asyncio.sleep(0)  # Let SSE coroutines wake
                _save_changed_event.clear()
        except Exception:
            log.debug("Save watcher error", exc_info=True)


# ---------------------------------------------------------------------------
# Game log tailer — builds live run state from godot.log
# ---------------------------------------------------------------------------

_log_tailer = None
_log_run_state: dict | None = None
_log_poll_lock: asyncio.Lock | None = None


async def _poll_game_log_once() -> None:
    """Poll the game log on demand instead of running a permanent background task."""
    global _log_tailer, _log_run_state, _log_poll_lock

    if _log_poll_lock is None:
        _log_poll_lock = asyncio.Lock()

    async with _log_poll_lock:
        if _log_tailer is None:
            from sts2.logparser import LogTailer
            _log_tailer = LogTailer()

        try:
            previous_active = bool(_log_run_state and _log_run_state.get("active"))
            result = await asyncio.to_thread(_log_tailer.poll)
            changed = False
            if result is not None:
                if hasattr(result, "model_dump"):
                    result = result.model_dump()
                elif hasattr(result, "to_dict"):
                    result = result.to_dict()
                _log_run_state = result
                changed = True
            elif _log_tailer.state and not _log_tailer.state.active and previous_active:
                _log_run_state = None
                changed = True

            if changed:
                _save_changed_event.set()
                await asyncio.sleep(0)
                _save_changed_event.clear()
        except Exception:
            log.debug("Log tailer error", exc_info=True)


async def _poll_game_log():
    """Poll the game log every 3 seconds for new events."""
    while True:
        await _poll_game_log_once()
        await asyncio.sleep(3)
