"""FastAPI web dashboard for Spirescope — core setup, middleware, background tasks."""
import asyncio
import collections
import contextlib
import hashlib
import hmac
import logging
import os
import re
import secrets
import struct
import sys
import time

from fastapi import FastAPI, Request
from fastapi.exceptions import StarletteHTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sts2.analytics import compute_analytics
from sts2.config import (
    SAVE_DIR,
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
_CSS_HASH = hashlib.md5(_css_path.read_bytes()).hexdigest()[:8] if _css_path.exists() else "0"
_theme_init_path = STATIC_DIR / "theme-init.js"
_THEME_INIT_HASH = hashlib.md5(_theme_init_path.read_bytes()).hexdigest()[:8] if _theme_init_path.exists() else "0"
_logo_path = STATIC_DIR / "logo.jpg"
_LOGO_HASH = hashlib.md5(_logo_path.read_bytes()).hexdigest()[:8] if _logo_path.exists() else "0"
_hero_bg_path = STATIC_DIR / "hero-bg.jpg"
_HERO_BG_HASH = hashlib.md5(_hero_bg_path.read_bytes()).hexdigest()[:8] if _hero_bg_path.exists() else "0"
_deck_js_path = STATIC_DIR / "deck.js"
_DECK_JS_HASH = hashlib.md5(_deck_js_path.read_bytes()).hexdigest()[:8] if _deck_js_path.exists() else "0"
_collections_js_path = STATIC_DIR / "collections.js"
_COLLECTIONS_JS_HASH = hashlib.md5(_collections_js_path.read_bytes()).hexdigest()[:8] if _collections_js_path.exists() else "0"
_shortcuts_js_path = STATIC_DIR / "shortcuts.js"
_SHORTCUTS_JS_HASH = hashlib.md5(_shortcuts_js_path.read_bytes()).hexdigest()[:8] if _shortcuts_js_path.exists() else "0"
_compare_js_path = STATIC_DIR / "compare.js"
_COMPARE_JS_HASH = hashlib.md5(_compare_js_path.read_bytes()).hexdigest()[:8] if _compare_js_path.exists() else "0"
_live_js_path = STATIC_DIR / "live.js"
_LIVE_JS_HASH = hashlib.md5(_live_js_path.read_bytes()).hexdigest()[:8] if _live_js_path.exists() else "0"


@contextlib.asynccontextmanager
async def _lifespan(application):
    from sts2.updater import check_for_data_update, check_for_update
    check_for_update(templates.env.globals.get("version", "0.0.0"))
    check_for_data_update()
    await _prewarm_caches()
    _watcher_task = asyncio.create_task(_watch_saves())  # noqa: F841
    yield


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


async def _get_progress():
    global _progress_cache, _progress_cache_time
    now = time.monotonic()
    # Use cache_time==0 (never populated) rather than cache is None — get_progress
    # returns None for "no save file" which is a valid cached value.
    if _progress_cache_time == 0 or (now - _progress_cache_time) > _PROGRESS_CACHE_TTL:
        _progress_cache = await asyncio.to_thread(get_progress)
        _progress_cache_time = now
    return _progress_cache


async def _get_runs():
    global _run_cache, _run_cache_by_id, _run_cache_time
    now = time.monotonic()
    if _run_cache_time == 0 or (now - _run_cache_time) > _RUN_CACHE_TTL:
        _run_cache = await asyncio.to_thread(get_run_history)
        _run_cache_by_id = {r.id: r for r in _run_cache}
        _run_cache_time = now
    return _run_cache


async def _get_run_by_id(run_id: str):
    await _get_runs()
    return _run_cache_by_id.get(run_id)


async def _get_analytics(ascension=None):
    global _analytics_cache, _analytics_cache_time
    now = time.monotonic()
    cache_time = _analytics_cache_time.get(ascension, 0)
    if cache_time == 0 or (now - cache_time) > _ANALYTICS_CACHE_TTL:
        runs = await _get_runs()
        if ascension is not None:
            runs = [r for r in runs if r.ascension == ascension]
        progress = await _get_progress()
        card_stats = progress.card_stats if progress else {}
        _analytics_cache[ascension] = await asyncio.to_thread(compute_analytics, runs, card_stats, kb)
        _analytics_cache_time[ascension] = now
    return _analytics_cache[ascension]


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


def _is_loopback_bind() -> bool:
    """Runtime-checked so tests can monkeypatch STS2_HOST without re-importing app."""
    return os.environ.get("STS2_HOST", "127.0.0.1") in ("127.0.0.1", "localhost", "::1")


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
    if _is_loopback_bind():
        return await call_next(request)
    # Liveness stays open (Docker healthchecks run in-container against the
    # non-loopback bind); it serves no user data. Preflight carries no auth.
    if request.method == "OPTIONS" or request.url.path == "/health":
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
        resp.set_cookie(_AUTH_COOKIE, _issue_auth_ticket(),
                        max_age=_AUTH_TICKET_MAX_AGE, httponly=True, samesite="lax")
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
# Exception handlers
# ---------------------------------------------------------------------------

_LOG_SANITIZE_RE = re.compile(r"[\x00-\x1f\x7f]")


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
    return templates.TemplateResponse(request, "error.html", {
        "error_code": exc.status_code,
        "error_message": messages.get(exc.status_code, "Something went wrong."),
    }, status_code=exc.status_code)


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    safe_path = _LOG_SANITIZE_RE.sub("", str(request.url.path))[:200]
    log.exception("Unhandled error on %s", safe_path)
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
    global _analytics_cache, _analytics_cache_time
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
    """Return the latest modification time across save files."""
    mtime = 0.0
    progress_path = SAVE_DIR / "progress.save"
    if progress_path.exists():
        mtime = max(mtime, progress_path.stat().st_mtime)
    history_dir = SAVE_DIR / "history"
    if history_dir.exists():
        mtime = max(mtime, history_dir.stat().st_mtime)
        for run_file in history_dir.glob("*.run"):
            try:
                mtime = max(mtime, run_file.stat().st_mtime)
            except OSError:
                pass
    return mtime


async def _watch_saves():
    global _save_watcher_last_mtime

    # Try watchdog for instant file-change detection
    from sts2.watcher import start_observer
    loop = asyncio.get_running_loop()
    observer = start_observer(SAVE_DIR, loop, _save_changed_event) if SAVE_DIR.exists() else None
    use_polling = observer is None

    while True:
        try:
            if use_polling:
                await asyncio.sleep(10)
                if not SAVE_DIR.exists():
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

_log_tailer = None  # type: ignore[assignment]
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
