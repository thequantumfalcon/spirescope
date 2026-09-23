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

# App-curated pseudo-categories; sources file these cards under Colorless,
# so a scrape must never overwrite them (see _merge_with_existing)
_CURATED_CHARACTERS = {"Curse", "Status", "Token", "Event", "Quest"}

WIKI_BASE = "https://slaythespire2.gg"
# Per their robots.txt: general scraping is permitted; /api, /admin,
# /analysis, /planner are disallowed and we never request them.
_SCRAPE_DELAY = 1.0  # seconds between wiki requests to avoid hammering
_MAX_RESPONSE_SIZE = 10_000_000  # 10 MB — a wiki page should never be this large

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


# Matches a surrogate pair first so astral characters recombine, then any lone
# \uXXXX escape.
_UNICODE_ESCAPE_RE = re.compile(
    r"\\u([dD][89abAB][0-9a-fA-F]{2})\\u([dD][c-fC-F][0-9a-fA-F]{2})"
    r"|\\u([0-9a-fA-F]{4})")


def _decode_unicode_escapes(text: str) -> str:
    r"""Resolve \uXXXX escapes without touching literal non-ASCII text.

    The obvious `text.encode().decode("unicode_escape")` round-trips UTF-8
    bytes through latin-1, so every real non-ASCII character in the payload is
    mangled — a curly quote (U+201C) came out as "â". That
    shipped: three relic descriptions rendered "Cards containing
    âStrikeâ". A previous cleanup repaired the
    data file but not this function, so the next refresh reproduced it exactly.
    """
    def _replace(match):
        high, low, solo = match.group(1), match.group(2), match.group(3)
        if solo is not None:
            return chr(int(solo, 16))
        return chr(0x10000 + ((int(high, 16) - 0xD800) << 10) + (int(low, 16) - 0xDC00))

    return _UNICODE_ESCAPE_RE.sub(_replace, text)


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
    # spaces: shipped descriptions must be single-line and single-spaced, or
    # they break layout wherever they are rendered inline. Regression: v2.2.1
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
    # URL is always WIKI_BASE (hardcoded https) + path — no file:/custom schemes.
    with urllib.request.urlopen(req, timeout=30) as resp:  # nosec B310
        body = resp.read(_MAX_RESPONSE_SIZE + 1)
        if len(body) > _MAX_RESPONSE_SIZE:
            raise urllib.error.URLError(
                f"Response for {path} too large (> {_MAX_RESPONSE_SIZE} bytes)")
        return body.decode("utf-8")


def _scan_json_objects(content: str, category: str, results: list, seen_ids: set):
    """Decode objects with JSON's own string/brace rules, with bounded input."""
    decoder = json.JSONDecoder()
    # A failed candidate costs at most 128 KiB; a successful enclosing object
    # is walked once and skipped rather than repeatedly reparsed.
    cursor = 0
    while True:
        start = content.find("{", cursor)
        if start < 0:
            return
        try:
            obj, end = decoder.raw_decode(content[start:start + 131072])
        except (ValueError, RecursionError):
            cursor = start + 1
            continue
        _walk_json_for_category(obj, category, results, seen_ids)
        cursor = start + end


def _extract_json_objects(html: str, category: str) -> list[dict]:
    results: list[dict] = []
    seen_ids: set = set()
    _scan_json_objects(html, category, results, seen_ids)
    # A partial inline result must not hide the streamed remainder.
    _extract_from_rsc_payloads(html, category, results, seen_ids)
    if not results:
        log.warning("All extraction strategies found 0 for %s", category)
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
    chunks = []
    for raw in raw_chunks:
        try:
            chunks.append(json.loads('"' + raw + '"', strict=False))
        except ValueError:
            log.warning("Invalid RSC string literal; refusing partial stream")
            return
    _scan_json_objects("".join(chunks), category, results, seen_ids)


def _norm_name(name) -> str:
    """Display name as a matching key: case- and whitespace-insensitive."""
    return " ".join(str(name).lower().split())


def _load_existing_records(filename: str) -> list[dict]:
    path = DATA_DIR / filename
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    return [item for item in data if isinstance(item, dict)] if isinstance(data, list) else []


def _load_existing_name_index(filename: str, prefix: str) -> dict[str, str]:
    """Build a name->id lookup from existing data to match wiki items.

    A name carried by more than one record is left out rather than resolved
    last-wins: a shared name is not an identity, and guessing attached one
    entity's update to another. No entry means no match.
    """
    index: dict[str, str] = {}
    ambiguous: set[str] = set()
    for item in _load_existing_records(filename):
        name = _norm_name(item.get("name", ""))
        item_id = item.get("id", "")
        if name and item_id:
            if index.get(name, item_id) != item_id:
                ambiguous.add(name)
            index[name] = item_id
    for name in ambiguous:
        del index[name]
    return index


def _load_existing_card_index() -> dict[tuple[str, str], str]:
    """(normalized name, character) -> id for the existing cards.

    Name alone is not a card's identity: five characters each have a Strike
    and a Defend, and Apotheosis exists as both a Colorless and an Event card.
    Keyed by name only, every Strike resolved to whichever came last
    (CARD.STRIKE_SILENT). Pairs shared by several records are left out.

    Sources file the app-curated pseudo-categories (Curse, Status, Event, ...)
    under Colorless, so a name that identifies exactly one record, and that
    record is curated, is also indexed under (name, "") as a fallback.
    """
    index: dict[tuple[str, str], str] = {}
    ambiguous: set[tuple[str, str]] = set()
    by_name: dict[str, list[dict]] = {}
    for item in _load_existing_records("cards.json"):
        name = _norm_name(item.get("name", ""))
        item_id = item.get("id", "")
        if not (name and item_id):
            continue
        by_name.setdefault(name, []).append(item)
        key = (name, str(item.get("character", "")))
        if index.get(key, item_id) != item_id:
            ambiguous.add(key)
        index[key] = item_id
    for key in ambiguous:
        del index[key]
    for name, items in by_name.items():
        if len(items) == 1 and items[0].get("character") in _CURATED_CHARACTERS:
            index[(name, "")] = items[0]["id"]
    return index


def _match_existing_card(index: dict[tuple[str, str], str], name: str,
                         character: str) -> str:
    """The existing card id for this name and character, or "" for no match."""
    key = _norm_name(name)
    return index.get((key, character)) or index.get((key, ""), "")


def _suffix_colliding_fallbacks(records: list[dict], unmatched: list[bool]) -> None:
    """Give unmatched records whose derived id collides a character suffix.

    Ids derived from a name or slug drop the character, so with no existing
    record to match, all five Strikes derive CARD.STRIKE. The app's own ids
    carry the character for exactly these cards (CARD.STRIKE_IRONCLAD).
    """
    counts: dict[str, int] = {}
    for r in records:
        counts[r["id"]] = counts.get(r["id"], 0) + 1
    for r, fallback in zip(records, unmatched):
        character = str(r.get("character", ""))
        if fallback and r["id"] in {"CARD.STRIKE", "CARD.DEFEND"} and character:
            suffix = re.sub(r"[^A-Z0-9]+", "_", character.upper()).strip("_")
            r["id"] = f"{r['id']}_{suffix}"


def _drop_identity_collisions(records: list[dict], source: str, label: str) -> list[dict]:
    """Remove every record whose id another record in the same batch shares.

    Two records resolving to one id means the join could not tell them apart
    (wiki.gg lists nine "Mad Science (...)" variants that all reduce to the
    one Mad Science card). Keeping either would be last-wins by another name,
    so neither updates anything.
    """
    counts: dict[str, int] = {}
    for r in records:
        counts[r["id"]] = counts.get(r["id"], 0) + 1
    colliding = sorted(i for i, n in counts.items() if n > 1)
    if not colliding:
        return records
    log.warning("%s: %d %s ids are ambiguous, skipping them: %s",
                source, len(colliding), label, ", ".join(colliding))
    print(f"    {source}: skipped {len(colliding)} ambiguous {label} ids")
    return [r for r in records if counts[r["id"]] == 1]


_CHARACTER_SUFFIXES = {
    "ironclad", "silent", "defect", "necrobinder", "the-regent", "regent",
    "colorless", "curse", "status",
}



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
    # Build (name, character)->id index from existing data for matching
    card_index = _load_existing_card_index()
    cards = []
    unmatched: list[bool] = []
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
        # Prefer matching by name and character against existing data to
        # avoid ID mismatches
        game_id = _match_existing_card(card_index, name, character)
        unmatched.append(not game_id)
        if not game_id:
            game_id = _wiki_id_to_game_id(wiki_id, "CARD", character)

        # Determine cost string. The site marks X costs explicitly (costsX,
        # with energy 0 or absent) and has no flag for Unplayable, so a
        # missing energy value is unknown, not Unplayable: "" lets the merge
        # keep the existing cost and lets the secondary fill it. Reading
        # absence as Unplayable is how ten X-cost cards (Whirlwind, Skewer,
        # ...) shipped as Unplayable.
        energy = obj.get("energy")
        if obj.get("costsX") is True:
            cost = "X"
        elif energy is None:
            cost = ""
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

        card = {
            "id": game_id,
            "name": obj.get("name", ""),
            "character": character,
            "cost": cost,
            "type": card_type,
            "rarity": obj.get("rarity", ""),
            "description": desc,
            "description_upgraded": desc_upgraded,
            "keywords": keywords,
        }
        # Star cost only when the site states one (costsStarX: Stardust;
        # starCost: Resonance). Leaving the key out otherwise keeps "absent"
        # distinct from "none", so the secondary can still supply it.
        if obj.get("costsStarX") is True:
            card["star_cost"] = "X"
        elif isinstance(obj.get("starCost"), int):
            card["star_cost"] = str(obj["starCost"])
        cards.append(card)

    _suffix_colliding_fallbacks(cards, unmatched)
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


def _check_source_compatibility(first: dict, second: dict, *, joining: bool = True) -> None:
    """Reject known incompatible mechanics; absent metadata stays unknown."""
    left, right = first.get("branch"), second.get("branch")
    if left in {"main", "beta"} and right in {"main", "beta"} and left != right:
        raise ValueError(f"Conflicting source branches for {first.get('id')}: {left} / {right}")
    # Different change revisions may update the installed record, but must
    # not supply different halves of a single merged source record.
    if joining and first.get("last_changed") and second.get("last_changed"):
        if first["last_changed"] != second["last_changed"]:
            raise ValueError(f"Conflicting source revisions for {first.get('id')}")


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
            _check_source_compatibility(old, new_item, joining=False)
            merged = dict(old)
            changed = False
            for k, v in new_item.items():
                if k in _PROVENANCE_FIELDS:
                    continue
                old_v = old.get(k)
                # Only preserve old value when new is empty/None and old has content
                if k in {"description", "description_upgraded", "cost", "name", "rarity", "character"} and v in (None, "") and old_v not in (None, ""):
                    continue
                # Pseudo-categories (Curse/Status/Token/Event/Quest) are app-curated;
                # no source can express them (the wiki files these cards under
                # Colorless), so a source may never overwrite one
                if k == "character" and old_v in _CURATED_CHARACTERS:
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


def _fetch_with_retry(path: str, retries: int = 2) -> str:  # type: ignore[return]
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


def _refresh_staged(save_only: bool = False):
    """Scrape game data and update local JSON files.

    Args:
        save_only: If True, skip wiki fetching and only discover from saves.
    """
    refreshed = 0
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
                fetched = _drop_identity_collisions(fetched, source.name, label)
                for r in fetched:
                    r["fetched_from"] = source.name
                if not records:
                    records = fetched
                elif fetched:
                    # Identity joins are shared across adapters. A known zero
                    # or false is data, while an omitted field is unknown.
                    by_id = {r["id"]: r for r in records}
                    for sec in fetched:
                        current = by_id.get(sec["id"])
                        if current is None:
                            records.append(sec)
                            by_id[sec["id"]] = sec
                            continue
                        _check_source_compatibility(current, sec)
                        for field, value in sec.items():
                            missing = field not in current
                            if field in {"description", "description_upgraded", "cost"}:
                                missing = not current.get(field)
                            if missing:
                                current[field] = value
                        if "keywords" in current:
                            current["keywords"] = _extract_keywords(current.get("description", ""))

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
            refreshed += 1
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
            count = len(data) if isinstance(data, list) else f"dict ({len(data)} keys)"  # type: ignore[assignment]
            print(f"    {f.name}: {count} entries")
        except (json.JSONDecodeError, OSError) as exc:
            print(f"    {f.name}: ERROR reading ({exc})")

    return refreshed


def run_fetcher(save_only: bool = False):
    """Stage a complete refresh, validate it, then swap with rollback.

    last_updated is the installed bundle's date, not a network-attempt time.
    Source attempts therefore cannot suppress a newer verified bundle.
    """
    import shutil

    from sts2.data_health import inspect_dataset
    from sts2.persist import write_json_atomic
    from sts2.updater import (
        _acquire_lock,
        _backup_dir,
        _fsync_tree,
        _lock_path,
        _release_lock,
        _staging_dir,
    )

    global DATA_DIR
    live = DATA_DIR
    live.parent.mkdir(parents=True, exist_ok=True)
    lock = _lock_path(live)
    fd = _acquire_lock(lock)
    if fd is None:
        raise RuntimeError("Another data update is already running.")
    staged = _staging_dir(live)
    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "source": "saves" if save_only else "wiki", "installed": False}
    try:
        shutil.copytree(live, staged)
        DATA_DIR = staged
        refreshed = _refresh_staged(save_only)
        if not save_only and refreshed != 3:
            raise ValueError("Refresh incomplete: all three source families must succeed; no changes installed.")
        if not save_only:
            from sts2.corrections import text
            text.main(dry_run=False, data_path=staged / "cards.json")
        health = inspect_dataset(staged)
        if not health["ok"]:
            raise ValueError("Refresh rejected: " + "; ".join(health["errors"]))
        report["content_digest"] = health["content_digest"]
        before = inspect_dataset(live)
        if before["content_digest"] != health["content_digest"]:
            _fsync_tree(staged)
            backup = _backup_dir(live)
            if backup.exists():
                shutil.rmtree(backup)
            live.rename(backup)
            try:
                staged.rename(live)
            except OSError:
                backup.rename(live)
                raise
            report["installed"] = True
        return report
    except Exception as exc:
        report["error"] = str(exc)[:500]
        raise
    finally:
        DATA_DIR = live
        if staged.exists():
            shutil.rmtree(staged)
        write_json_atomic(live.parent / (live.name + ".refresh.json"), report)
        _release_lock(lock, fd)


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
