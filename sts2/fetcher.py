"""Scraper to update game data from slaythespire2.gg. Run: python -m sts2 update"""
import json
import logging
import re
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

# Per-entity provenance fields (set at merge time when content changes)
_PROVENANCE_FIELDS = ("fetched_from", "fetched_at")

WIKI_BASE = "https://slaythespire2.gg"
# Per their robots.txt: general scraping is permitted; /api, /admin,
# /analysis, /planner are disallowed and we never request them.
_SCRAPE_DELAY = 1.0  # seconds between wiki requests to avoid hammering

# Markup tags used in wiki descriptions: [gold]...[/gold], [blue], [red], etc.
_COLOR_RE = re.compile(r"\[/?(?:gold|blue|red|green)\]")
# When a digit precedes the tag (e.g. "6[star:1]"), the digit IS the value and
# the tag is just an icon indicator.  When no digit precedes, use the tag number.
_PREFIXED_ENERGY_RE = re.compile(r"(\d+)\[energy:\d+\]")
_PREFIXED_STAR_RE = re.compile(r"(\d+)\[star:\d+\]")
_ENERGY_RE = re.compile(r"\[energy:(\d+)\]")
_STAR_RE = re.compile(r"\[star:(\d+)\]")
# RSC payload template tokens: {Energy:energyIcons(2)} carries its value and
# renders as "2 Energy"; other {Name:...} templates (diff(), choose(...),
# plural/cond forms) carry no resolvable value and cannot be rendered.
_TOKEN_ENERGY_RE = re.compile(r"\{\w+:energyIcons\((\d+)\)\}")
_TOKEN_STAR_RE = re.compile(r"\{\w+:starIcons\((\d+)\)\}")
_UNRESOLVED_TOKEN_RE = re.compile(r"\{\w+:")


def _clean_description(desc: str) -> str:
    """Strip wiki markup tags from descriptions, converting icons to text."""
    # Handle "6[star:1]" -> "6 Star" (digit before tag takes precedence)
    desc = _PREFIXED_ENERGY_RE.sub(lambda m: f"{m.group(1)} Energy", desc)
    desc = _PREFIXED_STAR_RE.sub(lambda m: f"{m.group(1)} Star", desc)
    # Handle "[energy:2]" -> "2 Energy" (no preceding digit)
    desc = _ENERGY_RE.sub(lambda m: f"{m.group(1)} Energy", desc)
    desc = _STAR_RE.sub(lambda m: f"{m.group(1)} Star", desc)
    desc = _TOKEN_ENERGY_RE.sub(lambda m: f"{m.group(1)} Energy", desc)
    desc = _TOKEN_STAR_RE.sub(lambda m: f"{m.group(1)} Star", desc)
    desc = _COLOR_RE.sub("", desc)
    # RSC text encodes line breaks as a literal backslash-n two-character
    # sequence after JSON decoding; normalize before whitespace collapse.
    desc = desc.replace("\\n", " ")
    # Collapse all internal whitespace (including embedded newlines from RSC
    # payload structure and double-spaces left by stripped icons) into single
    # spaces. CLAUDE.md data-hygiene protocol forbids both. Regression: v2.2.1
    # fixed 269 newline descriptions, but the fix lived only in the data, not
    # in the fetcher — so each wiki refresh re-introduced them.
    desc = re.sub(r"\s+", " ", desc)
    return desc.strip()


def _get_user_agent() -> str:
    from sts2.config import VERSION
    return (
        f"Mozilla/5.0 (compatible; Spirescope/{VERSION}; "
        f"+https://github.com/thequantumfalcon/spirescope)"
    )


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

    # Strategy 4: RSC streaming payloads — Next.js 13+ embeds data in
    # self.__next_f.push() calls with string-escaped JSON
    if not results:
        log.info("Trying RSC streaming extraction for %s", category)
        _extract_from_rsc_payloads(html, category, results, seen_ids)

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


def _extract_from_rsc_payloads(html: str, category: str, results: list, seen_ids: set):
    """Extract JSON objects from Next.js RSC streaming payloads.

    Next.js 13+ embeds data in self.__next_f.push() calls.  The string
    arguments may contain JSON objects with escaped quotes.  We extract
    all push() string content, unescape it, then scan for category matches.
    """
    # Match the push() string literal directly rather than locating the
    # array's closing "]" first — card text contains "]" (e.g. [gold]
    # markup), so any pattern that scans for the array bracket truncates
    # the payload at the first markup tag.
    chunk_pattern = re.compile(
        r'self\.__next_f\.push\(\s*\[\d+,\s*"((?:[^"\\]|\\.)*)"\s*\]\s*\)',
        re.DOTALL,
    )
    raw_chunks = [m.group(1) for m in chunk_pattern.finditer(html)]
    if not raw_chunks:
        return
    # Chunks are one continuous stream: the site splits JSON objects
    # mid-token across push() calls, so join with no separator BEFORE
    # decoding (an escape sequence can straddle a chunk boundary).
    combined_raw = "".join(raw_chunks)
    try:
        combined = combined_raw.encode().decode("unicode_escape")
    except (UnicodeDecodeError, ValueError):
        combined = combined_raw

    # Now search the decoded content for JSON objects with matching category.
    # Try both flat and bracket-balanced extraction.
    cat_escaped = re.escape(category)

    # Attempt 1: find JSON objects using a greedy-but-bounded approach
    obj_pattern = re.compile(
        r'\{[^{}]*"category"\s*:\s*"' + cat_escaped + r'"[^{}]*\}'
    )
    for match in obj_pattern.finditer(combined):
        try:
            obj = json.loads(match.group())
            if obj.get("category") == category:
                obj_id = obj.get("id", "")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue

    # Attempt 2 always runs: objects whose text contains braces are
    # invisible to the flat pattern (seen_ids dedupes the overlap).

    # Attempt 2: bracket-balanced extraction for nested objects
    # Find positions of category marker, then expand outward to find balanced {}
    for m in re.finditer(r'"category"\s*:\s*"' + cat_escaped + r'"', combined):
        start = m.start()
        # Walk backward to find opening brace
        depth = 0
        obj_start = start
        for i in range(start - 1, max(start - 5000, -1), -1):
            if combined[i] == '}':
                depth += 1
            elif combined[i] == '{':
                if depth == 0:
                    obj_start = i
                    break
                depth -= 1
        # Walk forward from obj_start to find balanced closing brace
        depth = 0
        obj_end = len(combined)
        for i in range(obj_start, min(obj_start + 5000, len(combined))):
            if combined[i] == '{':
                depth += 1
            elif combined[i] == '}':
                depth -= 1
                if depth == 0:
                    obj_end = i + 1
                    break
        try:
            obj = json.loads(combined[obj_start:obj_end])
            if obj.get("category") == category:
                obj_id = obj.get("id", "")
                if obj_id and obj_id not in seen_ids:
                    seen_ids.add(obj_id)
                    results.append(obj)
        except (json.JSONDecodeError, ValueError):
            continue


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


# Fields that must be non-empty on most scraped objects. If the wiki renames or
# drops one of these, downstream merge silently keeps stale data — validation
# rejects the batch so the existing "no X found" guard preserves curated data.
_EXPECTED_FIELDS: dict[str, frozenset[str]] = {
    "CARD": frozenset({"id", "name", "cardType", "description"}),
    "RELIC": frozenset({"id", "name", "description"}),
    "POTION": frozenset({"id", "name", "description"}),
}
_KEYS_BASELINE_FILE = ".fetcher_keys.json"


def _validate_extraction(raw: list[dict], category: str) -> bool:
    """Return True when at least 90% of objects have all required fields populated."""
    required = _EXPECTED_FIELDS.get(category)
    if not required or not raw:
        return True
    missing_counts: dict[str, int] = {}
    bad = 0
    for obj in raw:
        obj_missing = [f for f in required if not obj.get(f)]
        if obj_missing:
            bad += 1
            for f in obj_missing:
                missing_counts[f] = missing_counts.get(f, 0) + 1
    if bad / len(raw) > 0.1:
        summary = ", ".join(f"{f}={n}" for f, n in sorted(missing_counts.items()))
        log.warning(
            "Field-validation failed for category=%s: %d/%d objects missing required fields (%s)",
            category, bad, len(raw), summary,
        )
        return False
    return True


def _log_field_drift(raw: list[dict], category: str) -> None:
    """Persist the union of keys per category and log additions/removals between runs."""
    if not raw:
        return
    current = sorted({k for obj in raw for k in obj.keys()})
    baseline_path = DATA_DIR / _KEYS_BASELINE_FILE
    baseline: dict[str, list[str]] = {}
    if baseline_path.exists():
        try:
            baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            baseline = {}
    previous = set(baseline.get(category, []))
    current_set = set(current)
    if previous and previous != current_set:
        added = sorted(current_set - previous)
        removed = sorted(previous - current_set)
        if added or removed:
            log.info(
                "Field-set drift for category=%s: added=%s removed=%s",
                category, added or "[]", removed or "[]",
            )
    baseline[category] = current
    try:
        baseline_path.write_text(
            json.dumps(baseline, indent=2, sort_keys=True), encoding="utf-8"
        )
    except OSError as exc:
        log.warning("Failed to write %s: %s", _KEYS_BASELINE_FILE, exc)


def _scrape_cards(html: str) -> list[dict]:
    """Parse card data from wiki HTML."""
    raw = _extract_json_objects(html, "CARD")
    _log_field_drift(raw, "CARD")
    if not _validate_extraction(raw, "CARD"):
        return []
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
        # Normalize wiki character name to match app convention
        if character == "The Regent":
            character = "Regent"
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
        # A description with unresolved template tokens cannot be rendered;
        # blank it so _merge_with_existing keeps the curated existing text.
        if _UNRESOLVED_TOKEN_RE.search(desc):
            desc = ""
        keywords = _extract_keywords(desc)

        card_type = obj.get("cardType", "Skill")
        # Map wiki card types
        type_map = {"Attack": "Attack", "Skill": "Skill", "Power": "Power",
                     "Status": "Status", "Curse": "Curse"}
        card_type = type_map.get(card_type, card_type)

        # Site renamed upgradedDescription -> descriptionUpgraded; accept both.
        desc_upgraded = _clean_description(
            obj.get("descriptionUpgraded") or obj.get("upgradedDescription", "")
        )
        if _UNRESOLVED_TOKEN_RE.search(desc_upgraded):
            desc_upgraded = ""

        cards.append({
            "id": game_id,
            "name": obj.get("name", ""),
            "character": character,
            "cost": cost,
            "type": card_type,
            "rarity": obj.get("rarity", ""),
            "description": desc,
            "description_upgraded": desc_upgraded,
            "keywords": keywords,
        })

    return sorted(cards, key=lambda c: (c["character"], c["name"]))


def _scrape_relics(html: str) -> list[dict]:
    """Parse relic data from wiki HTML."""
    raw = _extract_json_objects(html, "RELIC")
    _log_field_drift(raw, "RELIC")
    if not _validate_extraction(raw, "RELIC"):
        return []
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
    _log_field_drift(raw, "POTION")
    if not _validate_extraction(raw, "POTION"):
        return []
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
    existing: list[dict] = []
    if existing_path.exists():
        try:
            with open(existing_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Existing %s is corrupted (%s), overwriting with new data", filename, exc)
            existing = []

    existing_by_id = {item[id_field]: item for item in existing}
    new_by_id = {item[id_field]: item for item in new_data}

    today = datetime.now(timezone.utc).date().isoformat()

    # Update existing with new data, but preserve non-empty existing fields
    # when wiki provides empty values (avoids overwriting curated data)
    merged_by_id = dict(existing_by_id)
    for item_id, new_item in new_by_id.items():
        if item_id in merged_by_id:
            old = merged_by_id[item_id]
            merged = dict(old)
            changed = False
            for k, v in new_item.items():
                if k in _PROVENANCE_FIELDS:
                    continue
                old_v = old.get(k)
                # Only preserve old value when new is empty/None and old has content
                if v in (None, "") and old_v not in (None, ""):
                    continue
                if merged.get(k) != v:
                    changed = True
                merged[k] = v
            # Provenance stamps move only when the record's content changed,
            # so data diffs stay reviewable (unchanged entities don't churn)
            if changed and new_item.get("fetched_from"):
                merged["fetched_from"] = new_item["fetched_from"]
                merged["fetched_at"] = today
            merged_by_id[item_id] = merged
        else:
            new_item = dict(new_item)
            if new_item.get("fetched_from"):
                new_item["fetched_at"] = today
            merged_by_id[item_id] = new_item
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
        from sts2.sources import Sts2ggSource, WikiggSource
        primary, secondary = Sts2ggSource(), WikiggSource()

        first = True
        for filename, label in (("cards.json", "cards"),
                                ("relics.json", "relics"),
                                ("potions.json", "potions")):
            if not first:
                time.sleep(_SCRAPE_DELAY)
            first = False

            # Primary source; secondary fills gaps or takes over entirely
            # when the primary fails (see docs/DATA_SOURCES.md)
            records: list[dict] = []
            for source in (primary, secondary):
                fetch = getattr(source, f"fetch_{label}")
                try:
                    print(f"  Fetching {label} from {source.name} ...")
                    fetched = fetch()
                except urllib.error.URLError as e:
                    log.warning("%s failed for %s: %s", source.name, label, e)
                    print(f"    Warning: {source.name} unreachable ({e})")
                    fetched = []
                except Exception as e:
                    log.exception("%s error for %s", source.name, label)
                    print(f"    Warning: {source.name} error ({e})")
                    fetched = []
                for r in fetched:
                    r["fetched_from"] = source.name
                if not records:
                    records = fetched
                elif fetched:
                    # Gap-fill: add entities earlier sources don't know.
                    # Both name AND id must be unknown — a lagging source
                    # listing a renamed entity under its old name generates
                    # the same id and would overwrite the current record
                    # (rename shadow: Follow Through -> Scare, v0.107.1).
                    have = {r["name"].lower() for r in records}
                    have_ids = {r["id"] for r in records}
                    extra = [r for r in fetched
                             if r["name"].lower() not in have
                             and r["id"] not in have_ids]
                    if extra:
                        print(f"    {source.name} filled {len(extra)} missing {label}")
                        records.extend(extra)
                    # Field-level gap-fill: adopt this source's text for
                    # records earlier sources left blank (e.g. cards whose
                    # primary text is an unrenderable template)
                    by_name = {r["name"].lower(): r for r in fetched}
                    filled = 0
                    for r in records:
                        sec = by_name.get(r["name"].lower())
                        if sec and not r.get("description") and sec.get("description"):
                            r["description"] = sec["description"]
                            if not r.get("description_upgraded") and sec.get("description_upgraded"):
                                r["description_upgraded"] = sec["description_upgraded"]
                            filled += 1
                    if filled:
                        print(f"    {source.name} filled text for {filled} {label}")

            if not records:
                log.warning("No %s from any source — keeping existing data", label)
                print(f"    Warning: no {label} from any source — keeping existing data")
                print("    Try 'spirescope update --save-only' instead.")
                continue
            # Guard: don't overwrite large dataset with empty/tiny result
            existing = _existing_count(filename)
            if existing > 20 and len(records) < existing * 0.1:
                log.warning("Sources returned %d %s vs %d existing — possible format change, skipping", len(records), label, existing)
                print(f"    Warning: sources returned only {len(records)} {label} vs {existing} existing, skipping overwrite")
                continue
            merged = _merge_with_existing(filename, records)
            count = _save_json(filename, merged)
            print(f"    Saved {count} {label} ({len(records)} fetched)")
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

    new_badges = _discover_badges_from_saves()
    if new_badges:
        merged = _merge_with_existing("badges.json", new_badges)
        count = _save_json("badges.json", merged)
        print(f"    Discovered {len(new_badges)} new badges (total: {count})")

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


def _discover_badges_from_saves() -> list[dict]:
    """Scan progress.save for earned badges not yet in badges.json."""
    from sts2.config import SAVE_DIR

    existing_ids = set()
    existing_path = DATA_DIR / "badges.json"
    if existing_path.exists():
        try:
            for item in json.loads(existing_path.read_text(encoding="utf-8")):
                existing_ids.add(item.get("id", ""))
        except (json.JSONDecodeError, OSError):
            pass
    progress_path = SAVE_DIR / "progress.save"
    if not progress_path.exists():
        return []
    try:
        data = json.loads(progress_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    discovered = []
    seen = set()
    for cs in data.get("character_stats", []):
        for b in cs.get("badges", []):
            bid = b.get("id", "")
            game_id = f"BADGE.{bid}"
            if not bid or game_id in existing_ids or game_id in seen:
                continue
            seen.add(game_id)
            discovered.append({
                "id": game_id,
                "name": bid.replace("_", " ").title(),
                "requirement": "",
                "source": "discovered",
            })
    return discovered
