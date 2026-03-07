"""FastAPI web dashboard for Spirescope."""
import asyncio
import collections
import contextlib
import hashlib
import json
import logging
import math
import os
import re
import secrets
import sys
import time
from fastapi import FastAPI, Request, Query
from fastapi.exceptions import StarletteHTTPException
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.responses import StreamingResponse

from sts2.analytics import compute_analytics
from sts2.config import TEMPLATES_DIR, STATIC_DIR, CHARACTERS, SAVE_DIR
from sts2.knowledge import KnowledgeBase, get_last_updated
from sts2.saves import get_progress, get_run_history, get_current_run

log = logging.getLogger(__name__)

# CSS cache buster: hash of style.css content at startup
_css_path = STATIC_DIR / "style.css"
_CSS_HASH = hashlib.md5(_css_path.read_bytes()).hexdigest()[:8] if _css_path.exists() else "0"

@contextlib.asynccontextmanager
async def _lifespan(application):
    """Start background save watcher on startup."""
    asyncio.create_task(_watch_saves())
    yield


app = FastAPI(title="Spirescope", lifespan=_lifespan)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=False), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
templates.env.globals["css_hash"] = _CSS_HASH

kb = KnowledgeBase()

# CSRF token (regenerated per server start, validated on POST)
_CSRF_TOKEN = secrets.token_hex(32)

# Admin token for protected endpoints (reload)
# Use env var if set, otherwise generate. Print to stderr once (never to log files).
_ADMIN_TOKEN = os.environ.get("SPIRESCOPE_ADMIN_TOKEN", secrets.token_hex(32))
if "SPIRESCOPE_ADMIN_TOKEN" not in os.environ:
    print(f"[Spirescope] Admin token: {_ADMIN_TOKEN}", file=sys.stderr)

# Simple in-memory rate limiter: IP -> deque of request timestamps
_rate_limit_store: dict[str, collections.deque] = {}
_RATE_LIMIT_MAX = 60  # max requests per window
_RATE_LIMIT_WINDOW = 60.0  # seconds
_RATE_LIMIT_CLEANUP_INTERVAL = 300.0  # purge stale IPs every 5 min
_rate_limit_last_cleanup: float = 0

# Progress cache (refreshes every 30s)
_progress_cache: object = None
_progress_cache_time: float = 0
_PROGRESS_CACHE_TTL = 30.0

# Run history cache (refreshes every 30s)
_run_cache: list = []
_run_cache_by_id: dict = {}
_run_cache_time: float = 0
_RUN_CACHE_TTL = 30.0

# Analytics cache (refreshes every 60s — heavier computation)
_analytics_cache: dict = {}
_analytics_cache_time: float = 0
_ANALYTICS_CACHE_TTL = 60.0


def _get_progress():
    """Return cached player progress, refreshing if stale."""
    global _progress_cache, _progress_cache_time
    now = time.monotonic()
    if _progress_cache is None or (now - _progress_cache_time) > _PROGRESS_CACHE_TTL:
        _progress_cache = get_progress()
        _progress_cache_time = now
    return _progress_cache


def _get_runs():
    """Return cached run history, refreshing if stale."""
    global _run_cache, _run_cache_by_id, _run_cache_time
    now = time.monotonic()
    if not _run_cache or (now - _run_cache_time) > _RUN_CACHE_TTL:
        _run_cache = get_run_history()
        _run_cache_by_id = {r.id: r for r in _run_cache}
        _run_cache_time = now
    return _run_cache


def _get_run_by_id(run_id: str):
    """O(1) run lookup from cache."""
    _get_runs()  # ensure cache is fresh
    return _run_cache_by_id.get(run_id)


def _get_analytics():
    """Return cached analytics, recomputing if stale."""
    global _analytics_cache, _analytics_cache_time
    now = time.monotonic()
    if not _analytics_cache or (now - _analytics_cache_time) > _ANALYTICS_CACHE_TTL:
        runs = _get_runs()
        progress = _get_progress()
        card_stats = progress.card_stats if progress else {}
        _analytics_cache = compute_analytics(runs, card_stats)
        _analytics_cache_time = now
    return _analytics_cache


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Simple per-IP rate limiting (60 requests/minute) with periodic cleanup."""
    global _rate_limit_last_cleanup
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()

    # Periodic cleanup: remove IPs with no recent requests
    if now - _rate_limit_last_cleanup > _RATE_LIMIT_CLEANUP_INTERVAL:
        stale = [k for k, v in _rate_limit_store.items()
                 if not v or v[-1] < now - _RATE_LIMIT_WINDOW]
        for k in stale:
            del _rate_limit_store[k]
        _rate_limit_last_cleanup = now

    if ip not in _rate_limit_store:
        _rate_limit_store[ip] = collections.deque()

    timestamps = _rate_limit_store[ip]
    # Purge old entries outside the window
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
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none'"
    )
    # Cache static assets for 1 hour
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=3600"
    return response


# Sanitize user input before logging (prevent log injection via newlines/control chars)
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


# Background save file watcher: detect new runs and auto-reload KB
_save_watcher_last_mtime: float = 0


async def _watch_saves():
    """Background task: watch save dir for changes, rebuild KB when new data appears."""
    global kb, _save_watcher_last_mtime, _progress_cache, _progress_cache_time
    global _run_cache, _run_cache_time, _analytics_cache, _analytics_cache_time
    while True:
        await asyncio.sleep(10)
        try:
            if not SAVE_DIR.exists():
                continue
            # Check if progress.save or history dir changed
            mtime = 0.0
            progress_path = SAVE_DIR / "progress.save"
            if progress_path.exists():
                mtime = max(mtime, progress_path.stat().st_mtime)
            history_dir = SAVE_DIR / "history"
            if history_dir.exists():
                mtime = max(mtime, history_dir.stat().st_mtime)
            if mtime > _save_watcher_last_mtime and _save_watcher_last_mtime > 0:
                log.info("Save files changed, refreshing data")
                # Invalidate caches so next request gets fresh data
                _progress_cache = None
                _progress_cache_time = 0
                _run_cache_time = 0
                _analytics_cache.clear()
                _analytics_cache_time = 0
                # Rebuild KB to pick up newly discovered enemies/events
                new_kb = KnowledgeBase()
                kb = new_kb
            _save_watcher_last_mtime = mtime
        except Exception:
            log.debug("Save watcher error", exc_info=True)


@app.get("/health")
async def health():
    """Health check for uptime monitors and load balancers."""
    return {"status": "ok", "cards": len(kb.cards)}


@app.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /deck/analyze\nSitemap: /sitemap.xml\n"


@app.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml(request: Request):
    """Dynamic sitemap for SEO — lists all detail pages."""
    base = str(request.base_url).rstrip("/")
    urls = ["/", "/cards", "/relics", "/potions", "/enemies", "/events", "/deck", "/live", "/runs", "/analytics", "/community"]
    for card in kb.cards:
        urls.append(f"/cards/{card.id}")
    for relic in kb.relics:
        urls.append(f"/relics/{relic.id}")
    for enemy in kb.enemies:
        urls.append(f"/enemies/{enemy.id}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        lines.append(f"  <url><loc>{base}{url}</loc></url>")
    lines.append("</urlset>")
    return PlainTextResponse("\n".join(lines), media_type="application/xml")


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    progress = _get_progress()
    runs = _get_runs()
    return templates.TemplateResponse(request, "index.html", {
        "characters": CHARACTERS,
        "progress": progress,
        "recent_runs": runs[:5],
        "kb": kb,
        "total_cards": len(kb.cards),
        "total_relics": len(kb.relics),
        "total_potions": len(kb.potions),
        "total_enemies": len(kb.enemies),
        "last_updated": get_last_updated(),
    })


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("", max_length=200)):
    results = kb.search(q)
    total = sum(len(v) for k, v in results.items() if k != "suggestions")
    return templates.TemplateResponse(request, "search.html", {
        "query": q, "results": results, "total": total, "kb": kb,
    })


_CARDS_PER_PAGE = 30


@app.get("/cards", response_class=HTMLResponse)
async def cards(request: Request, character: str = None,
                type: str = Query(None, alias="type"),
                rarity: str = None, cost: str = None, keyword: str = None,
                page: int = Query(1, ge=1)):
    card_type = type  # avoid shadowing builtin in function body
    card_list = kb.get_cards(character=character, card_type=card_type, rarity=rarity, cost=cost, keyword=keyword)
    total_cards = len(card_list)
    total_pages = max(1, math.ceil(total_cards / _CARDS_PER_PAGE))
    page = min(page, total_pages)
    start = (page - 1) * _CARDS_PER_PAGE
    paged_cards = card_list[start:start + _CARDS_PER_PAGE]
    progress = _get_progress()
    card_stats = progress.card_stats if progress else {}
    return templates.TemplateResponse(request, "cards.html", {
        "cards": paged_cards, "total_cards": total_cards, "characters": CHARACTERS,
        "selected_character": character, "selected_type": card_type,
        "selected_rarity": rarity, "selected_cost": cost, "selected_keyword": keyword,
        "page": page, "total_pages": total_pages, "card_stats": card_stats,
    })


@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def card_detail(request: Request, card_id: str):
    card = kb.get_card_by_id(card_id)
    if not card:
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Card '{card_id}' not found.",
        }, status_code=404)
    synergies = kb.find_synergies(card_id)
    strategy = kb.get_strategy(card.character)
    progress = _get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    # Compute win rate from run history for this card
    runs_with_card = [r for r in _get_runs() if card_id in r.deck]
    card_run_wins = sum(1 for r in runs_with_card if r.win)
    card_run_total = len(runs_with_card)
    community_tips = kb.get_community_tips(card.name)
    return templates.TemplateResponse(request, "card_detail.html", {
        "card": card, "synergies": synergies, "strategy": strategy,
        "card_stats": card_stats,
        "card_run_wins": card_run_wins, "card_run_total": card_run_total,
        "community_tips": community_tips,
    })


@app.get("/relics", response_class=HTMLResponse)
async def relics(request: Request, character: str = None, rarity: str = None):
    relic_list = kb.get_relics(character=character, rarity=rarity)
    return templates.TemplateResponse(request, "relics.html", {
        "relics": relic_list, "characters": CHARACTERS,
        "selected_character": character, "selected_rarity": rarity,
    })


@app.get("/relics/{relic_id:path}", response_class=HTMLResponse)
async def relic_detail(request: Request, relic_id: str):
    relic = kb.get_relic_by_id(relic_id)
    if not relic:
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Relic '{relic_id}' not found.",
        }, status_code=404)
    # Find runs where this relic was used
    relic_runs = [r for r in _get_runs() if relic_id in r.relics]
    community_tips = kb.get_community_tips(relic.name)
    return templates.TemplateResponse(request, "relic_detail.html", {
        "relic": relic, "relic_runs": relic_runs, "community_tips": community_tips,
    })


@app.get("/potions", response_class=HTMLResponse)
async def potions(request: Request, rarity: str = None):
    potion_list = kb.get_potions(rarity=rarity)
    return templates.TemplateResponse(request, "potions.html", {
        "potions": potion_list, "selected_rarity": rarity,
        "total_potions": len(kb.potions),
    })


@app.get("/enemies", response_class=HTMLResponse)
async def enemies(request: Request, act: str = None,
                  type: str = Query(None, alias="type")):
    enemy_type = type
    enemy_list = kb.get_enemies(act=act, enemy_type=enemy_type)
    return templates.TemplateResponse(request, "enemies.html", {
        "enemies": enemy_list,
        "selected_act": act, "selected_type": enemy_type,
    })


@app.get("/enemies/{enemy_id}", response_class=HTMLResponse)
async def enemy_detail(request: Request, enemy_id: str):
    enemy = kb.get_enemy_by_id(enemy_id)
    if not enemy:
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Enemy '{enemy_id}' not found.",
        }, status_code=404)
    progress = _get_progress()
    encounter_stats = {}
    enemy_fight_stats = {}
    if progress:
        # Check encounter_stats (by encounter ID)
        for enc_id, stats in progress.encounter_stats.items():
            if enemy_id.split(".")[-1].lower() in enc_id.lower():
                encounter_stats = stats
                break
        # Check enemy_stats (by monster ID) — more granular per-enemy data
        enemy_fight_stats = progress.enemy_stats.get(enemy_id, {})
        if not encounter_stats:
            encounter_stats = enemy_fight_stats
    community_tips = kb.get_community_tips(enemy.name)
    return templates.TemplateResponse(request, "enemy_detail.html", {
        "enemy": enemy, "encounter_stats": encounter_stats, "kb": kb,
        "community_tips": community_tips,
    })


@app.get("/events", response_class=HTMLResponse)
async def events(request: Request, act: str = None):
    event_list = kb.events
    if act:
        event_list = [e for e in event_list if act in e.act]
    return templates.TemplateResponse(request, "events.html", {
        "events": event_list, "selected_act": act, "total_events": len(kb.events),
    })


@app.get("/strategy/{character}", response_class=HTMLResponse)
async def strategy(request: Request, character: str):
    strat = kb.get_strategy(character)
    if not strat:
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"No strategy found for '{character}'.",
        }, status_code=404)
    cards = kb.get_cards(character=character)
    return templates.TemplateResponse(request, "strategy.html", {
        "strategy": strat, "cards": cards, "characters": CHARACTERS,
    })


@app.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, character: str = None, result: str = None):
    run_list = _get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    total = len(run_list)
    wins = sum(1 for r in run_list if r.win)
    return templates.TemplateResponse(request, "runs.html", {
        "runs": filtered, "kb": kb, "characters": CHARACTERS,
        "selected_character": character, "selected_result": result,
        "total_runs": total, "total_wins": wins,
    })


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    run = _get_run_by_id(run_id)
    if not run:
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Run '{run_id}' not found.",
        }, status_code=404)
    return templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "kb": kb,
    })


@app.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    stats = _get_analytics()
    return templates.TemplateResponse(request, "analytics.html", {
        "stats": stats, "kb": kb,
    })


@app.get("/api/analytics")
async def api_analytics():
    return _get_analytics()


@app.get("/community", response_class=HTMLResponse)
async def community(request: Request):
    meta_posts = kb.meta_posts
    # Group cards by their community tier for display
    tier_cards: dict[str, list] = {}
    for card in kb.cards:
        if card.tier and card.tier in ("S", "A", "B", "C", "D", "F"):
            tier_cards.setdefault(card.tier, []).append(card)
    return templates.TemplateResponse(request, "community.html", {
        "meta_posts": meta_posts, "tier_cards": tier_cards,
    })


@app.get("/live", response_class=HTMLResponse)
async def live_run(request: Request, player: int = Query(0, ge=0, le=3)):
    run = get_current_run(player_index=player)
    analysis = None
    if run.active and run.deck:
        analysis = kb.analyze_deck(run.deck)
    return templates.TemplateResponse(request, "live.html", {
        "run": run, "analysis": analysis, "kb": kb,
        "selected_player": player, "total_players": run.total_players,
    })


@app.get("/api/live")
async def api_live_run(player: int = Query(0, ge=0, le=3)):
    run = get_current_run(player_index=player)
    return run.model_dump()


# SSE connection tracking
_sse_connections: int = 0
_SSE_MAX_CONNECTIONS = 10
_SSE_IDLE_TIMEOUT = 300.0  # close after 5 min of no state changes


@app.get("/api/live/stream")
async def live_stream(player: int = Query(0, ge=0, le=3)):
    """SSE stream that pushes live run state every 3 seconds."""
    global _sse_connections
    if _sse_connections >= _SSE_MAX_CONNECTIONS:
        return PlainTextResponse("Too many live connections. Close another tab.", status_code=429)

    async def event_generator():
        global _sse_connections
        _sse_connections += 1
        try:
            last_hash = ""
            idle_since = time.monotonic()
            while True:
                run = get_current_run(player_index=player)
                data = run.model_dump()
                data_json = json.dumps(data, sort_keys=True)
                current_hash = str(hash(data_json))
                if current_hash != last_hash:
                    last_hash = current_hash
                    idle_since = time.monotonic()
                    yield f"data: {data_json}\n\n"
                elif time.monotonic() - idle_since > _SSE_IDLE_TIMEOUT:
                    yield f"event: timeout\ndata: {{}}\n\n"
                    return
                await asyncio.sleep(3)
        finally:
            _sse_connections -= 1

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/reload")
async def reload_data(request: Request, token: str = Query(...)):
    """Reload the knowledge base from disk (requires admin token)."""
    if not secrets.compare_digest(token, _ADMIN_TOKEN):
        return PlainTextResponse("Unauthorized.", status_code=403)
    global kb
    new_kb = KnowledgeBase()  # build fully before swapping
    kb = new_kb
    return {"status": "ok", "cards": len(kb.cards), "relics": len(kb.relics),
            "potions": len(kb.potions), "enemies": len(kb.enemies)}


@app.get("/deck", response_class=HTMLResponse)
async def deck_analyzer(request: Request):
    return templates.TemplateResponse(request, "deck.html", {
        "cards": kb.cards, "analysis": None, "csrf_token": _CSRF_TOKEN,
    })


_MAX_DECK_SIZE = 100  # max cards in a deck analysis request


@app.post("/deck/analyze", response_class=HTMLResponse)
async def analyze_deck(request: Request):
    form = await request.form()
    token = form.get("csrf_token", "")
    if not secrets.compare_digest(token, _CSRF_TOKEN):
        return templates.TemplateResponse(request, "error.html", {
            "error_code": 403, "error_message": "Invalid form submission. Please go back and try again.",
        }, status_code=403)
    card_ids = form.getlist("card_ids")[:_MAX_DECK_SIZE]
    if not card_ids:
        return templates.TemplateResponse(request, "deck.html", {
            "cards": kb.cards, "analysis": {"error": "No cards selected"}, "selected_ids": [],
            "csrf_token": _CSRF_TOKEN,
        })
    analysis = kb.analyze_deck(card_ids)
    return templates.TemplateResponse(request, "deck.html", {
        "cards": kb.cards, "analysis": analysis, "selected_ids": card_ids, "kb": kb,
        "csrf_token": _CSRF_TOKEN,
    })


@app.get("/api/cards/{card_id}")
async def api_card(card_id: str):
    card = kb.get_card_by_id(card_id)
    if not card:
        return PlainTextResponse("Card not found.", status_code=404)
    progress = _get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    return {**card.model_dump(), "stats": card_stats}


@app.get("/api/runs")
async def api_runs(character: str = None, result: str = None):
    run_list = _get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    return [r.model_dump() for r in filtered]


@app.get("/api/search")
async def api_search(q: str = Query("", max_length=200)):
    results = kb.search(q)
    return {
        "query": q,
        "cards": [c.model_dump() for c in results["cards"]],
        "relics": [r.model_dump() for r in results["relics"]],
        "potions": [p.model_dump() for p in results["potions"]],
        "enemies": [e.model_dump() for e in results["enemies"]],
        "events": [e.model_dump() for e in results["events"]],
        "suggestions": results.get("suggestions", []),
    }
