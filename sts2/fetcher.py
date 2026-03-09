"""Scraper to update game data from slaythespire2.gg. Run: python -m sts2 update"""
import json
import logging
import re
import time
import urllib.request
import urllib.error

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

WIKI_BASE = "https://slaythespire2.gg"
_SCRAPE_DELAY = 1.0  # seconds between wiki requests to avoid hammering

# Markup tags used in wiki descriptions: [gold]...[/gold], [blue], [red], etc.
_MARKUP_RE = re.compile(r"\[/?(?:gold|blue|red|green|energy:\d+|star:\d+)\]")


def _clean_description(desc: str) -> str:
    """Strip wiki markup tags from descriptions."""
    return _MARKUP_RE.sub("", desc).strip()


def _get_user_agent() -> str:
    try:
        from importlib.metadata import version
        return f"Spirescope/{version('spirescope')}"
    except Exception:
        return "Spirescope/1.0"


def _fetch_page(path: str) -> str:
    """Fetch a wiki page and return its HTML content."""
    url = f"{WIKI_BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": _get_user_agent()})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _extract_json_objects(html: str, category: str) -> list[dict]:
    """Extract JSON objects with the given category from RSC payloads in HTML.

    Uses two extraction strategies:
      1. Flat regex — matches single-level JSON objects with "category":"<cat>"
      2. Nested regex — matches multi-level JSON (handles wiki redesigns that nest data)
    Falls back to strategy 2 only if strategy 1 finds nothing.
    """
    results = []
    seen_ids = set()

    # Strategy 1: flat JSON objects (current wiki format)
    pattern = re.compile(
        r'\{[^{}]*"category"\s*:\s*"' + re.escape(category) + r'"[^{}]*\}'
    )
    for match in pattern.finditer(html):
        try:
            obj = json.loads(match.group())
            if obj.get("category") == category:
                obj_id = obj.get("id", "")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue

    if results:
        return results

    # Strategy 2: nested JSON — find larger blocks containing the category,
    # then extract individual items from parsed structures
    log.info("Flat extraction found 0 for %s, trying nested extraction", category)
    nested_pattern = re.compile(
        r'\{[^{}]*(?:\{[^{}]*\}[^{}]*)*"category"\s*:\s*"' + re.escape(category) + r'"'
        r'[^{}]*(?:\{[^{}]*\}[^{}]*)*\}'
    )
    for match in nested_pattern.finditer(html):
        try:
            obj = json.loads(match.group())
            if obj.get("category") == category:
                obj_id = obj.get("id", "")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue

    # Strategy 3: scan __NEXT_DATA__ script tag if present
    if not results:
        next_data_match = re.search(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.DOTALL)
        if next_data_match:
            try:
                next_data = json.loads(next_data_match.group(1))
                _walk_json_for_category(next_data, category, results, seen_ids)
            except (json.JSONDecodeError, ValueError):
                pass

    if not results:
        log.warning("All extraction strategies found 0 objects for category=%s (HTML length=%d)", category, len(html))
    return results


def _walk_json_for_category(data, category: str, results: list, seen_ids: set, depth: int = 0):
    """Recursively walk a JSON structure looking for objects with matching category."""
    if depth > 20:
        return
    if isinstance(data, dict):
        if data.get("category") == category:
            obj_id = data.get("id", "")
            if obj_id and obj_id not in seen_ids:
                seen_ids.add(obj_id)
                results.append(data)
        else:
            for v in data.values():
                _walk_json_for_category(v, category, results, seen_ids, depth + 1)
    elif isinstance(data, list):
        for item in data:
            _walk_json_for_category(item, category, results, seen_ids, depth + 1)


_CHARACTER_SUFFIXES = {
    "ironclad", "silent", "defect", "necrobinder", "the-regent", "regent",
    "colorless", "curse", "status",
}


def _load_existing_name_index(filename: str, prefix: str) -> dict[str, str]:
    """Build a name->id lookup from existing data to match wiki items."""
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    index = {}
    for item in data:
        name = item.get("name", "").lower().strip()
        item_id = item.get("id", "")
        if name and item_id:
            index[name] = item_id
    return index


def _wiki_id_to_game_id(wiki_id: str, prefix: str, character: str = "") -> str:
    """Convert wiki slug to game ID, stripping known character suffixes.

    'bash-ironclad' -> 'CARD.BASH'
    'iron-wave-ironclad' -> 'CARD.IRON_WAVE'
    'finesse-colorless' -> 'CARD.FINESSE'
    'after-image-silent' -> 'CARD.AFTER_IMAGE'
    """
    slug = wiki_id
    # Strip known character suffix from end of slug (longest match first)
    for suffix in sorted(_CHARACTER_SUFFIXES, key=len, reverse=True):
        if slug.endswith(f"-{suffix}"):
            slug = slug[: -(len(suffix) + 1)]
            break
    return f"{prefix}.{slug.upper().replace('-', '_')}"


def _scrape_cards(html: str) -> list[dict]:
    """Parse card data from wiki HTML."""
    raw = _extract_json_objects(html, "CARD")
    # Build name->id index from existing data for matching
    name_index = _load_existing_name_index("cards.json", "CARD")
    cards = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

        character = obj.get("character", "Colorless")
        name = obj.get("name", "")
        # Prefer matching by name against existing data to avoid ID mismatches
        game_id = name_index.get(name.lower().strip())
        if not game_id:
            game_id = _wiki_id_to_game_id(wiki_id, "CARD", character)

        # Determine cost string
        energy = obj.get("energy")
        if energy is None:
            cost = "Unplayable"
        elif isinstance(energy, int):
            cost = str(energy)
        else:
            cost = str(energy)

        # Extract keywords from description
        desc = _clean_description(obj.get("description", ""))
        keywords = _extract_keywords(desc)

        card_type = obj.get("cardType", "Skill")
        # Map wiki card types
        type_map = {"Attack": "Attack", "Skill": "Skill", "Power": "Power",
                     "Status": "Status", "Curse": "Curse"}
        card_type = type_map.get(card_type, card_type)

        desc_upgraded = _clean_description(obj.get("upgradedDescription", ""))

        cards.append({
            "id": game_id,
            "name": obj.get("name", ""),
            "character": character,
            "cost": cost,
            "type": card_type,
            "rarity": obj.get("rarity", "Common"),
            "description": desc,
            "description_upgraded": desc_upgraded,
            "keywords": keywords,
        })

    return sorted(cards, key=lambda c: (c["character"], c["name"]))


def _scrape_relics(html: str) -> list[dict]:
    """Parse relic data from wiki HTML."""
    raw = _extract_json_objects(html, "RELIC")
    name_index = _load_existing_name_index("relics.json", "RELIC")
    relics = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

        pools = obj.get("relicPools", ["Shared"])
        character = pools[0] if pools else "Shared"

        name = obj.get("name", "")
        game_id = name_index.get(name.lower().strip())
        if not game_id:
            game_id = f"RELIC.{wiki_id.upper().replace('-', '_')}"

        relics.append({
            "id": game_id,
            "name": obj.get("name", ""),
            "character": character,
            "rarity": obj.get("rarity", ""),
            "description": _clean_description(obj.get("description", "")),
        })

    return sorted(relics, key=lambda r: (r["character"], r["name"]))


def _scrape_potions(html: str) -> list[dict]:
    """Parse potion data from wiki HTML."""
    raw = _extract_json_objects(html, "POTION")
    name_index = _load_existing_name_index("potions.json", "POTION")
    potions = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

        name = obj.get("name", "")
        game_id = name_index.get(name.lower().strip())
        if not game_id:
            game_id = f"POTION.{wiki_id.upper().replace('-', '_')}"

        potions.append({
            "id": game_id,
            "name": obj.get("name", ""),
            "rarity": obj.get("rarity", ""),
            "description": _clean_description(obj.get("description", "")),
        })

    return sorted(potions, key=lambda p: p["name"])


# Common STS keywords to detect in descriptions
_KEYWORD_PATTERNS = [
    "Block", "Strength", "Dexterity", "Vulnerable", "Weak", "Poison",
    "Exhaust", "Ethereal", "Innate", "Retain", "Draw", "Scry",
    "Channel", "Evoke", "Focus", "Frost", "Lightning", "Dark", "Plasma",
    "Intangible", "Artifact", "Plated Armor", "Thorns", "Ritual",
    "Barricade", "Metallicize", "Shiv", "Discard", "Curse", "Wound",
    "Burn", "Slime", "Void", "Daze", "Clash", "Combo", "Flourish",
    "Echo", "Summon", "Bone", "Soul", "Regen",
]


def _extract_keywords(description: str) -> list[str]:
    """Extract gameplay keywords from card description text."""
    desc_lower = description.lower()
    return [kw for kw in _KEYWORD_PATTERNS if kw.lower() in desc_lower]


def _save_json(filename: str, data: list[dict]) -> int:
    """Write data to a JSON file, return count of items."""
    path = DATA_DIR / filename
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)
    return len(data)


def _save_update_timestamp():
    """Write a timestamp file recording when data was last updated."""
    import datetime
    path = DATA_DIR / "last_updated.txt"
    path.write_text(datetime.datetime.now(datetime.timezone.utc).isoformat(), encoding="utf-8")


def _merge_with_existing(filename: str, new_data: list[dict], id_field: str = "id") -> list[dict]:
    """Merge new scraped data with existing data, preserving manual additions.

    Items in new_data update existing items by ID. Items in the existing file
    that are NOT in new_data are kept (they may be manual additions like enemies/events).
    """
    existing_path = DATA_DIR / filename
    if not existing_path.exists():
        return new_data

    try:
        with open(existing_path, "r", encoding="utf-8") as f:
            existing = json.load(f)
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Existing %s is corrupted (%s), overwriting with new data", filename, exc)
        return new_data

    existing_by_id = {item[id_field]: item for item in existing}
    new_by_id = {item[id_field]: item for item in new_data}

    # Update existing with new data
    merged_by_id = {**existing_by_id, **new_by_id}
    return list(merged_by_id.values())


def _discover_enemies_from_saves() -> list[dict]:
    """Scan run history and current run saves to discover enemies not yet in enemies.json."""
    from sts2.config import SAVE_DIR

    existing_path = DATA_DIR / "enemies.json"
    existing_ids = set()
    if existing_path.exists():
        try:
            for item in json.loads(existing_path.read_text(encoding="utf-8")):
                existing_ids.add(item["id"])
        except (json.JSONDecodeError, OSError):
            pass

    discovered = {}  # id -> {id, name, act, type}

    # Scan progress.save for encounter stats
    progress_path = SAVE_DIR / "progress.save"
    if progress_path.exists():
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            for es in data.get("encounter_stats", []):
                enc_id = es.get("encounter_id", "")
                if enc_id and enc_id not in existing_ids and enc_id not in discovered:
                    name = enc_id.split(".", 1)[-1].replace("_", " ").title() if "." in enc_id else enc_id
                    etype = "boss" if "BOSS" in enc_id.upper() else "elite" if "ELITE" in enc_id.upper() else "normal"
                    discovered[enc_id] = {
                        "id": enc_id,
                        "name": name,
                        "act": [],
                        "type": etype,
                        "hp_range": "",
                        "patterns": [],
                        "tips": ["Auto-discovered from save data"],
                    }
        except (json.JSONDecodeError, OSError):
            pass

    # Scan run history for monster IDs
    history_dir = SAVE_DIR / "history"
    if history_dir.exists():
        for run_file in history_dir.glob("*.run"):
            try:
                data = json.loads(run_file.read_text(encoding="utf-8"))
                act_num = 0
                for act_floors in data.get("map_point_history", []):
                    act_num += 1
                    act_label = f"Act {act_num}"
                    for floor_data in act_floors:
                        rooms = floor_data.get("rooms", [])
                        room = rooms[0] if rooms else {}
                        floor_type = floor_data.get("map_point_type", room.get("room_type", ""))
                        for monster_id in room.get("monster_ids", []):
                            game_id = f"MONSTER.{monster_id}" if "." not in monster_id else monster_id
                            if game_id in existing_ids:
                                continue
                            if game_id not in discovered:
                                name = monster_id.replace("_", " ").title()
                                etype = "boss" if "boss" in floor_type.lower() else "elite" if "elite" in floor_type.lower() else "normal"
                                discovered[game_id] = {
                                    "id": game_id,
                                    "name": name,
                                    "act": [],
                                    "type": etype,
                                    "hp_range": "",
                                    "patterns": [],
                                    "tips": ["Auto-discovered from save data"],
                                }
                            # Add act if not already there
                            if act_label not in discovered[game_id]["act"]:
                                discovered[game_id]["act"].append(act_label)
            except (json.JSONDecodeError, OSError):
                continue

    return list(discovered.values())


def _discover_events_from_saves() -> list[dict]:
    """Scan save data to discover events not yet in events.json."""
    from sts2.config import SAVE_DIR

    existing_path = DATA_DIR / "events.json"
    existing_ids = set()
    if existing_path.exists():
        try:
            for item in json.loads(existing_path.read_text(encoding="utf-8")):
                existing_ids.add(item["id"])
        except (json.JSONDecodeError, OSError):
            pass

    discovered = {}

    # Scan progress.save for discovered events
    progress_path = SAVE_DIR / "progress.save"
    if progress_path.exists():
        try:
            data = json.loads(progress_path.read_text(encoding="utf-8"))
            for event_id in data.get("discovered_events", []):
                if event_id and event_id not in existing_ids and event_id not in discovered:
                    name = event_id.split(".", 1)[-1].replace("_", " ").title() if "." in event_id else event_id
                    discovered[event_id] = {
                        "id": event_id,
                        "name": name,
                        "act": [],
                        "description": "Auto-discovered from save data",
                        "choices": [],
                        "notes": "",
                    }
        except (json.JSONDecodeError, OSError):
            pass

    return list(discovered.values())


def _fetch_with_retry(path: str, retries: int = 2) -> str:
    """Fetch a wiki page with retry on network error."""
    for attempt in range(retries + 1):
        try:
            return _fetch_page(path)
        except urllib.error.URLError as e:
            if attempt < retries:
                log.warning("Fetch %s failed (attempt %d/%d): %s", path, attempt + 1, retries + 1, e)
                time.sleep(2 * (attempt + 1))
            else:
                log.error("Fetch %s failed after %d attempts: %s", path, retries + 1, e)
                raise


def _existing_count(filename: str) -> int:
    """Return the number of items in an existing data file."""
    path = DATA_DIR / filename
    if not path.exists():
        return 0
    try:
        return len(json.loads(path.read_text(encoding="utf-8")))
    except (json.JSONDecodeError, OSError):
        return 0


def run_fetcher(save_only: bool = False):
    """Scrape game data and update local JSON files.

    Args:
        save_only: If True, skip wiki fetching and only discover from saves.
    """
    print("\n  Spirescope Data Updater")
    print("  ======================\n")

    if not save_only:
        scrapers = {
            "cards.json": ("cards", "/cards", _scrape_cards),
            "relics.json": ("relics", "/relics", _scrape_relics),
            "potions.json": ("potions", "/potions", _scrape_potions),
        }

        first = True
        for filename, (label, path, scraper_fn) in scrapers.items():
            if not first:
                time.sleep(_SCRAPE_DELAY)
            first = False
            print(f"  Fetching {label} from {WIKI_BASE}{path} ...")
            try:
                html = _fetch_with_retry(path)
                new_data = scraper_fn(html)
                if not new_data:
                    log.warning("No %s found from %s — wiki format may have changed", label, path)
                    print(f"    Warning: no {label} found — wiki format may have changed")
                    print(f"    Keeping existing data. Try 'spirescope update --save-only' instead.")
                    continue
                # Guard: don't overwrite large dataset with empty/tiny wiki result
                existing = _existing_count(filename)
                if existing > 20 and len(new_data) < existing * 0.1:
                    log.warning("Wiki returned %d %s vs %d existing — possible format change, skipping", len(new_data), label, existing)
                    print(f"    Warning: wiki returned only {len(new_data)} {label} vs {existing} existing, skipping overwrite")
                    continue
                merged = _merge_with_existing(filename, new_data)
                count = _save_json(filename, merged)
                print(f"    Saved {count} {label} ({len(new_data)} from wiki)")
            except urllib.error.URLError as e:
                print(f"    Error fetching {label}: {e}")
            except Exception as e:
                log.exception("Scraper error for %s", label)
                print(f"    Error processing {label}: {e}")
    else:
        print("  Save-only mode: skipping wiki fetch\n")

    # Discover enemies and events from save files
    print("  Scanning save files for new enemies/events ...")
    new_enemies = _discover_enemies_from_saves()
    if new_enemies:
        merged = _merge_with_existing("enemies.json", new_enemies)
        count = _save_json("enemies.json", merged)
        print(f"    Discovered {len(new_enemies)} new enemies (total: {count})")
    else:
        print("    No new enemies found")

    new_events = _discover_events_from_saves()
    if new_events:
        merged = _merge_with_existing("events.json", new_events)
        count = _save_json("events.json", merged)
        print(f"    Discovered {len(new_events)} new events (total: {count})")
    else:
        print("    No new events found")

    # Report all data files
    print()
    print("  Data summary:")
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            count = len(data) if isinstance(data, list) else f"dict ({len(data)} keys)"
            print(f"    {f.name}: {count} entries")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"    {f.name}: ERROR reading ({exc})")

    _save_update_timestamp()

    print()
    print("  Done! Restart Spirescope to use updated data.")
    print()
