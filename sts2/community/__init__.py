"""Community data scraper: pull tier lists, tips, and meta from Reddit and Steam.

Usage: python -m sts2 community
"""
import json
import logging

from sts2.config import COMMUNITY_SOURCES, DATA_DIR

from ._merge import merge_results
from ._types import (
    SourceResult,
    compute_consensus_tier as _compute_consensus_tier,
    extract_tier_ratings as _extract_tier_ratings,
    extract_tips as _extract_tips,
    STS2_INDICATORS,
)
from .reddit import _is_sts2_post

log = logging.getLogger(__name__)

# Re-exports for backward compatibility (tests import these from sts2.community)
__all__ = [
    "run_community_scraper",
    "save_community_data",
    "apply_community_tiers",
    "scrape_community_data",
    "_compute_consensus_tier",
    "_extract_tier_ratings",
    "_extract_tips",
    "_is_sts2_post",
    "_load_cached_community_data",
]

# Default: all sources enabled. Override with STS2_COMMUNITY_SOURCES env var.
_KNOWN_SOURCES = {"reddit", "steam"}


def _enabled_sources() -> list[str]:
    """Return list of enabled source names."""
    raw = COMMUNITY_SOURCES.strip().lower()
    if raw == "all":
        return sorted(_KNOWN_SOURCES)
    sources = [s.strip() for s in raw.split(",") if s.strip()]
    unknown = set(sources) - _KNOWN_SOURCES
    if unknown:
        log.warning("Unknown community sources ignored: %s", unknown)
    return [s for s in sources if s in _KNOWN_SOURCES]


def scrape_community_data(existing_names: set[str] = None) -> dict:
    """Scrape all enabled sources for STS2 community data.

    Returns dict with: card_tiers, community_tips, meta_posts, sources, etc.
    """
    if existing_names is None:
        existing_names = set()

    enabled = _enabled_sources()
    results: list[SourceResult] = []

    print("\n  Spirescope Community Data Collector")
    print("  ===================================\n")
    print(f"  Sources: {', '.join(enabled)}\n")

    if "reddit" in enabled:
        try:
            from .reddit import scrape as scrape_reddit
            results.append(scrape_reddit(existing_names))
        except Exception as e:
            log.warning("Reddit scraper failed: %s", e)
            print(f"  [Reddit] Failed: {e}")
            results.append(SourceResult(source_name="reddit", errors=[str(e)]))

    if "steam" in enabled:
        try:
            from .steam import scrape as scrape_steam
            results.append(scrape_steam(existing_names))
        except Exception as e:
            log.warning("Steam scraper failed: %s", e)
            print(f"  [Steam] Failed: {e}")
            results.append(SourceResult(source_name="steam", errors=[str(e)]))

    merged = merge_results(results)

    # Print summary
    print(f"\n  Summary:")
    print(f"    {merged['sources']} total items analyzed")
    print(f"    {len(merged['card_tiers'])} entity tier ratings")
    print(f"    {sum(len(v) for v in merged['community_tips'].values())} tips")
    print(f"    {len(merged['meta_posts'])} meta posts")

    for sr in results:
        if sr.errors:
            for err in sr.errors:
                print(f"    Warning [{sr.source_name}]: {err}")

    return merged


def save_community_data(data: dict) -> None:
    """Save community data to disk."""
    path = DATA_DIR / "community.json"
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)
    print(f"\n  Saved community data to {path}")


def apply_community_tiers(community_data: dict) -> None:
    """Apply community tier ratings to cards.json.

    Only updates the 'tier' field on cards that have a community consensus.
    Does NOT overwrite tiers that were already set manually.
    """
    tiers = community_data.get("card_tiers", {})
    if not tiers:
        return

    updated_cards = 0
    cards_path = DATA_DIR / "cards.json"
    if cards_path.exists():
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
        for card in cards:
            name_lower = card.get("name", "").lower().strip()
            if name_lower in tiers and not card.get("tier"):
                card["tier"] = tiers[name_lower]
                updated_cards += 1
        tmp_path = cards_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
        tmp_path.replace(cards_path)

    print(f"  Applied tiers to {updated_cards} cards")


def _load_cached_community_data() -> dict | None:
    """Load previously saved community data as fallback."""
    path = DATA_DIR / "community.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def run_community_scraper():
    """Main entry point: scrape, save, and apply community data."""
    # Build name set from existing data
    existing_names: set[str] = set()
    for filename in ("cards.json", "relics.json", "potions.json", "enemies.json"):
        path = DATA_DIR / filename
        if path.exists():
            for item in json.loads(path.read_text(encoding="utf-8")):
                name = item.get("name", "").lower().strip()
                if name:
                    existing_names.add(name)

    data = scrape_community_data(existing_names)

    # If scrape returned nothing useful, fall back to cached data
    if not data.get("sources") and not data.get("card_tiers"):
        cached = _load_cached_community_data()
        if cached:
            print("\n  Sources unavailable — using cached community data.")
            print("  Restart Spirescope to see existing tiers.\n")
            return

    save_community_data(data)
    apply_community_tiers(data)

    print("\n  Done! Community data collected and applied.")
    print("  Restart Spirescope to see updated tiers.\n")
