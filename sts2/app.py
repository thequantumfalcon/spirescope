"""FastAPI web dashboard for Spirescope."""
import collections
import logging
import time
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sts2.config import TEMPLATES_DIR, STATIC_DIR, CHARACTERS
from sts2.knowledge import KnowledgeBase, get_last_updated
from sts2.saves import get_progress, get_run_history, get_current_run

log = logging.getLogger(__name__)

app = FastAPI(title="Spirescope")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

kb = KnowledgeBase()

# Simple in-memory rate limiter: IP -> deque of request timestamps
_rate_limit_store: dict[str, collections.deque] = {}
_RATE_LIMIT_MAX = 60  # max requests per window
_RATE_LIMIT_WINDOW = 60.0  # seconds

# Run history cache (refreshes every 30s)
_run_cache: list = []
_run_cache_by_id: dict = {}
_run_cache_time: float = 0
_RUN_CACHE_TTL = 30.0


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


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """Simple per-IP rate limiting (60 requests/minute)."""
    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()

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
    return response


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return templates.TemplateResponse(request, "error.html", {
        "error_code": 500,
        "error_message": "Something went wrong. Please try again.",
    }, status_code=500)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    progress = get_progress()
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


@app.get("/cards", response_class=HTMLResponse)
async def cards(request: Request, character: str = None, type: str = None,
                rarity: str = None, cost: str = None, keyword: str = None):
    card_list = kb.get_cards(character=character, card_type=type, rarity=rarity, cost=cost, keyword=keyword)
    return templates.TemplateResponse(request, "cards.html", {
        "cards": card_list, "characters": CHARACTERS,
        "selected_character": character, "selected_type": type,
        "selected_rarity": rarity, "selected_cost": cost, "selected_keyword": keyword,
    })


@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def card_detail(request: Request, card_id: str):
    card = kb.get_card_by_id(card_id)
    synergies = kb.find_synergies(card_id) if card else []
    strategy = kb.get_strategy(card.character) if card else None
    return templates.TemplateResponse(request, "card_detail.html", {
        "card": card, "synergies": synergies, "strategy": strategy,
    })


@app.get("/relics", response_class=HTMLResponse)
async def relics(request: Request, character: str = None, rarity: str = None):
    relic_list = kb.get_relics(character=character, rarity=rarity)
    return templates.TemplateResponse(request, "relics.html", {
        "relics": relic_list, "characters": CHARACTERS,
        "selected_character": character, "selected_rarity": rarity,
    })


@app.get("/potions", response_class=HTMLResponse)
async def potions(request: Request):
    return templates.TemplateResponse(request, "potions.html", {
        "potions": kb.potions,
    })


@app.get("/enemies", response_class=HTMLResponse)
async def enemies(request: Request, act: str = None, type: str = None):
    enemy_list = kb.get_enemies(act=act, enemy_type=type)
    return templates.TemplateResponse(request, "enemies.html", {
        "enemies": enemy_list,
        "selected_act": act, "selected_type": type,
    })


@app.get("/enemies/{enemy_id}", response_class=HTMLResponse)
async def enemy_detail(request: Request, enemy_id: str):
    enemy = kb.get_enemy_by_id(enemy_id)
    progress = get_progress()
    encounter_stats = {}
    if progress:
        for enc_id, stats in progress.encounter_stats.items():
            if enemy_id.split(".")[-1].lower() in enc_id.lower():
                encounter_stats = stats
                break
    return templates.TemplateResponse(request, "enemy_detail.html", {
        "enemy": enemy, "encounter_stats": encounter_stats, "kb": kb,
    })


@app.get("/events", response_class=HTMLResponse)
async def events(request: Request):
    return templates.TemplateResponse(request, "events.html", {
        "events": kb.events,
    })


@app.get("/strategy/{character}", response_class=HTMLResponse)
async def strategy(request: Request, character: str):
    strat = kb.get_strategy(character)
    cards = kb.get_cards(character=character)
    return templates.TemplateResponse(request, "strategy.html", {
        "strategy": strat, "cards": cards, "characters": CHARACTERS,
    })


@app.get("/runs", response_class=HTMLResponse)
async def runs(request: Request):
    run_list = _get_runs()
    return templates.TemplateResponse(request, "runs.html", {
        "runs": run_list, "kb": kb,
    })


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    run = _get_run_by_id(run_id)
    return templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "kb": kb,
    })


@app.get("/live", response_class=HTMLResponse)
async def live_run(request: Request, player: int = 0):
    run = get_current_run(player_index=player)
    analysis = None
    if run.active and run.deck:
        analysis = kb.analyze_deck(run.deck)
    return templates.TemplateResponse(request, "live.html", {
        "run": run, "analysis": analysis, "kb": kb,
        "selected_player": player, "total_players": run.total_players,
    })


@app.get("/api/live")
async def api_live_run(player: int = 0):
    run = get_current_run(player_index=player)
    return run.model_dump()


@app.get("/deck", response_class=HTMLResponse)
async def deck_analyzer(request: Request):
    return templates.TemplateResponse(request, "deck.html", {
        "cards": kb.cards, "analysis": None,
    })


@app.post("/deck/analyze", response_class=HTMLResponse)
async def analyze_deck(request: Request):
    form = await request.form()
    card_ids = form.getlist("card_ids")
    if not card_ids:
        return templates.TemplateResponse(request, "deck.html", {
            "cards": kb.cards, "analysis": {"error": "No cards selected"}, "selected_ids": [],
        })
    analysis = kb.analyze_deck(card_ids)
    return templates.TemplateResponse(request, "deck.html", {
        "cards": kb.cards, "analysis": analysis, "selected_ids": card_ids, "kb": kb,
    })


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
