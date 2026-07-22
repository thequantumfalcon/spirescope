"""Route handlers for Spirescope."""
import asyncio
import hashlib
import ipaddress
import json
import math
import re
import secrets
import time
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape as xml_escape

from fastapi import APIRouter, File, Form, Path, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import ValidationError
from starlette.responses import StreamingResponse

from sts2.config import CHARACTERS
from sts2.models import CurrentRun
from sts2.saves import get_current_run

router = APIRouter()


# ---------------------------------------------------------------------------
# Run filtering helpers
# ---------------------------------------------------------------------------

def _parse_date(value: str | None) -> date | None:
    """Safely parse a YYYY-MM-DD string. Returns None on invalid input."""
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def _resolve_preset(preset: str | None) -> str | None:
    """Convert a preset like '7d' into a from-date string. Returns None if invalid."""
    if preset in ("7d", "30d", "90d"):
        days = {"7d": 7, "30d": 30, "90d": 90}[preset]
        return (date.today() - timedelta(days=days)).isoformat()
    return None


def _filter_runs(runs: list, *, version: str | None = None,
                 date_from: str | None = None, date_to: str | None = None,
                 origin: str | None = None) -> list:
    """Filter runs by game version, date range, and/or save-tree origin.

    Runs with timestamp=0 (unknown) are excluded by any date filter.
    """
    if version:
        runs = [r for r in runs if r.build_id == version]
    if origin in ("vanilla", "modded"):
        runs = [r for r in runs if r.origin == origin]
    from_date = _parse_date(date_from)
    if from_date:
        from_ts = int(datetime(from_date.year, from_date.month, from_date.day,
                               tzinfo=timezone.utc).timestamp())
        runs = [r for r in runs if r.timestamp >= from_ts]
    to_date = _parse_date(date_to)
    if to_date:
        to_ts = int(datetime(to_date.year, to_date.month, to_date.day,
                             23, 59, 59, tzinfo=timezone.utc).timestamp())
        runs = [r for r in runs if r.timestamp <= to_ts]
    return runs


async def _get_live_run(player: int = 0) -> CurrentRun:
    """Get the best available live run data, merging save + log sources.

    Save provides: HP, relics, floors, deck_upgrades, run_time, events_seen.
    Log provides: fresher deck, gold, potions, act, floor (updates mid-combat).
    When both are active, merge log's fresher fields into save's complete state.
    """
    a = _app()
    await a._poll_game_log_once()
    run = await asyncio.to_thread(get_current_run, player_index=player)

    from sts2.app import _log_run_state
    log_active = _log_run_state and _log_run_state.get("active")

    if run.active and log_active:
        # Both sources — merge log's fresher data into save's complete state
        log = _log_run_state
        merged = run.model_dump()
        if log.get("deck"):
            merged["deck"] = log["deck"]
            merged["deck_upgrades"] = [False] * len(log["deck"])
        if log.get("gold", 0) > 0:
            merged["gold"] = log["gold"]
        if log.get("potions"):
            merged["potions"] = log["potions"]
        if log.get("floor", 0) > 0:
            merged["floor"] = log["floor"]
        if log.get("act", 1) > merged.get("act", 1):
            merged["act"] = log["act"]
        if log.get("encounters_won"):
            merged["encounters_won"] = log["encounters_won"]
        return CurrentRun(**merged)

    if run.active:
        return run  # Save file only

    if log_active:
        return CurrentRun(**_log_run_state)  # Log parser only

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


def _is_loopback_client(request: Request) -> bool:
    """Only trust the actual client address, never a spoofable Referer header."""
    host = request.client.host if request.client else ""
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host.lower() == "localhost"


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
    # Compute aggregate current streak across all characters
    current_streak = 0
    streak_character = ""
    if progress and progress.character_stats:
        for char, cs in progress.character_stats.items():
            s = cs.get("current_streak", 0)
            if s > current_streak:
                current_streak = s
                streak_character = char

    # Next epochs to unlock
    next_epochs = []
    if progress and progress.epochs:
        obtained_ids = {e["id"] for e in progress.epochs if e.get("state") == "revealed"}
        for ep in a.kb.epochs:
            if ep.id not in obtained_ids:
                next_epochs.append({"name": ep.name, "requirement": ep.requirement,
                                    "unlocks": ep.unlocks[:3]})
            if len(next_epochs) >= 3:
                break

    last_updated = await asyncio.to_thread(get_last_updated)
    # Stale-data hint: surface a badge when the wiki data is >30 days old so
    # players know to run `python -m sts2 update`. Does NOT auto-network on
    # launch — auto-fetch would break the local-first, no-telemetry promise.
    data_age_days = None
    if last_updated:
        try:
            parsed = datetime.fromisoformat(last_updated)
            data_age_days = (datetime.now(timezone.utc) - parsed).days
        except (ValueError, TypeError):
            pass
    return a.templates.TemplateResponse(request, "index.html", {
        "characters": CHARACTERS, "progress": progress, "recent_runs": runs[:5],
        "current_streak": current_streak, "streak_character": streak_character,
        "next_epochs": next_epochs,
        "kb": a.kb, "total_cards": len(a.kb.cards), "total_relics": len(a.kb.relics),
        "total_potions": len(a.kb.potions), "total_enemies": len(a.kb.enemies),
        "last_updated": last_updated, "data_age_days": data_age_days,
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
        # Exact match on enemy_id first; only fall back to suffix-equality so
        # short IDs like "RAT" don't substring-match "BIG_RAT_PACK".
        enemy_suffix = enemy_id.split(".")[-1].lower()
        for enc_id, stats in progress.encounter_stats.items():
            if enc_id.split(".")[-1].lower() == enemy_suffix:
                encounter_stats = stats
                break
        enemy_fight_stats = progress.enemy_stats.get(enemy_id, {})
        if not encounter_stats:
            encounter_stats = enemy_fight_stats
    community_tips = a.kb.get_community_tips(enemy.name)
    counter_cards = a.kb.get_counter_cards(enemy)
    analytics = await a._get_analytics()
    danger = analytics.get("encounter_danger", {}).get(enemy_id, None)
    return a.templates.TemplateResponse(request, "enemy_detail.html", {
        "enemy": enemy, "encounter_stats": encounter_stats, "kb": a.kb,
        "community_tips": community_tips, "counter_cards": counter_cards,
        "danger": danger,
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
               ascension: int = Query(None, ge=0, le=20),
               version: str = Query(None, max_length=100),
               date_from: str = Query(None, alias="from", max_length=10),
               date_to: str = Query(None, alias="to", max_length=10),
               preset: str = Query(None, max_length=10),
               origin: str = Query(None, max_length=10)):
    a = _app()
    run_list = await a._get_runs()

    # Resolve preset into date range
    if preset and preset != "all":
        p_from = _resolve_preset(preset)
        if p_from:
            date_from = p_from
            date_to = None

    # Version/time/origin filters apply before character/result/ascension
    filtered = _filter_runs(run_list, version=version,
                            date_from=date_from, date_to=date_to,
                            origin=origin)

    if character:
        filtered = [r for r in filtered if r.character == character]
    if result == "win":
        filtered = [r for r in filtered if r.win]
    elif result == "loss":
        filtered = [r for r in filtered if not r.win]
    if ascension is not None:
        filtered = [r for r in filtered if r.ascension == ascension]
    total = len(filtered)
    wins = sum(1 for r in filtered if r.win)
    ascension_levels = sorted({r.ascension for r in run_list})
    available_versions = sorted({r.build_id for r in run_list if r.build_id}, reverse=True)
    available_origins = sorted({r.origin for r in run_list})
    selected_preset = preset if preset in ("7d", "30d", "90d", "all") else ""
    return a.templates.TemplateResponse(request, "runs.html", {
        "runs": filtered, "kb": a.kb, "characters": CHARACTERS,
        "selected_character": character, "selected_result": result,
        "selected_ascension": ascension, "ascension_levels": ascension_levels,
        "total_runs": total, "total_wins": wins, "csrf_token": a.generate_csrf_token(),
        "available_versions": available_versions, "selected_version": version,
        "available_origins": available_origins, "selected_origin": origin,
        "selected_from": date_from or "", "selected_to": date_to or "",
        "selected_preset": selected_preset,
    })


@router.get("/runs/compare", response_class=HTMLResponse)
async def compare_runs(request: Request,
                       a_id: str = Query("", alias="a", max_length=200),
                       b_id: str = Query("", alias="b", max_length=200)):
    from collections import Counter

    from sts2.analytics import analyze_run
    a = _app()
    if not a_id or not b_id:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 400, "error_message": "Select two runs to compare.",
        }, status_code=400)
    run_a = await a._get_run_by_id(a_id)
    run_b = await a._get_run_by_id(b_id)
    if not run_a or not run_b:
        missing = a_id if not run_a else b_id
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 404, "error_message": f"Run '{missing[:100]}' not found.",
        }, status_code=404)
    deck_a, deck_b = Counter(run_a.deck), Counter(run_b.deck)
    all_cards = sorted(set(deck_a) | set(deck_b))
    deck_diff = [{"id": c, "name": a.kb.id_to_name(c),
                  "qty_a": deck_a[c], "qty_b": deck_b[c]} for c in all_cards]
    relics_a, relics_b = set(run_a.relics), set(run_b.relics)
    relic_diff = {
        "shared": sorted(relics_a & relics_b),
        "only_a": sorted(relics_a - relics_b),
        "only_b": sorted(relics_b - relics_a),
    }

    def run_stats(r):
        return {"floors": len(r.floors), "deck_size": len(r.deck),
                "relics": len(r.relics),
                "total_damage": sum(f.damage_taken for f in r.floors)}

    # Seed-match rivalry diff: when both runs played the same seed, surface
    # floor-by-floor decision differences (card picks chosen differently, HP
    # divergence). Reuses the existing rivalry module.
    rivalry_diff = None
    if run_a.seed and run_b.seed and run_a.seed == run_b.seed:
        from sts2.rivalry import compare_seed_runs
        result = compare_seed_runs(run_a, run_b, kb=a.kb)
        if "error" not in result:
            rivalry_diff = result
    return a.templates.TemplateResponse(request, "compare.html", {
        "run_a": run_a, "run_b": run_b, "kb": a.kb,
        "analysis_a": analyze_run(run_a, kb=a.kb), "analysis_b": analyze_run(run_b, kb=a.kb),
        "deck_diff": deck_diff, "relic_diff": relic_diff,
        "stats_a": run_stats(run_a), "stats_b": run_stats(run_b),
        "rivalry_diff": rivalry_diff,
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
    run_analysis = analyze_run(run, kb=a.kb)
    archetype = a.kb.classify_archetype(run.deck, run.character)
    autopsy = None
    if not run.win:
        try:
            from sts2.diagnosis import diagnose_run
            all_runs = await a._get_runs()
            autopsy = diagnose_run(run, a.kb, all_runs)
        except ImportError:
            pass
        except Exception:
            pass
    # Tamper-evidence: SHA-256 Merkle chain over every floor decision.
    # Same chain = same run, byte-for-byte. Shared hash lets two players
    # confirm they're talking about the identical run.
    from sts2.integrity import compute_merkle_root
    integrity_hash = compute_merkle_root(run)
    # Cascade map: per-pick downstream impact (Δ damage, Δ turns vs pre-pick).
    # Helps identify which pick changed the run's trajectory.
    from sts2.cascade import trace_all_picks
    try:
        cascade = trace_all_picks(run, a.kb)
    except Exception:
        cascade = []
    # Archetype drift: reconstruct deck floor-by-floor, classify per snapshot,
    # detect dominant-archetype shift between early and late game.
    from sts2.drift import compute_archetype_drift, detect_drift_alert
    try:
        drift_trajectory = compute_archetype_drift(run, a.kb)
        drift_alert = detect_drift_alert(drift_trajectory)
    except Exception:
        drift_trajectory = []
        drift_alert = None
    return a.templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "kb": a.kb, "run_analysis": run_analysis,
        "archetype": archetype, "autopsy": autopsy,
        "integrity_hash": integrity_hash,
        "cascade": cascade,
        "drift_trajectory": drift_trajectory,
        "drift_alert": drift_alert,
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


@router.get("/runs/{run_id}/export/html")
async def export_run_html(run_id: str = Path(max_length=200)):
    from sts2.analytics import analyze_run
    from sts2.config import STATIC_DIR, VERSION
    a = _app()
    run = await a._get_run_by_id(run_id)
    if not run:
        return PlainTextResponse("Run not found.", status_code=404)
    run_analysis = analyze_run(run, kb=a.kb)
    css_path = STATIC_DIR / "style.css"
    css_content = css_path.read_text(encoding="utf-8") if css_path.exists() else ""
    html = a.templates.env.get_template("run_export.html").render(
        run=run, kb=a.kb, run_analysis=run_analysis,
        css_content=css_content, version=VERSION,
    )
    safe_id = re.sub(r'[^\w\-.]', '_', run.id)
    return HTMLResponse(
        content=html,
        headers={"Content-Disposition": f'attachment; filename="spirescope_{safe_id}.html"'},
    )


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
    except (json.JSONDecodeError, ValidationError, KeyError, RecursionError):
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 400,
            "error_message": "Invalid run file format.",
        }, status_code=400)
    # Per-field guard: a 1 MB byte cap still permits ~100k tiny floor entries,
    # which would DoS the analyzer + template render. STS2 runs are 50-60 floors.
    if len(run.floors) > 500 or len(run.deck) > 200 or len(run.relics) > 100:
        return a.templates.TemplateResponse(request, "error.html", {
            "error_code": 400,
            "error_message": "Run file exceeds reasonable size (floors/deck/relics).",
        }, status_code=400)
    # Per-floor cap: 500 floors x 1000-item cards_offered would still DoS.
    for f in run.floors:
        if (len(getattr(f, "cards_offered", []) or []) > 50 or
                len(getattr(f, "monsters", []) or []) > 20 or
                len(getattr(f, "potions_used", []) or []) > 20 or
                len(getattr(f, "potions_gained", []) or []) > 20):
            return a.templates.TemplateResponse(request, "error.html", {
                "error_code": 400,
                "error_message": "Run file has unreasonable per-floor list sizes.",
            }, status_code=400)
    run_analysis = analyze_run(run, kb=a.kb)
    return a.templates.TemplateResponse(request, "run_detail.html", {
        "run": run, "run_analysis": run_analysis, "kb": a.kb, "imported": True,
    })


@router.get("/analytics", response_class=HTMLResponse)
async def analytics(request: Request,
                    ascension: int = Query(None, ge=0, le=20),
                    version: str = Query(None, max_length=100),
                    date_from: str = Query(None, alias="from", max_length=10),
                    date_to: str = Query(None, alias="to", max_length=10),
                    preset: str = Query(None, max_length=10),
                    origin: str = Query(None, max_length=10)):
    from sts2.analytics import analyze_run_patterns, compute_analytics, compute_boss_matchups
    a = _app()
    all_runs = await a._get_runs()
    ascension_levels = sorted({r.ascension for r in all_runs})
    available_versions = sorted({r.build_id for r in all_runs if r.build_id}, reverse=True)
    available_origins = sorted({r.origin for r in all_runs})

    # Resolve preset into date range
    if preset and preset != "all":
        p_from = _resolve_preset(preset)
        if p_from:
            date_from = p_from
            date_to = None

    has_filters = version or date_from or date_to or origin

    if has_filters:
        # Bypass cache — compute analytics on filtered subset
        filtered = _filter_runs(all_runs, version=version,
                                date_from=date_from, date_to=date_to,
                                origin=origin)
        if ascension is not None:
            filtered = [r for r in filtered if r.ascension == ascension]
        progress = await a._get_progress()
        card_stats = progress.card_stats if progress else {}
        stats = await asyncio.to_thread(compute_analytics, filtered, card_stats, a.kb)
        run_patterns = analyze_run_patterns(filtered, kb=a.kb)
    else:
        stats = await a._get_analytics(ascension=ascension)
        filtered = all_runs
        if ascension is not None:
            filtered = [r for r in filtered if r.ascension == ascension]
        run_patterns = analyze_run_patterns(filtered, kb=a.kb)

    selected_preset = preset if preset in ("7d", "30d", "90d", "all") else ""
    boss_matchups = compute_boss_matchups(filtered, kb=a.kb)
    # Behavior signals: tilt detection (session momentum) + named anti-patterns
    # (The Hoarder, Greedy Builder, Coward, Potion Paralysis). Surfaces here
    # because /analytics is where a player goes to reflect.
    from sts2.behavior import detect_anti_patterns, detect_tilt
    try:
        tilt = detect_tilt(filtered)
        anti_patterns = detect_anti_patterns(filtered)
    except Exception:
        tilt = None
        anti_patterns = []
    return a.templates.TemplateResponse(request, "analytics.html", {
        "stats": stats, "kb": a.kb,
        "selected_ascension": ascension, "ascension_levels": ascension_levels,
        "run_patterns": run_patterns, "boss_matchups": boss_matchups,
        "available_versions": available_versions, "selected_version": version,
        "available_origins": available_origins, "selected_origin": origin,
        "selected_from": date_from or "", "selected_to": date_to or "",
        "selected_preset": selected_preset,
        "tilt": tilt, "anti_patterns": anti_patterns,
    })


@router.get("/records", response_class=HTMLResponse)
async def records(request: Request):
    from sts2.analytics import compute_records
    a = _app()
    runs = await a._get_runs()
    progress = await a._get_progress()
    recs = compute_records(runs, progress)
    return a.templates.TemplateResponse(request, "records.html", {
        "records": recs, "kb": a.kb,
    })


@router.get("/hypothesis", response_class=HTMLResponse)
async def hypothesis_list(request: Request):
    """List + manage Bayesian-style hypotheses tested against run history."""
    from sts2.hypothesis import load_hypotheses, save_hypotheses, update_hypothesis
    a = _app()
    runs = await a._get_runs()
    hyps = load_hypotheses()
    # Re-evaluate all hypotheses fresh against current run history so the page
    # is idempotent and never double-counts.
    for h in hyps.values():
        h["runs_tested"] = 0
        h["runs_matching"] = 0
        h["runs_not_matching"] = 0
        h["wins_matching"] = 0
        h["wins_not_matching"] = 0
        h["verdict"] = "insufficient_data"
        h.pop("effect_size", None)
    save_hypotheses(hyps)
    for run in runs:
        for hyp_id in list(hyps):
            update_hypothesis(hyp_id, run)
    hyps = load_hypotheses()
    return a.templates.TemplateResponse(request, "hypothesis.html", {
        "hypotheses": hyps,
        "csrf_token": a.generate_csrf_token(),
        "characters": CHARACTERS,
    })


@router.post("/hypothesis/create", response_class=HTMLResponse)
async def hypothesis_create(request: Request,
                            csrf_token: str = Form(""),
                            text: str = Form("", max_length=200),
                            condition_type: str = Form(""),
                            param_value: str = Form("", max_length=100)):
    import hashlib
    import time as _t

    from starlette.responses import RedirectResponse

    from sts2.hypothesis import register_hypothesis
    a = _app()
    if not a.validate_csrf_token(csrf_token):
        return PlainTextResponse("Invalid form submission.", status_code=403)
    if not text or condition_type not in ("elite_skip", "deck_size", "card_pick", "character"):
        return PlainTextResponse("Invalid hypothesis.", status_code=400)
    hyp_id = hashlib.sha1(f"{text}{_t.time()}".encode()).hexdigest()[:12]
    params: dict = {}
    if condition_type == "deck_size":
        try:
            params["max_size"] = max(1, min(100, int(param_value or "25")))
        except ValueError:
            params["max_size"] = 25
    elif condition_type == "card_pick":
        params["card_id"] = param_value[:100]
    elif condition_type == "character":
        params["character"] = param_value[:50]
    register_hypothesis(hyp_id, text[:200], condition_type, params)
    return RedirectResponse("/hypothesis", status_code=303)


@router.post("/hypothesis/delete/{hyp_id}", response_class=HTMLResponse)
async def hypothesis_delete(request: Request,
                            hyp_id: str = Path(max_length=64),
                            csrf_token: str = Form("")):
    from starlette.responses import RedirectResponse

    from sts2.hypothesis import load_hypotheses, save_hypotheses
    a = _app()
    if not a.validate_csrf_token(csrf_token):
        return PlainTextResponse("Invalid form submission.", status_code=403)
    hyps = load_hypotheses()
    if hyp_id in hyps:
        del hyps[hyp_id]
        save_hypotheses(hyps)
    return RedirectResponse("/hypothesis", status_code=303)


@router.get("/prophecy", response_class=HTMLResponse)
async def prophecy(request: Request,
                   character: str = Query("", max_length=20),
                   ascension: int = Query(0, ge=0, le=20)):
    """Pre-run prediction: win probability, danger zones, recommendation.

    Uses historical runs at the same character + similar ascension to estimate
    what's likely to happen if you start this run. Empowers planning rather
    than gating play.
    """
    from sts2.prophecy import generate_prophecy
    a = _app()
    result = None
    if character:
        runs = await a._get_runs()
        try:
            result = generate_prophecy(character, ascension, runs)
        except Exception:
            result = {"available": False, "reason": "Prophecy computation failed."}
    return a.templates.TemplateResponse(request, "prophecy.html", {
        "characters": CHARACTERS,
        "selected_character": character,
        "selected_ascension": ascension,
        "result": result,
    })


@router.get("/graveyard", response_class=HTMLResponse)
async def graveyard(request: Request):
    a = _app()
    try:
        from sts2.graveyard import generate_epitaph
        runs = await a._get_runs()
        deaths = [r for r in runs if not r.win][-50:]
        graves = [{"run": r, "epitaph": generate_epitaph(r, a.kb)} for r in reversed(deaths)]
    except ImportError:
        graves = []
    return a.templates.TemplateResponse(request, "graveyard.html", {"graves": graves})


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


@router.get("/epochs", response_class=HTMLResponse)
async def epochs_page(request: Request, category: str = Query(None, max_length=50),
                      character: str = Query(None, max_length=50)):
    a = _app()
    progress = await a._get_progress()
    epoch_list = a.kb.get_epochs(category=category, character=character)

    # Merge static data with save state
    epoch_states = {}
    if progress:
        for e in progress.epochs:
            epoch_states[e["id"]] = e

    from datetime import datetime, timezone
    epochs_with_state = []
    for ep in epoch_list:
        state_data = epoch_states.get(ep.id, {})
        ts = state_data.get("obtain_date", 0)
        date_str = ""
        if ts > 0:
            date_str = datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%b %d, %Y")
        epochs_with_state.append({
            "epoch": ep,
            "state": state_data.get("state", "not_obtained"),
            "date": date_str,
        })

    unlocked = sum(1 for e in epochs_with_state if e["state"] == "revealed")
    total = len(epochs_with_state)

    return a.templates.TemplateResponse(request, "epochs.html", {
        "epochs": epochs_with_state, "unlocked": unlocked, "total": total,
        "selected_category": category, "selected_character": character,
        "characters": CHARACTERS, "progress": progress,
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

        # Build discovered/undiscovered object lists (sorted alphabetically)
        discovered_card_objs = sorted([c for c in all_cards if c.id in card_ids], key=lambda c: c.name)
        undiscovered_cards = sorted([c for c in all_cards if c.id not in card_ids], key=lambda c: c.name)
        discovered_relic_objs = sorted([r for r in a.kb.relics if r.id in relic_ids], key=lambda r: r.name)
        undiscovered_relic_objs = sorted([r for r in a.kb.relics if r.id not in relic_ids], key=lambda r: r.name)
        discovered_potion_objs = sorted([p for p in a.kb.potions if p.id in potion_ids], key=lambda p: p.name)
        undiscovered_potion_objs = sorted([p for p in a.kb.potions if p.id not in potion_ids], key=lambda p: p.name)
        discovered_event_objs = sorted([e for e in a.kb.events if e.id in event_ids], key=lambda e: e.name)
        undiscovered_event_objs = sorted([e for e in a.kb.events if e.id not in event_ids], key=lambda e: e.name)
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

    coaching_alerts = []

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

        # Compound risk scoring
        try:
            from sts2.risk import compute_death_risk
            risk = compute_death_risk(run, a.kb)
            # Only show danger banner for danger/critical, not caution
            if risk["level"] in ("danger", "critical"):
                danger_level = risk["level"]
                danger_pct = int(run.current_hp / run.max_hp * 100) if run.max_hp else 0
        except ImportError:
            # Fallback: simple HP percentage
            try:
                if run.max_hp > 0:
                    hp_pct = run.current_hp / run.max_hp
                    danger_pct = int(hp_pct * 100)
                    if hp_pct < 0.2:
                        danger_level = "critical"
                    elif hp_pct < 0.4:
                        danger_level = "warning"
            except Exception:
                pass
        except Exception:
            _log.debug("Coaching: risk scoring failed", exc_info=True)

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

        # Defensive gap warning — no Block/defense by floor threshold
        try:
            if run.floor >= 4 and analysis:
                kw_freq = dict(analysis.get("top_keywords", []))
                has_defense = any(k in kw_freq for k in ("Block", "Dexterity", "Frost"))
                if not has_defense:
                    severity = "critical" if run.floor >= 8 else "warning"
                    coaching_alerts.append({
                        "level": severity,
                        "text": f"No defensive cards by floor {run.floor} — pick Block/Frost cards to survive elite fights.",
                    })
        except Exception:
            _log.debug("Coaching: defensive gap alert failed", exc_info=True)

        # Card fatigue — flag over-stacking
        try:
            from collections import Counter as _Counter
            card_counts = _Counter(run.deck)
            for card_id, count in card_counts.items():
                if count >= 3:
                    card_name = a.kb.id_to_name(card_id)
                    coaching_alerts.append({
                        "level": "warning",
                        "text": f"{card_name} appears {count}x in deck — diminishing returns, consider diversifying.",
                    })
        except Exception:
            _log.debug("Coaching: card fatigue failed", exc_info=True)

        # Energy efficiency — avg cost too high for default 3 energy
        try:
            if analysis and analysis.get("avg_cost", 0) > 1.8:
                coaching_alerts.append({
                    "level": "warning",
                    "text": f"Average card cost is {analysis['avg_cost']:.1f} — you may not play your full hand. Add 0-cost cards or energy relics.",
                })
        except Exception:
            _log.debug("Coaching: energy efficiency failed", exc_info=True)

        # Boss preparation — approaching boss floor without key tools
        try:
            boss_floors = {1: 16, 2: 33, 3: 50}
            boss_floor = boss_floors.get(run.act, 99)
            floors_to_boss = boss_floor - run.floor
            if 0 < floors_to_boss <= 4 and analysis:
                kw_freq = dict(analysis.get("top_keywords", []))
                missing = []
                if not any(k in kw_freq for k in ("Block", "Dexterity", "Frost")):
                    missing.append("Block/defense")
                if not any(k in kw_freq for k in ("Strength", "Poison", "Lightning", "Frost")):
                    missing.append("damage scaling")
                if missing:
                    coaching_alerts.append({
                        "level": "critical",
                        "text": f"Boss in ~{floors_to_boss} floors — still missing {', '.join(missing)}. Prioritize these picks.",
                    })
        except Exception:
            _log.debug("Coaching: boss prep failed", exc_info=True)

    # Ghost run comparison
    ghost_splits = []
    ghost_info = None
    if run.active:
        try:
            from sts2.ghost import compute_splits, find_ghost_run, ghost_summary
            all_runs = await a._get_runs()
            ghost = find_ghost_run(run.character, getattr(run, "ascension", 0), all_runs)
            if ghost:
                ghost_splits = compute_splits(run, ghost)
                ghost_info = ghost_summary(ghost_splits)
        except ImportError:
            pass
        except Exception:
            pass

    return a.templates.TemplateResponse(request, "live.html", {
        "run": run, "analysis": analysis, "kb": a.kb,
        "selected_player": player, "total_players": run.total_players,
        "pick_suggestions": pick_suggestions[:6],
        "danger_level": danger_level, "danger_pct": danger_pct,
        "counter_cards": counter_cards, "last_enemy_name": last_enemy_name,
        "synergy_hints": synergy_hints,
        "coaching_alerts": coaching_alerts,
        "ghost_splits": ghost_splits[-5:] if ghost_splits else [],
        "ghost_info": ghost_info,
    })


@router.get("/overlay", response_class=HTMLResponse)
async def overlay(request: Request, player: int = Query(0, ge=0, le=3)):
    """Minimal overlay for OBS browser source or always-on-top second monitor."""
    a = _app()
    run = await _get_live_run(player)
    danger_level = None
    danger_pct = 0
    counter_cards = []
    synergy_hints = []
    top_cards = []
    if run.active:
        try:
            from sts2.risk import compute_death_risk
            risk = compute_death_risk(run, a.kb)
            danger_level = risk["level"] if risk["level"] != "safe" else None
            danger_pct = int(100 - risk["win_probability"])
        except ImportError:
            if run.max_hp and run.current_hp:
                danger_pct = int(run.current_hp / run.max_hp * 100)
                if danger_pct <= 25:
                    danger_level = "critical"
                elif danger_pct <= 50:
                    danger_level = "warning"
        except Exception:
            pass
        # Top cards by play count
        from collections import Counter as _Counter
        card_counts = _Counter(run.deck)
        for card_id, count in card_counts.most_common(5):
            name = a.kb.id_to_name(card_id)
            top_cards.append({"name": name, "count": count})
    return a.templates.TemplateResponse(request, "overlay.html", {
        "run": run, "danger_level": danger_level, "danger_pct": danger_pct,
        "counter_cards": counter_cards, "synergy_hints": synergy_hints,
        "top_cards": top_cards,
    })


@router.get("/deck", response_class=HTMLResponse)
async def deck_analyzer(request: Request,
                        from_run: str = Query(None, max_length=200)):
    a = _app()
    selected_ids: list[str] = []
    from_run_id = None
    if from_run:
        if from_run == "live":
            live_run = await _get_live_run(0)
            if live_run.active and live_run.deck:
                selected_ids = live_run.deck[:_MAX_DECK_SIZE]
                from_run_id = "live"
        else:
            run = await a._get_run_by_id(from_run)
            if run:
                selected_ids = run.deck[:_MAX_DECK_SIZE]
                from_run_id = run.id
    selected_counts: dict[str, int] = {}
    for cid in selected_ids:
        selected_counts[cid] = selected_counts.get(cid, 0) + 1
    return a.templates.TemplateResponse(request, "deck.html", {
        "cards": a.kb.cards, "analysis": None, "selected_ids": selected_ids,
        "selected_counts": selected_counts,
        "from_run_id": from_run_id, "csrf_token": a.generate_csrf_token(),
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
            "selected_ids": [], "selected_counts": {},
            "csrf_token": a.generate_csrf_token(),
        })
    analysis = a.kb.analyze_deck(card_ids)
    selected_counts: dict[str, int] = {}
    for cid in card_ids:
        selected_counts[cid] = selected_counts.get(cid, 0) + 1
    # Deck health via spectral graph analysis: builds keyword-synergy graph,
    # computes algebraic connectivity + orphan list. Score 0-100, higher = more
    # internally coherent. Identifies cards with zero synergy connections.
    from sts2.spectral import deck_spectral_health
    try:
        spectral_health = deck_spectral_health(card_ids, a.kb)
    except Exception:
        spectral_health = None
    return a.templates.TemplateResponse(request, "deck.html", {
        "cards": a.kb.cards, "analysis": analysis, "selected_ids": card_ids,
        "selected_counts": selected_counts,
        "kb": a.kb, "csrf_token": a.generate_csrf_token(),
        "spectral_health": spectral_health,
    })


# ---------------------------------------------------------------------------
# JSON API
# ---------------------------------------------------------------------------

@router.get("/api/analytics")
async def api_analytics(version: str = Query(None, max_length=100),
                        date_from: str = Query(None, alias="from", max_length=10),
                        date_to: str = Query(None, alias="to", max_length=10),
                        ascension: int = Query(None, ge=0, le=20)):
    a = _app()
    if version or date_from or date_to:
        from sts2.analytics import compute_analytics
        runs = await a._get_runs()
        filtered = _filter_runs(runs, version=version,
                                date_from=date_from, date_to=date_to)
        if ascension is not None:
            filtered = [r for r in filtered if r.ascension == ascension]
        progress = await a._get_progress()
        card_stats = progress.card_stats if progress else {}
        return await asyncio.to_thread(compute_analytics, filtered, card_stats, a.kb)
    return await a._get_analytics(ascension=ascension)


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
    # Atomic check-and-reserve. Increment is done INSIDE the generator's try
    # block (paired with the finally decrement) so a pre-stream client
    # disconnect can't leak a slot. The pre-check here only refuses obvious
    # overflows — the generator will re-check on first yield.
    if _sse_active >= _SSE_MAX_CONNECTIONS:
        return PlainTextResponse("Too many live connections. Close another tab.",
                                 status_code=429)

    async def event_generator():
        global _sse_active
        # Re-check cap and reserve atomically when the body actually starts;
        # this pairs with the `finally` decrement so disconnect cannot leak.
        if _sse_active >= _SSE_MAX_CONNECTIONS:
            yield "event: error\ndata: {\"reason\":\"too_many\"}\n\n"
            return
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
                    yield "event: timeout\ndata: {}\n\n"
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


@router.post("/shutdown")
async def shutdown(request: Request):
    """Gracefully stop SpireScope. Requires admin token or a loopback client."""
    a = _app()
    token = request.headers.get("X-Admin-Token", "")
    has_valid_token = bool(token) and secrets.compare_digest(token, a._ADMIN_TOKEN)
    if not _is_loopback_client(request) and not has_valid_token:
        return PlainTextResponse("Unauthorized.", status_code=403)
    import os
    import signal
    import threading
    threading.Timer(0.5, lambda: os.kill(os.getpid(), signal.SIGTERM)).start()
    return {"status": "shutting down"}


@router.get("/api/cards/{card_id}")
async def api_card(card_id: str = Path(max_length=200)):
    a = _app()
    card = a.kb.get_card_by_id(card_id)
    if not card:
        # Match the JSON shape used by the success path so API clients
        # can parse both responses uniformly.
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "Card not found.", "card_id": card_id}, status_code=404)
    progress = await a._get_progress()
    card_stats = progress.card_stats.get(card_id, {}) if progress else {}
    synergies = a.kb.find_synergies(card_id)
    return {
        **card.model_dump(),
        "stats": card_stats,
        "synergies": [{"id": s.id, "name": s.name} for s in synergies[:10]],
    }


def _csv_safe(v: str) -> str:
    """Escape CSV injection characters."""
    if v and v[0] in "=+-@\t\r":
        return "'" + v
    return v


@router.get("/api/runs")
async def api_runs(character: str = Query(None, max_length=50), result: str = Query(None, max_length=10),
                   version: str = Query(None, max_length=100),
                   date_from: str = Query(None, alias="from", max_length=10),
                   date_to: str = Query(None, alias="to", max_length=10),
                   limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    a = _app()
    run_list = await a._get_runs()
    filtered = _filter_runs(run_list, version=version,
                            date_from=date_from, date_to=date_to)
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
