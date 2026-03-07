"""Scraper to update game data from slaythespire2.gg. Run: python -m sts2 update"""
import json
import logging
import re
import urllib.request
import urllib.error
from pathlib import Path

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

WIKI_BASE = "https://slaythespire2.gg"
PAGES = {
    "cards": "/cards",
    "relics": "/relics",
    "potions": "/potions",
}

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


def _wiki_id_to_game_id(wiki_id: str, prefix: str) -> str:
    """Convert wiki slug 'bash-ironclad' to game ID 'CARD.BASH'."""
    # Strip character suffix for cards (e.g., 'bash-ironclad' -> 'bash')
    parts = wiki_id.rsplit("-", 1)
    name_part = parts[0] if len(parts) > 1 else wiki_id
    return f"{prefix}.{name_part.upper().replace('-', '_')}"


def _scrape_cards(html: str) -> list[dict]:
    """Parse card data from wiki HTML."""
    raw = _extract_json_objects(html, "CARD")
    cards = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

        character = obj.get("character", "Colorless")
        game_id = _wiki_id_to_game_id(wiki_id, "CARD")

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
    relics = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

        pools = obj.get("relicPools", ["Shared"])
        character = pools[0] if pools else "Shared"

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
    potions = []
    seen = set()
    for obj in raw:
        wiki_id = obj.get("id", "")
        if not wiki_id or wiki_id in seen:
            continue
        seen.add(wiki_id)

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

    # Report files not scraped (enemies, events, strategy are manual)
    print()
    print("  Manual data files (edit directly):")
    for f in sorted(DATA_DIR.glob("*.json")):
        if f.name not in scrapers:
            data = json.loads(f.read_text(encoding="utf-8"))
            print(f"    {f.name}: {len(data)} entries")

    print()
    print("  Done! Restart Spirescope to use updated data.")
    print()
