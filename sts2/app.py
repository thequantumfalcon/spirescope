"""FastAPI web dashboard for Spirescope."""
import logging
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from sts2.config import TEMPLATES_DIR, STATIC_DIR, CHARACTERS
from sts2.knowledge import KnowledgeBase
from sts2.saves import get_progress, get_run_history, get_current_run

log = logging.getLogger(__name__)

app = FastAPI(title="Spirescope")
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

kb = KnowledgeBase()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


@app.exception_handler(Exception)
async def global_error_handler(request: Request, exc: Exception):
    log.exception("Unhandled error on %s", request.url.path)
    return PlainTextResponse("Internal server error", status_code=500)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    progress = get_progress()
    runs = get_run_history()
    return templates.TemplateResponse("index.html", {
        "request": request,
        "characters": CHARACTERS,
        "progress": progress,
        "recent_runs": runs[:5],
        "kb": kb,
        "total_cards": len(kb.cards),
        "total_relics": len(kb.relics),
        "total_potions": len(kb.potions),
        "total_enemies": len(kb.enemies),
    })


@app.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("", max_length=200)):
    results = kb.search(q)
    total = sum(len(v) for v in results.values())
    return templates.TemplateResponse("search.html", {
        "request": request, "query": q, "results": results, "total": total, "kb": kb,
    })


@app.get("/cards", response_class=HTMLResponse)
async def cards(request: Request, character: str = None, type: str = None,
                rarity: str = None, cost: str = None, keyword: str = None):
    card_list = kb.get_cards(character=character, card_type=type, rarity=rarity, cost=cost, keyword=keyword)
    return templates.TemplateResponse("cards.html", {
        "request": request, "cards": card_list, "characters": CHARACTERS,
        "selected_character": character, "selected_type": type,
        "selected_rarity": rarity, "selected_cost": cost, "selected_keyword": keyword,
    })


@app.get("/cards/{card_id}", response_class=HTMLResponse)
async def card_detail(request: Request, card_id: str):
    card = kb.get_card_by_id(card_id)
    synergies = kb.find_synergies(card_id) if card else []
    strategy = kb.get_strategy(card.character) if card else None
    return templates.TemplateResponse("card_detail.html", {
        "request": request, "card": card, "synergies": synergies, "strategy": strategy,
    })


@app.get("/relics", response_class=HTMLResponse)
async def relics(request: Request, character: str = None, rarity: str = None):
    relic_list = kb.get_relics(character=character, rarity=rarity)
    return templates.TemplateResponse("relics.html", {
        "request": request, "relics": relic_list, "characters": CHARACTERS,
        "selected_character": character, "selected_rarity": rarity,
    })


@app.get("/potions", response_class=HTMLResponse)
async def potions(request: Request):
    return templates.TemplateResponse("potions.html", {
        "request": request, "potions": kb.potions,
    })


@app.get("/enemies", response_class=HTMLResponse)
async def enemies(request: Request, act: str = None, type: str = None):
    enemy_list = kb.get_enemies(act=act, enemy_type=type)
    return templates.TemplateResponse("enemies.html", {
        "request": request, "enemies": enemy_list,
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
    return templates.TemplateResponse("enemy_detail.html", {
        "request": request, "enemy": enemy, "encounter_stats": encounter_stats, "kb": kb,
    })


@app.get("/events", response_class=HTMLResponse)
async def events(request: Request):
    return templates.TemplateResponse("events.html", {
        "request": request, "events": kb.events,
    })


@app.get("/strategy/{character}", response_class=HTMLResponse)
async def strategy(request: Request, character: str):
    strat = kb.get_strategy(character)
    cards = kb.get_cards(character=character)
    return templates.TemplateResponse("strategy.html", {
        "request": request, "strategy": strat, "cards": cards, "characters": CHARACTERS,
    })


@app.get("/runs", response_class=HTMLResponse)
async def runs(request: Request):
    run_list = get_run_history()
    return templates.TemplateResponse("runs.html", {
        "request": request, "runs": run_list, "kb": kb,
    })


@app.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    run_list = get_run_history()
    run = next((r for r in run_list if r.id == run_id), None)
    return templates.TemplateResponse("run_detail.html", {
        "request": request, "run": run, "kb": kb,
    })


@app.get("/live", response_class=HTMLResponse)
async def live_run(request: Request):
    run = get_current_run()
    analysis = None
    if run.active and run.deck:
        analysis = kb.analyze_deck(run.deck)
    return templates.TemplateResponse("live.html", {
        "request": request, "run": run, "analysis": analysis, "kb": kb,
    })


@app.get("/api/live")
async def api_live_run():
    run = get_current_run()
    return run.model_dump()


@app.get("/deck", response_class=HTMLResponse)
async def deck_analyzer(request: Request):
    return templates.TemplateResponse("deck.html", {
        "request": request, "cards": kb.cards, "analysis": None,
    })


@app.post("/deck/analyze", response_class=HTMLResponse)
async def analyze_deck(request: Request):
    form = await request.form()
    card_ids = form.getlist("card_ids")
    analysis = kb.analyze_deck(card_ids)
    return templates.TemplateResponse("deck.html", {
        "request": request, "cards": kb.cards, "analysis": analysis, "selected_ids": card_ids, "kb": kb,
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
    }
