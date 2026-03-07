"""Route handlers for Spirescope."""
import asyncio
import json
import math
import secrets
import time
from xml.sax.saxutils import escape as xml_escape
from fastapi import APIRouter, Request, Query
from fastapi.responses import HTMLResponse, PlainTextResponse
from starlette.responses import StreamingResponse

from sts2.config import CHARACTERS
from sts2.saves import get_current_run

router = APIRouter()


def _app():
    """Lazy import to access app.py shared state (kb, templates, caches).

    Routes import app → app imports routes, so we break the cycle by deferring.
    Each route calls a = _app() then uses a.kb, a.templates, a._get_progress(), etc.
    This also lets tests mock app-level functions (e.g. patch("sts2.app._get_progress"))
    because routes always do a live lookup rather than capturing a reference at import.
    """
    import sts2.app as _a
    return _a


# ---------------------------------------------------------------------------
# Utility / SEO
# ---------------------------------------------------------------------------

@router.get("/health")
async def health():
    a = _app()
    return {"status": "ok", "cards": len(a.kb.cards)}


@router.get("/robots.txt", response_class=PlainTextResponse)
async def robots_txt():
    return "User-agent: *\nAllow: /\nDisallow: /api/\nDisallow: /deck/analyze\nSitemap: /sitemap.xml\n"


@router.get("/sitemap.xml", response_class=PlainTextResponse)
async def sitemap_xml(request: Request):
    a = _app()
    base = str(request.base_url).rstrip("/")
    urls = ["/", "/cards", "/relics", "/potions", "/enemies", "/events",
            "/deck", "/live", "/runs", "/analytics", "/community", "/guide"]
    for card in a.kb.cards:
        urls.append(f"/cards/{card.id}")
    for relic in a.kb.relics:
        urls.append(f"/relics/{relic.id}")
    for enemy in a.kb.enemies:
        urls.append(f"/enemies/{enemy.id}")
    lines = ['<?xml version="1.0" encoding="UTF-8"?>',
             '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">']
    for url in urls:
        lines.append(f"  <url><loc>{xml_escape(base)}{xml_escape(url)}</loc></url>")
    lines.append("</urlset>")
    return PlainTextResponse("\n".join(lines), media_type="application/xml")


# ---------------------------------------------------------------------------
# HTML pages
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
async def index(request: Request):
    from sts2.knowledge import get_last_updated
    from sts2.updater import get_update_info
    a = _app()
    progress = a._get_progress()
    runs = a._get_runs()
    undiscovered = []
    if progress and progress.discovered_cards:
        undiscovered = a.kb.get_undiscovered_cards(progress.discovered_cards)[:12]
    return a.templates.TemplateResponse(request, "index.html", {
        "characters": CHARACTERS, "progress": progress, "recent_runs": runs[:5],
        "kb": a.kb, "total_cards": len(a.kb.cards), "total_relics": len(a.kb.relics),
        "total_potions": len(a.kb.potions), "total_enemies": len(a.kb.enemies),
        "last_updated": get_last_updated(), "data_status": a.kb.get_data_status(),
        "update_info": get_update_info(), "undiscovered_cards": undiscovered,
    })


@router.get("/search", response_class=HTMLResponse)
async def search(request: Request, q: str = Query("", max_length=200)):
    a = _app()
    results = a.kb.search(q)
    total = sum(len(v) for k, v in results.items() if k != "suggestions")
    return a.templates.TemplateResponse(request, "search.html", {
        "query": q, "results": results, "total": total, "kb": a.kb,
    })


_CARDS_PER_PAGE = 30


@router.get("/cards", response_class=HTMLResponse)
async def cards(request: Request, character: str = Query(None, max_length=50),
                type: str = Query(None, alias="type", max_length=50),
                rarity: str = Query(None, max_length=50), cost: str = Query(None, max_length=10),
                keyword: str = Query(None, max_length=100),
                sort: str = Query(None, max_length=20), page: int = Query(1, ge=1)):
    a = _app()
    card_type = type
    card_list = a.kb.get_cards(character=character, card_type=card_type,
                               rarity=rarity, cost=cost, keyword=keyword)
    progress = a._get_progress()
    card_stats = progress.card_stats if progress else {}

    # Sort options
    if sort == "winrate":
        analytics = a._get_analytics()
        wr_lookup = {cr["id"]: cr["win_rate"] for cr in analytics.get("card_rankings", [])}
        card_list = sorted(card_list, key=lambda c: wr_lookup.get(c.id, -1), reverse=True)
    elif sort == "pickrate":
        card_list = sorted(card_list, key=lambda c: (
            card_stats.get(c.id, {}).get("picked", 0) /
            max(1, card_stats.get(c.id, {}).get("picked", 0) + card_stats.get(c.id, {}).get("skipped", 0))
        ), reverse=True)

    total_cards = len(card_list)
    total_pages = max(1, math.ceil(total_cards / _CARDS_PER_PAGE))
    page = min(page, total_pages)
    start = (page - 1) * _CARDS_PER_PAGE
    paged_cards = card_list[start:start + _CARDS_PER_PAGE]
    return a.templates.TemplateResponse(request, "cards.html", {
        "cards": paged_cards, "total_cards": total_cards, "characters": CHARACTERS,
        "selected_character": character, "selected_type": card_type,
        "selected_rarity": rarity, "selected_cost": cost, "selected_keyword": keyword,
        "selected_sort": sort,
        "page": page, "total_pages": total_pages, "card_stats": card_stats,
    })


@router.get("/cards/{card_id}", response_class=HTMLResponse)
async def card_detail(request: Request, card_id: str):
    a = _app()
    card = a.kb.get_card_by_id(card_id)
    if not card:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Card '{card_id}' not found.",
        }, status_code=404)
    synergies = a.kb.find_synergies(card_id)
    strategy = a.kb.get_strategy(card.character)
    progress = a._get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    runs_with_card = [r for r in a._get_runs() if card_id in r.deck]
    card_run_wins = sum(1 for r in runs_with_card if r.win)
    card_run_total = len(runs_with_card)
    community_tips = a.kb.get_community_tips(card.name)
    # Enemies faced in runs containing this card
    enemies_faced: dict[str, dict] = {}
    for run in runs_with_card:
        for floor in run.floors:
            if floor.encounter and floor.damage_taken > 0:
                enc = floor.encounter
                if enc not in enemies_faced:
                    enemies_faced[enc] = {"fights": 0, "total_damage": 0}
                enemies_faced[enc]["fights"] += 1
                enemies_faced[enc]["total_damage"] += floor.damage_taken
    top_enemies = sorted(enemies_faced.items(),
                         key=lambda x: -x[1]["fights"])[:6]
    return a.templates.TemplateResponse(request, "card_detail.html", {
        "card": card, "synergies": synergies, "strategy": strategy,
        "card_stats": card_stats,
        "card_run_wins": card_run_wins, "card_run_total": card_run_total,
        "community_tips": community_tips, "top_enemies": top_enemies, "kb": a.kb,
    })


@router.get("/relics", response_class=HTMLResponse)
async def relics(request: Request, character: str = Query(None, max_length=50),
                 rarity: str = Query(None, max_length=50)):
    a = _app()
    relic_list = a.kb.get_relics(character=character, rarity=rarity)
    return a.templates.TemplateResponse(request, "relics.html", {
        "relics": relic_list, "characters": CHARACTERS,
        "selected_character": character, "selected_rarity": rarity,
    })


@router.get("/relics/{relic_id:path}", response_class=HTMLResponse)
async def relic_detail(request: Request, relic_id: str):
    a = _app()
    relic = a.kb.get_relic_by_id(relic_id)
    if not relic:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Relic '{relic_id}' not found.",
        }, status_code=404)
    relic_runs = [r for r in a._get_runs() if relic_id in r.relics]
    community_tips = a.kb.get_community_tips(relic.name)
    # Relic synergy — other relics commonly found in winning runs with this one
    relic_synergies = []
    analytics = a._get_analytics()
    for edge in analytics.get("relic_synergy_edges", []):
        if edge["source"] == relic_id:
            relic_synergies.append({"id": edge["target"], "weight": edge["weight"]})
        elif edge["target"] == relic_id:
            relic_synergies.append({"id": edge["source"], "weight": edge["weight"]})
    relic_synergies.sort(key=lambda x: -x["weight"])
    # Archetypes mentioning this relic
    relic_archetypes = a.kb.find_relic_archetypes(relic.name)
    return a.templates.TemplateResponse(request, "relic_detail.html", {
        "relic": relic, "relic_runs": relic_runs, "community_tips": community_tips,
        "relic_synergies": relic_synergies[:6], "relic_archetypes": relic_archetypes,
        "kb": a.kb,
    })


@router.get("/potions", response_class=HTMLResponse)
async def potions(request: Request, rarity: str = Query(None, max_length=50)):
    a = _app()
    potion_list = a.kb.get_potions(rarity=rarity)
    analytics = a._get_analytics()
    potion_stats = analytics.get("potion_stats", {})
    return a.templates.TemplateResponse(request, "potions.html", {
        "potions": potion_list, "selected_rarity": rarity,
        "total_potions": len(a.kb.potions), "potion_stats": potion_stats,
    })


@router.get("/enemies", response_class=HTMLResponse)
async def enemies(request: Request, act: str = Query(None, max_length=50),
                  type: str = Query(None, alias="type", max_length=50)):
    a = _app()
    enemy_type = type
    enemy_list = a.kb.get_enemies(act=act, enemy_type=enemy_type)
    return a.templates.TemplateResponse(request, "enemies.html", {
        "enemies": enemy_list, "selected_act": act, "selected_type": enemy_type,
    })


@router.get("/enemies/{enemy_id}", response_class=HTMLResponse)
async def enemy_detail(request: Request, enemy_id: str):
    a = _app()
    enemy = a.kb.get_enemy_by_id(enemy_id)
    if not enemy:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Enemy '{enemy_id}' not found.",
        }, status_code=404)
    progress = a._get_progress()
    encounter_stats = {}
    if progress:
        for enc_id, stats in progress.encounter_stats.items():
            if enemy_id.split(".")[-1].lower() in enc_id.lower():
                encounter_stats = stats
                break
        enemy_fight_stats = progress.enemy_stats.get(enemy_id, {})
        if not encounter_stats:
            encounter_stats = enemy_fight_stats
    community_tips = a.kb.get_community_tips(enemy.name)
    counter_cards = a.kb.get_counter_cards(enemy)
    return a.templates.TemplateResponse(request, "enemy_detail.html", {
        "enemy": enemy, "encounter_stats": encounter_stats, "kb": a.kb,
        "community_tips": community_tips, "counter_cards": counter_cards,
    })


@router.get("/events", response_class=HTMLResponse)
async def events(request: Request, act: str = None):
    a = _app()
    event_list = a.kb.events
    if act:
        event_list = [e for e in event_list if act in e.act]
    return a.templates.TemplateResponse(request, "events.html", {
        "events": event_list, "selected_act": act, "total_events": len(a.kb.events),
    })


@router.get("/strategy/{character}", response_class=HTMLResponse)
async def strategy(request: Request, character: str):
    a = _app()
    strat = a.kb.get_strategy(character)
    if not strat:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"No strategy found for '{character}'.",
        }, status_code=404)
    cards_list = a.kb.get_cards(character=character)
    return a.templates.TemplateResponse(request, "strategy.html", {
        "strategy": strat, "cards": cards_list, "characters": CHARACTERS,
    })


@router.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, character: str = None, result: str = None):
    a = _app()
    run_list = a._get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    total = len(run_list)
    wins = sum(1 for r in run_list if r.win)
    return a.templates.TemplateResponse(request, "runs.html", {
        "runs": filtered, "kb": a.kb, "characters": CHARACTERS,
        "selected_character": character, "selected_result": result,
        "total_runs": total, "total_wins": wins,
    })


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str):
    from sts2.analytics import analyze_run
    a = _app()
    run = a._get_run_by_id(run_id)
    if not run:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Run '{run_id}' not found.",
        }, status_code=404)
    run_analysis = analyze_run(run)
    return a.templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "kb": a.kb, "run_analysis": run_analysis,
    })


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    a = _app()
    stats = a._get_analytics()
    return a.templates.TemplateResponse(request, "analytics.html", {
        "stats": stats, "kb": a.kb,
    })


@router.get("/community", response_class=HTMLResponse)
async def community(request: Request):
    a = _app()
    meta_posts = a.kb.meta_posts
    tier_cards: dict[str, list] = {}
    for card in a.kb.cards:
        if card.tier and card.tier in ("S", "A", "B", "C", "D", "F"):
            tier_cards.setdefault(card.tier, []).append(card)
    return a.templates.TemplateResponse(request, "community.html", {
        "meta_posts": meta_posts, "tier_cards": tier_cards,
    })


@router.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    a = _app()
    return a.templates.TemplateResponse(request, "guide.html", {})


@router.get("/live", response_class=HTMLResponse)
async def live_run(request: Request, player: int = Query(0, ge=0, le=3)):
    a = _app()
    run = get_current_run(player_index=player)
    analysis = None
    pick_suggestions = []
    if run.active and run.deck:
        analysis = a.kb.analyze_deck(run.deck)
        # Generate pick suggestions: cards that would complete archetypes or fill gaps
        if analysis and analysis.get("detected_archetypes"):
            for arch in analysis["detected_archetypes"][:1]:
                for missing_name in arch.get("missing_key_cards", [])[:4]:
                    pick_suggestions.append({
                        "name": missing_name,
                        "reason": f"Completes {arch['name']} archetype",
                    })
        # Add suggestions from weaknesses
        deck_keywords = set()
        for card_id in run.deck:
            card = a.kb.get_card_by_id(card_id)
            if card:
                deck_keywords.update(card.keywords)
        if "Block" not in deck_keywords and "Dexterity" not in deck_keywords:
            pick_suggestions.append({
                "name": "Any Block card",
                "reason": "No Block generation — vulnerable to damage",
            })
        # Add analytics-based suggestions
        analytics = a._get_analytics()
        top_cards = analytics.get("card_rankings", [])[:10]
        deck_set = set(run.deck)
        for cr in top_cards:
            if cr["id"] not in deck_set and cr["win_rate"] >= 60:
                card = a.kb.get_card_by_id(cr["id"])
                if card and card.character in (run.character, "Colorless"):
                    pick_suggestions.append({
                        "name": card.name,
                        "reason": f"{cr['win_rate']}% win rate across your runs",
                    })
                    if len(pick_suggestions) >= 6:
                        break
    return a.templates.TemplateResponse(request, "live.html", {
        "run": run, "analysis": analysis, "kb": a.kb,
        "selected_player": player, "total_players": run.total_players,
        "pick_suggestions": pick_suggestions[:6],
    })


@router.get("/deck", response_class=HTMLResponse)
async def deck_analyzer(request: Request):
    a = _app()
    return a.templates.TemplateResponse(request, "deck.html", {
        "cards": a.kb.cards, "analysis": None, "csrf_token": a.generate_csrf_token(),
    })


_MAX_DECK_SIZE = 100


@router.post("/deck/analyze", response_class=HTMLResponse)
async def analyze_deck(request: Request):
    a = _app()
    form = await request.form()
    token = form.get("csrf_token", "")
    if not a.validate_csrf_token(token):
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 403,
            "error_message": "Invalid form submission. Please go back and try again.",
        }, status_code=403)
    card_ids = form.getlist("card_ids")[:_MAX_DECK_SIZE]
    if not card_ids:
        return a.templates.TemplateResponse(request, "deck.html", {
            "cards": a.kb.cards, "analysis": {"error": "No cards selected"},
            "selected_ids": [], "csrf_token": a.generate_csrf_token(),
        })
    analysis = a.kb.analyze_deck(card_ids)
    return a.templates.TemplateResponse(request, "deck.html", {
        "cards": a.kb.cards, "analysis": analysis, "selected_ids": card_ids,
        "kb": a.kb, "csrf_token": a.generate_csrf_token(),
    })


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@router.get("/api/analytics")
async def api_analytics():
    return _app()._get_analytics()


@router.get("/api/live")
async def api_live_run(player: int = Query(0, ge=0, le=3)):
    run = get_current_run(player_index=player)
    return run.model_dump()


# SSE connection tracking — atomic counter (safe in single-threaded asyncio)
_SSE_MAX_CONNECTIONS = 10
_SSE_IDLE_TIMEOUT = 300.0
_sse_active = 0


@router.get("/api/live/stream")
async def live_stream(player: int = Query(0, ge=0, le=3)):
    global _sse_active
    if _sse_active >= _SSE_MAX_CONNECTIONS:
        return PlainTextResponse("Too many live connections. Close another tab.",
                                 status_code=429)

    async def event_generator():
        global _sse_active
        _sse_active += 1
        try:
            last_hash = ""
            idle_since = time.monotonic()
            while True:
                run = await asyncio.to_thread(get_current_run, player_index=player)
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
            _sse_active -= 1

    return StreamingResponse(event_generator(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})


@router.post("/api/reload")
async def reload_data(request: Request):
    a = _app()
    token = request.headers.get("X-Admin-Token", "")
    if not token or not secrets.compare_digest(token, a._ADMIN_TOKEN):
        return PlainTextResponse("Unauthorized.", status_code=403)
    from sts2.knowledge import KnowledgeBase
    new_kb = KnowledgeBase()
    a.kb = new_kb
    return {"status": "ok", "cards": len(a.kb.cards), "relics": len(a.kb.relics),
            "potions": len(a.kb.potions), "enemies": len(a.kb.enemies)}


@router.get("/api/cards/{card_id}")
async def api_card(card_id: str):
    a = _app()
    card = a.kb.get_card_by_id(card_id)
    if not card:
        return PlainTextResponse("Card not found.", status_code=404)
    progress = a._get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    return {**card.model_dump(), "stats": card_stats}


@router.get("/api/runs")
async def api_runs(character: str = None, result: str = None):
    a = _app()
    run_list = a._get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    return [r.model_dump() for r in filtered]


@router.get("/api/search")
async def api_search(q: str = Query("", max_length=200)):
    a = _app()
    results = a.kb.search(q)
    return {
        "query": q,
        "cards": [c.model_dump() for c in results["cards"]],
        "relics": [r.model_dump() for r in results["relics"]],
        "potions": [p.model_dump() for p in results["potions"]],
        "enemies": [e.model_dump() for e in results["enemies"]],
        "events": [e.model_dump() for e in results["events"]],
        "suggestions": results.get("suggestions", []),
    }
