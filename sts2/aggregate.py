"""Aggregate stats: compute and merge player-sourced data."""
import json
import logging
from pathlib import Path

from sts2.models import RunHistory

log = logging.getLogger(__name__)

# Anti-manipulation cap: imported run_count clamped to max(existing * 2, 1000)
_MAX_IMPORT_FACTOR = 2
_MIN_IMPORT_CAP = 1000


def _aggregate_storage_path() -> Path:
    """Resolve writable path for aggregate file."""
    import sys

    from sts2.config import DATA_DIR
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "community_aggregate.json"
    return DATA_DIR / "community_aggregate.json"


def compute_aggregate_stats(runs: list[RunHistory]) -> dict:
    """Extract aggregate stats from runs. Excludes PII (seed, id, floors, full decks)."""
    card_pick_rates: dict[str, dict] = {}
    card_win_rates: dict[str, dict] = {}
    relic_win_rates: dict[str, dict] = {}
    character_stats: dict[str, dict] = {}
    ascension_stats: dict[int, dict] = {}

    for run in runs:
        # Character stats
        cs = character_stats.setdefault(run.character, {"wins": 0, "total": 0})
        cs["total"] += 1
        if run.win:
            cs["wins"] += 1

        # Ascension stats
        ast = ascension_stats.setdefault(run.ascension, {"wins": 0, "total": 0})
        ast["total"] += 1
        if run.win:
            ast["wins"] += 1

        # Card win rates (from final deck)
        for card_id in set(run.deck):
            cw = card_win_rates.setdefault(card_id, {"wins": 0, "total": 0})
            cw["total"] += 1
            if run.win:
                cw["wins"] += 1

        # Relic win rates
        for relic_id in set(run.relics):
            rw = relic_win_rates.setdefault(relic_id, {"wins": 0, "total": 0})
            rw["total"] += 1
            if run.win:
                rw["wins"] += 1

        # Card pick rates (from floor data)
        for floor in run.floors:
            if floor.cards_offered:
                for offered_id in floor.cards_offered:
                    if offered_id:
                        cp = card_pick_rates.setdefault(offered_id, {"picked": 0, "offered": 0})
                        cp["offered"] += 1
                if floor.card_picked:
                    cp = card_pick_rates.setdefault(floor.card_picked, {"picked": 0, "offered": 0})
                    cp["picked"] += 1

    return {
        "run_count": len(runs),
        "card_pick_rates": card_pick_rates,
        "card_win_rates": card_win_rates,
        "relic_win_rates": relic_win_rates,
        "character_stats": character_stats,
        "ascension_stats": {str(k): v for k, v in ascension_stats.items()},
    }


def merge_aggregate(existing: dict, imported: dict) -> dict:
    """Weighted merge with anti-manipulation cap."""
    if not existing or existing.get("run_count", 0) == 0:
        return imported

    existing_count = existing.get("run_count", 0)
    imported_count = imported.get("run_count", 0)
    cap = max(existing_count * _MAX_IMPORT_FACTOR, _MIN_IMPORT_CAP)
    if imported_count > cap:
        imported_count = cap

    merged = {"run_count": existing_count + imported_count}

    # Merge dict-of-dicts fields
    for field in ("card_pick_rates", "card_win_rates", "relic_win_rates",
                  "character_stats", "ascension_stats"):
        ex = existing.get(field, {})
        im = imported.get(field, {})
        merged_field = dict(ex)
        for key, vals in im.items():
            if key in merged_field:
                for subkey, subval in vals.items():
                    if isinstance(subval, (int, float)):
                        merged_field[key][subkey] = merged_field[key].get(subkey, 0) + subval
            else:
                merged_field[key] = dict(vals)
        merged[field] = merged_field

    return merged


def load_aggregate() -> dict:
    """Load aggregate from disk, return empty dict if missing."""
    path = _aggregate_storage_path()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def reset_aggregate() -> bool:
    """Delete aggregate file. Returns True if file was deleted."""
    path = _aggregate_storage_path()
    if path.exists():
        path.unlink()
        return True
    return False


def save_aggregate(data: dict) -> None:
    """Atomic write aggregate to disk."""
    path = _aggregate_storage_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2)
    if len(content) > 5_000_000:
        log.warning("Aggregate file too large (%d bytes), skipping write", len(content))
        return
    tmp = path.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)
