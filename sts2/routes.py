"""Route handlers for Spirescope."""
import asyncio
import hashlib
import json
import math
import re
import secrets
import time
from xml.sax.saxutils import escape as xml_escape
from fastapi import APIRouter, File, Form, Path, Request, Query, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from sts2.config import CHARACTERS
from sts2.saves import get_current_run
from sts2.models import CurrentRun

router = APIRouter()


async def _get_live_run(player: int = 0) -> CurrentRun:
    """Get the best available live run data.

    Priority: save file (has HP) > log parser (has deck/floor/gold).
    Merges log data into save data when both are available.
    """
    run = await asyncio.to_thread(get_current_run, player_index=player)
    if run.active:
        return run  # Save file has full data including HP

    # No save file — check the log parser for live state
    a = _app()
    log_state = getattr(a, '_log_run_state', None) if hasattr(a, '_log_run_state') else None
    # Access the module-level variable from app
    from sts2.app import _log_run_state
    if _log_run_state and _log_run_state.get("active"):
        return CurrentRun(**_log_run_state)

    return run  # No active run from either source


def _app():
    """Lazy import to access app.py shared state (kb, templates, caches).

    Routes import app → app imports routes, so we break the cycle by deferring.
    Each route calls a = _app() then uses a.kb, a.templates, await a._get_progress(), etc.
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
            "/deck", "/live", "/runs", "/analytics", "/collections", "/community", "/guide"]
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
    progress = await a._get_progress()
    runs = await a._get_runs()
    undiscovered = []
    if progress and progress.discovered_cards:
        undiscovered = a.kb.get_undiscovered_cards(progress.discovered_cards)[:12]
    return a.templates.TemplateResponse(request, "index.html", {
        "characters": CHARACTERS, "progress": progress, "recent_runs": runs[:5],
        "kb": a.kb, "total_cards": len(a.kb.cards), "total_relics": len(a.kb.relics),
        "total_potions": len(a.kb.potions), "total_enemies": len(a.kb.enemies),
        "last_updated": await asyncio.to_thread(get_last_updated),
        "data_status": a.kb.get_data_status(skip_last_updated=True),
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
    progress = await a._get_progress()
    card_stats = progress.card_stats if progress else {}

    # Sort options
    if sort == "winrate":
        analytics = await a._get_analytics()
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
async def card_detail(request: Request, card_id: str = Path(max_length=200)):
    a = _app()
    card = a.kb.get_card_by_id(card_id)
    if not card:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Card '{card_id[:100]}' not found.",
        }, status_code=404)
    synergies = a.kb.find_synergies(card_id)
    strategy = a.kb.get_strategy(card.character)
    progress = await a._get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    runs_with_card = [r for r in await a._get_runs() if card_id in r.deck]
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


@router.get("/relics/{relic_id}", response_class=HTMLResponse)
async def relic_detail(request: Request, relic_id: str = Path(max_length=200)):
    a = _app()
    relic = a.kb.get_relic_by_id(relic_id)
    if not relic:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Relic '{relic_id[:100]}' not found.",
        }, status_code=404)
    relic_runs = [r for r in await a._get_runs() if relic_id in r.relics]
    community_tips = a.kb.get_community_tips(relic.name)
    # Relic synergy — other relics commonly found in winning runs with this one
    relic_synergies = []
    analytics = await a._get_analytics()
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
    analytics = await a._get_analytics()
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
async def enemy_detail(request: Request, enemy_id: str = Path(max_length=200)):
    a = _app()
    enemy = a.kb.get_enemy_by_id(enemy_id)
    if not enemy:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Enemy '{enemy_id[:100]}' not found.",
        }, status_code=404)
    progress = await a._get_progress()
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
async def events(request: Request, act: str = Query(None, max_length=50)):
    a = _app()
    event_list = a.kb.events
    if act:
        event_list = [e for e in event_list if act in e.act]
    return a.templates.TemplateResponse(request, "events.html", {
        "events": event_list, "selected_act": act, "total_events": len(a.kb.events),
    })


@router.get("/strategy/{character}", response_class=HTMLResponse)
async def strategy(request: Request, character: str = Path(max_length=50)):
    a = _app()
    strat = a.kb.get_strategy(character)
    if not strat:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"No strategy found for '{character[:100]}'.",
        }, status_code=404)
    cards_list = a.kb.get_cards(character=character)
    return a.templates.TemplateResponse(request, "strategy.html", {
        "strategy": strat, "cards": cards_list, "characters": CHARACTERS,
    })


@router.get("/runs", response_class=HTMLResponse)
async def runs(request: Request, character: str = Query(None, max_length=50),
               result: str = Query(None, max_length=10),
               ascension: int = Query(None, ge=0, le=20)):
    a = _app()
    run_list = await a._get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    if ascension is not None:
        filtered = [r for r in filtered if r.ascension == ascension]
    total = len(run_list)
    wins = sum(1 for r in run_list if r.win)
    # Collect ascension levels present in runs for the filter dropdown
    ascension_levels = sorted({r.ascension for r in run_list})
    return a.templates.TemplateResponse(request, "runs.html", {
        "runs": filtered, "kb": a.kb, "characters": CHARACTERS,
        "selected_character": character, "selected_result": result,
        "selected_ascension": ascension, "ascension_levels": ascension_levels,
        "total_runs": total, "total_wins": wins, "csrf_token": a.generate_csrf_token(),
    })


@router.get("/runs/{run_id}", response_class=HTMLResponse)
async def run_detail(request: Request, run_id: str = Path(max_length=200)):
    from sts2.analytics import analyze_run
    a = _app()
    run = await a._get_run_by_id(run_id)
    if not run:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Run '{run_id[:100]}' not found.",
        }, status_code=404)
    run_analysis = analyze_run(run)
    return a.templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "kb": a.kb, "run_analysis": run_analysis,
    })


@router.get("/runs/{run_id}/export")
async def export_run(run_id: str = Path(max_length=200)):
    a = _app()
    run = await a._get_run_by_id(run_id)
    if not run:
        return PlainTextResponse("Run not found.", status_code=404)
    from sts2.config import VERSION
    export_data = json.dumps({"spirescope_version": VERSION, "format_version": 1,
                              "run": run.model_dump()}, indent=2)
    safe_id = re.sub(r'[^\w\-.]', '_', run.id)
    return PlainTextResponse(
        export_data, media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="spirescope_{safe_id}.json"'})


@router.post("/runs/import", response_class=HTMLResponse)
async def import_run(request: Request, file: UploadFile = File(...),
                     csrf_token: str = Form("")):
    from sts2.analytics import analyze_run
    from sts2.models import RunHistory
    a = _app()
    if not a.validate_csrf_token(csrf_token):
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 403,
            "error_message": "Invalid form submission. Please go back and try again.",
        }, status_code=403)
    contents = await file.read(1_048_577)
    if len(contents) > 1_048_576:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 413,
            "error_message": "File too large (max 1 MB).",
        }, status_code=413)
    try:
        data = json.loads(contents)
        if data.get("format_version") != 1:
            return a.templates.TemplateResponse(request, "error.html", {
                "error_code": 400,
                "error_message": "Unsupported format version. Expected format_version: 1.",
            }, status_code=400)
        if "run" not in data:
            return a.templates.TemplateResponse(request, "error.html", {
                "error_code": 400,
                "error_message": "Invalid file: missing 'run' key.",
            }, status_code=400)
        run = RunHistory(**data["run"])
    except (json.JSONDecodeError, ValidationError, KeyError, RecursionError) as exc:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 400,
            "error_message": f"Invalid run file: {str(exc)[:200]}",
        }, status_code=400)
    run_analysis = analyze_run(run)
    return a.templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "run_analysis": run_analysis, "kb": a.kb, "imported": True,
    })


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request):
    a = _app()
    stats = await a._get_analytics()
    return a.templates.TemplateResponse(request, "analytics.html", {
        "stats": stats, "kb": a.kb,
    })


@router.get("/community", response_class=HTMLResponse)
async def community(request: Request):
    from sts2.aggregate import load_aggregate
    a = _app()
    meta_posts = a.kb.meta_posts
    tier_cards: dict[str, list] = {}
    for card in a.kb.cards:
        if card.tier and card.tier in ("S", "A", "B", "C", "D", "F"):
            tier_cards.setdefault(card.tier, []).append(card)
    aggregate = load_aggregate()
    return a.templates.TemplateResponse(request, "community.html", {
        "meta_posts": meta_posts, "tier_cards": tier_cards,
        "aggregate": aggregate, "kb": a.kb,
    })


@router.get("/collections", response_class=HTMLResponse)
async def collections(request: Request):
    a = _app()
    progress = await a._get_progress()

    # Totals from knowledge base (exclude Status/Curse cards)
    all_cards = [c for c in a.kb.cards if c.character not in ("Status", "Curse")]
    total_cards = len(all_cards)
    total_relics = len(a.kb.relics)
    total_potions = len(a.kb.potions)
    total_events = len(a.kb.events)

    if progress:
        card_ids = set(progress.discovered_cards)
        relic_ids = set(progress.discovered_relics)
        potion_ids = set(progress.discovered_potions)
        event_ids = set(progress.discovered_events)

        disc_cards = len(card_ids & {c.id for c in all_cards})
        disc_relics = len(relic_ids & {r.id for r in a.kb.relics})
        disc_potions = len(potion_ids & {p.id for p in a.kb.potions})
        disc_events = len(event_ids & {e.id for e in a.kb.events})

        total_all = total_cards + total_relics + total_potions + total_events
        disc_all = disc_cards + disc_relics + disc_potions + disc_events
        overall_pct = round((disc_all / total_all) * 100) if total_all > 0 else 0

        # Build discovered/undiscovered object lists
        discovered_card_objs = [c for c in all_cards if c.id in card_ids]
        undiscovered_cards = [c for c in all_cards if c.id not in card_ids]
        discovered_relic_objs = [r for r in a.kb.relics if r.id in relic_ids]
        undiscovered_relic_objs = [r for r in a.kb.relics if r.id not in relic_ids]
        discovered_potion_objs = [p for p in a.kb.potions if p.id in potion_ids]
        undiscovered_potion_objs = [p for p in a.kb.potions if p.id not in potion_ids]
        discovered_event_objs = [e for e in a.kb.events if e.id in event_ids]
        undiscovered_event_objs = [e for e in a.kb.events if e.id not in event_ids]
    else:
        card_ids = relic_ids = potion_ids = event_ids = set()
        disc_cards = disc_relics = disc_potions = disc_events = 0
        overall_pct = 0
        discovered_card_objs = undiscovered_cards = []
        discovered_relic_objs = undiscovered_relic_objs = []
        discovered_potion_objs = undiscovered_potion_objs = []
        discovered_event_objs = undiscovered_event_objs = []

    return a.templates.TemplateResponse(request, "collections.html", {
        "progress": progress, "characters": CHARACTERS,
        "discovered_cards": disc_cards, "total_cards": total_cards,
        "discovered_relics": disc_relics, "total_relics": total_relics,
        "discovered_potions": disc_potions, "total_potions": total_potions,
        "discovered_events": disc_events, "total_events": total_events,
        "overall_pct": overall_pct,
        "all_cards": all_cards, "all_events": a.kb.events,
        "card_ids": card_ids, "relic_ids": relic_ids,
        "potion_ids": potion_ids, "event_ids": event_ids,
        "discovered_card_objs": discovered_card_objs, "undiscovered_cards": undiscovered_cards,
        "discovered_relic_objs": discovered_relic_objs, "undiscovered_relic_objs": undiscovered_relic_objs,
        "discovered_potion_objs": discovered_potion_objs, "undiscovered_potion_objs": undiscovered_potion_objs,
        "discovered_event_objs": discovered_event_objs, "undiscovered_event_objs": undiscovered_event_objs,
    })


@router.get("/guide", response_class=HTMLResponse)
async def guide(request: Request):
    a = _app()
    return a.templates.TemplateResponse(request, "guide.html", {})


@router.get("/live", response_class=HTMLResponse)
async def live_run(request: Request, player: int = Query(0, ge=0, le=3)):
    import logging
    _log = logging.getLogger(__name__)
    a = _app()
    run = await _get_live_run(player)
    analysis = None
    pick_suggestions = []
    danger_level = None
    danger_pct = 0
    counter_cards = []
    last_enemy_name = ""
    synergy_hints = []

    if run.active and run.deck:
        try:
            analysis = a.kb.analyze_deck(run.deck)
        except Exception:
            _log.debug("Coaching: analyze_deck failed", exc_info=True)

        # Pick suggestions from archetypes
        try:
            if analysis and analysis.get("detected_archetypes"):
                for arch in analysis["detected_archetypes"][:1]:
                    for missing_name in arch.get("missing_key_cards", [])[:4]:
                        pick_suggestions.append({
                            "name": missing_name,
                            "reason": f"Completes {arch['name']} archetype",
                        })
        except Exception:
            _log.debug("Coaching: archetype suggestions failed", exc_info=True)

        # Pick suggestions from weakness keywords
        try:
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
        except Exception:
            _log.debug("Coaching: weakness suggestions failed", exc_info=True)

        # Analytics-based suggestions
        try:
            live_analytics = await a._get_analytics()
            top_cards = live_analytics.get("card_rankings", [])[:10]
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
        except Exception:
            _log.debug("Coaching: analytics suggestions failed", exc_info=True)

        # Danger zone alerts
        try:
            if run.max_hp > 0:
                hp_pct = run.current_hp / run.max_hp
                danger_pct = int(hp_pct * 100)
                if hp_pct < 0.2:
                    danger_level = "critical"
                elif hp_pct < 0.4:
                    danger_level = "warning"
        except Exception:
            _log.debug("Coaching: danger zone failed", exc_info=True)

        # Counter-card suggestions (based on last combat encounter)
        try:
            if run.floors:
                deck_set = set(run.deck)
                for floor in reversed(run.floors):
                    enemy = a.kb.get_enemy_by_id(floor.encounter) if floor.encounter else None
                    if enemy:
                        raw_counters = a.kb.get_counter_cards(enemy, limit=8)
                        filtered = [c for c in raw_counters
                                    if c.character in (run.character, "Colorless")
                                    and c.id not in deck_set]
                        counter_cards = filtered[:4]
                        last_enemy_name = enemy.name
                        break
        except Exception:
            _log.debug("Coaching: counter-cards failed", exc_info=True)

        # Synergy hints (based on last card picked)
        try:
            if run.floors:
                deck_set = set(run.deck)
                for floor in reversed(run.floors):
                    if floor.card_picked:
                        synergy_list = a.kb.find_synergies(floor.card_picked)
                        picked_card = a.kb.get_card_by_id(floor.card_picked)
                        picked_name = picked_card.name if picked_card else floor.card_picked
                        synergy_hints = [{"card_name": s.name, "picked_name": picked_name}
                                         for s in synergy_list if s.id not in deck_set][:4]
                        break
        except Exception:
            _log.debug("Coaching: synergy hints failed", exc_info=True)

    return a.templates.TemplateResponse(request, "live.html", {
        "run": run, "analysis": analysis, "kb": a.kb,
        "selected_player": player, "total_players": run.total_players,
        "pick_suggestions": pick_suggestions[:6],
        "danger_level": danger_level, "danger_pct": danger_pct,
        "counter_cards": counter_cards, "last_enemy_name": last_enemy_name,
        "synergy_hints": synergy_hints,
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
    return await _app()._get_analytics()


@router.get("/api/live")
async def api_live_run(player: int = Query(0, ge=0, le=3)):
    run = await _get_live_run(player)
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
                run = await _get_live_run(player)
                data = run.model_dump()
                data_json = json.dumps(data, sort_keys=True)
                current_hash = hashlib.sha1(data_json.encode(), usedforsecurity=False).hexdigest()
                if current_hash != last_hash:
                    last_hash = current_hash
                    idle_since = time.monotonic()
                    yield f"data: {data_json}\n\n"
                elif time.monotonic() - idle_since > _SSE_IDLE_TIMEOUT:
                    yield f"event: timeout\ndata: {{}}\n\n"
                    return
                # Wake instantly on file change, or poll every 3s as fallback
                try:
                    a = _app()
                    await asyncio.wait_for(a._save_changed_event.wait(), timeout=3.0)
                except asyncio.TimeoutError:
                    pass
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
    new_kb = await asyncio.to_thread(KnowledgeBase)
    a.kb = new_kb
    return {"status": "ok", "cards": len(a.kb.cards), "relics": len(a.kb.relics),
            "potions": len(a.kb.potions), "enemies": len(a.kb.enemies)}


@router.get("/api/cards/{card_id}")
async def api_card(card_id: str = Path(max_length=200)):
    a = _app()
    card = a.kb.get_card_by_id(card_id)
    if not card:
        return PlainTextResponse("Card not found.", status_code=404)
    progress = await a._get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    return {**card.model_dump(), "stats": card_stats}


def _csv_safe(v: str) -> str:
    """Escape CSV injection characters."""
    if v and v[0] in "=+-@\t\r":
        return "'" + v
    return v


@router.get("/api/runs")
async def api_runs(character: str = Query(None, max_length=50), result: str = Query(None, max_length=10),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    a = _app()
    run_list = await a._get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    total = len(filtered)
    page = filtered[offset:offset + limit]
    return {"total": total, "offset": offset, "limit": limit,
            "runs": [r.model_dump() for r in page]}


@router.get("/api/export/runs")
async def api_export_runs_csv(character: str = Query(None, max_length=50),
                               result: str = Query(None, max_length=10)):
    a = _app()
    run_list = await a._get_runs()
    filtered = run_list
    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]

    import csv
    import io
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "character", "win", "ascension", "seed", "killed_by",
                      "deck_size", "relic_count", "floor_count", "run_time"])
    for r in filtered:
        writer.writerow([
            _csv_safe(r.id), _csv_safe(r.character), r.win, r.ascension,
            _csv_safe(r.seed), _csv_safe(r.killed_by),
            len(r.deck), len(r.relics), len(r.floors), r.run_time,
        ])
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="spirescope_runs.csv"'})


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


@router.get("/api/export/stats")
async def api_export_stats():
    from sts2.aggregate import compute_aggregate_stats
    a = _app()
    runs = await a._get_runs()
    stats = compute_aggregate_stats(runs)
    return stats


@router.post("/api/reset/stats")
async def api_reset_stats(request: Request):
    a = _app()
    token = request.headers.get("X-Admin-Token", "")
    if not token or not secrets.compare_digest(token, a._ADMIN_TOKEN):
        return PlainTextResponse("Unauthorized.", status_code=403)
    from sts2.aggregate import reset_aggregate
    deleted = reset_aggregate()
    return {"status": "ok", "deleted": deleted}


@router.post("/api/import/stats")
async def api_import_stats(request: Request, file: UploadFile = File(...),
                           csrf_token: str = Form("")):
    from sts2.aggregate import load_aggregate, merge_aggregate, save_aggregate
    a = _app()
    if not a.validate_csrf_token(csrf_token):
        return PlainTextResponse("Invalid CSRF token.", status_code=403)
    contents = await file.read(512_001)
    if len(contents) > 512_000:
        return PlainTextResponse("File too large (max 500 KB).", status_code=413)
    try:
        imported = json.loads(contents)
        if not isinstance(imported, dict) or "run_count" not in imported:
            return PlainTextResponse("Invalid aggregate file.", status_code=400)
    except (json.JSONDecodeError, RecursionError):
        return PlainTextResponse("Invalid JSON.", status_code=400)
    existing = load_aggregate()
    merged = merge_aggregate(existing, imported)
    save_aggregate(merged)
    return {"status": "ok", "run_count": merged.get("run_count", 0)}
