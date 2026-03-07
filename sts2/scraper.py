"""Scraper to update game data from slaythespire2.gg. Run: python -m sts2 update"""
import json
import logging
import re
import urllib.request
import urllib.error

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

WIKI_BASE = "https://slaythespire2.gg"

# Markup tags used in wiki descriptions: [gold]...[/gold], [blue], [red], etc.
_MARKUP_RE = re.compile(r"\[/?(?:gold|blue|red|green|energy:\d+|star:\d+)\]")


def _clean_description(desc: str) -> str:
    """Strip wiki markup tags from descriptions."""
    return _MARKUP_RE.sub("", desc).strip()


def _fetch_page(path: str) -> str:
    """Fetch a wiki page and return its HTML content."""
    url = f"{WIKI_BASE}{path}"
    req = urllib.request.Request(url, headers={"User-Agent": "Spirescope/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read().decode("utf-8")


def _extract_json_objects(html: str, category: str) -> list[dict]:
    """Extract JSON objects with the given category from RSC payloads in HTML."""
    results = []
    # Match JSON objects containing "category":"<category>" in script tags / RSC stream
    # The data appears as serialized JSON within the page source
    pattern = re.compile(
        r'\{[^{}]*"category"\s*:\s*"' + re.escape(category) + r'"[^{}]*\}'
    )
    for match in pattern.finditer(html):
        try:
            obj = json.loads(match.group())
            if obj.get("category") == category:
                results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue
    return results


_CHARACTER_SUFFIXES = {
    "ironclad", "silent", "defect", "necrobinder", "the-regent", "regent",
    "colorless", "curse", "status",
}


def _load_existing_name_index(filename: str, prefix: str) -> dict[str, str]:
    """Build a name->id lookup from existing data to match wiki items."""
    path = DATA_DIR / filename
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    index = {}
    for item in data:
        name = item.get("name", "").lower().strip()
        if name:
            index[name] = item["id"]
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

        cards.append({
            "id": game_id,
            "name": obj.get("name", ""),
            "character": character,
            "cost": cost,
            "type": card_type,
            "rarity": obj.get("rarity", "Common"),
            "description": desc,
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
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    return len(data)


def _merge_with_existing(filename: str, new_data: list[dict], id_field: str = "id") -> list[dict]:
    """Merge new scraped data with existing data, preserving manual additions.

    Items in new_data update existing items by ID. Items in the existing file
    that are NOT in new_data are kept (they may be manual additions like enemies/events).
    """
    existing_path = DATA_DIR / filename
    if not existing_path.exists():
        return new_data

    with open(existing_path, "r", encoding="utf-8") as f:
        existing = json.load(f)

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
        for item in json.loads(existing_path.read_text(encoding="utf-8")):
            existing_ids.add(item["id"])

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
        for item in json.loads(existing_path.read_text(encoding="utf-8")):
            existing_ids.add(item["id"])

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


def run_scraper():
    """Scrape game data from slaythespire2.gg and update local JSON files."""
    print("\n  Spirescope Data Updater")
    print("  ======================\n")

    scrapers = {
        "cards.json": ("cards", "/cards", _scrape_cards),
        "relics.json": ("relics", "/relics", _scrape_relics),
        "potions.json": ("potions", "/potions", _scrape_potions),
    }

    for filename, (label, path, scraper_fn) in scrapers.items():
        print(f"  Fetching {label} from {WIKI_BASE}{path} ...")
        try:
            html = _fetch_page(path)
            new_data = scraper_fn(html)
            if not new_data:
                print(f"    Warning: no {label} found, keeping existing data")
                continue
            merged = _merge_with_existing(filename, new_data)
            count = _save_json(filename, merged)
            print(f"    Saved {count} {label} ({len(new_data)} from wiki)")
        except urllib.error.URLError as e:
            print(f"    Error fetching {label}: {e}")
        except Exception as e:
            log.exception("Scraper error for %s", label)
            print(f"    Error processing {label}: {e}")

    # Discover enemies and events from save files
    print()
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
        data = json.loads(f.read_text(encoding="utf-8"))
        print(f"    {f.name}: {len(data)} entries")

    print()
    print("  Done! Restart Spirescope to use updated data.")
    print()
