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
import time
from fastapi import FastAPI, Request
from fastapi.exceptions import StarletteHTTPException
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from fastapi.middleware.cors import CORSMiddleware
from sts2.analytics import compute_analytics
from sts2.config import TEMPLATES_DIR, STATIC_DIR, SAVE_DIR
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


@contextlib.asynccontextmanager
async def _lifespan(application):
    from sts2.updater import check_for_update
    check_for_update(templates.env.globals.get("version", "0.0.0"))
    await _prewarm_caches()
    _watcher_task = asyncio.create_task(_watch_saves())  # noqa: F841
    _log_task = asyncio.create_task(_poll_game_log())  # noqa: F841
    yield


app = FastAPI(title="Spirescope", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["css_hash"] = _CSS_HASH
templates.env.globals["theme_init_hash"] = _THEME_INIT_HASH
templates.env.globals["logo_hash"] = _LOGO_HASH
try:
    from importlib.metadata import version as _get_version
    templates.env.globals["version"] = _get_version("spirescope")
except Exception:
    from sts2.config import VERSION
    templates.env.globals["version"] = VERSION

kb = KnowledgeBase()

_CSRF_SECRET = secrets.token_bytes(32)
_CSRF_MAX_AGE = 14400  # 4 hours


def generate_csrf_token() -> str:
    """Generate an HMAC-signed CSRF token with embedded timestamp."""
    ts = max(0, int(time.time()))
    msg = struct.pack(">Q", ts)
    sig = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return f"{ts:x}.{sig}"


def validate_csrf_token(token: str) -> bool:
    """Validate an HMAC-signed CSRF token and check it's not expired."""
    try:
        ts_hex, sig = token.split(".", 1)
        ts = int(ts_hex, 16)
    except (ValueError, AttributeError):
        return False
    if abs(time.time() - ts) > _CSRF_MAX_AGE:
        return False
    msg = struct.pack(">Q", ts)
    expected = hmac.new(_CSRF_SECRET, msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(sig, expected)

_ADMIN_TOKEN = os.environ.get("SPIRESCOPE_ADMIN_TOKEN", secrets.token_hex(32))
if "SPIRESCOPE_ADMIN_TOKEN" not in os.environ:
    log.debug("Admin token: %s", _ADMIN_TOKEN)

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

_analytics_cache: dict = {}
_analytics_cache_time: float = 0
_ANALYTICS_CACHE_TTL = 60.0


async def _get_progress():
    global _progress_cache, _progress_cache_time
    now = time.monotonic()
    if _progress_cache is None or (now - _progress_cache_time) > _PROGRESS_CACHE_TTL:
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


async def _get_analytics():
    global _analytics_cache, _analytics_cache_time
    now = time.monotonic()
    if _analytics_cache_time == 0 or (now - _analytics_cache_time) > _ANALYTICS_CACHE_TTL:
        runs = await _get_runs()
        progress = await _get_progress()
        card_stats = progress.card_stats if progress else {}
        _analytics_cache = await asyncio.to_thread(compute_analytics, runs, card_stats)
        _analytics_cache_time = now
    return _analytics_cache


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


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    # Exempt static files, SSE stream, and CORS preflight
    if request.url.path.startswith("/static/") or request.url.path == "/api/live/stream":
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
        if provided and secrets.compare_digest(provided, _api_key):
            return await call_next(request)

    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = collections.deque()

    timestamps = _rate_limit_store[ip]
    while timestamps and timestamps[0] < now - _RATE_LIMIT_WINDOW:
        timestamps.popleft()

    if len(timestamps) >= _RATE_LIMIT_MAX:
        return PlainTextResponse("Rate limit exceeded. Try again later.", status_code=429)

    timestamps.append(now)
    return await call_next(request)


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
        404: "Page not found.",
        405: "Method not allowed.",
        422: "Invalid request parameters.",
    }
    return templates.TemplateResponse(request, "error.html", {
        "error_code": exc.status_code,
        "error_message": messages.get(exc.status_code, exc.detail),
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
    _analytics_cache_time = 0
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


async def _poll_game_log():
    """Poll the game log every 3 seconds for new events."""
    global _log_tailer, _log_run_state
    from sts2.logparser import LogTailer
    _log_tailer = LogTailer()
    while True:
        try:
            result = await asyncio.to_thread(_log_tailer.poll)
            if result is not None:
                _log_run_state = result
                # Wake SSE consumers
                _save_changed_event.set()
                await asyncio.sleep(0)
                _save_changed_event.clear()
            elif _log_tailer.state and not _log_tailer.state.active:
                _log_run_state = None
        except Exception:
            log.debug("Log tailer error", exc_info=True)
        await asyncio.sleep(3)
