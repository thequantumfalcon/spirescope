"""Aggregate stats: compute and merge player-sourced data."""
import copy
import json
import logging
from pathlib import Path

from sts2.models import RunHistory

log = logging.getLogger(__name__)

# Anti-manipulation cap: imported run_count clamped to max(existing * 2, 1000)
_MAX_IMPORT_FACTOR = 2
_MIN_IMPORT_CAP = 1000


def _aggregate_storage_path() -> Path:
    """Resolve writable path for the aggregate file.

    Same location frozen or not: this is user state, and the executable's own
    directory is not reliably writable (an app installed under /Applications or
    Program Files is not). Frozen builds that already wrote next to the
    executable are migrated by config.migrate_state_from_data_dir().
    """
    from sts2.config import state_path
    return state_path("community_aggregate.json")


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


def _scale_subcounts(d: dict, scale: float) -> dict:
    """Scale every numeric sub-counter in a dict-of-dicts by `scale`."""
    out = {}
    for key, vals in d.items():
        if not isinstance(vals, dict):
            out[key] = vals
            continue
        scaled = {}
        any_nonzero = False
        for subkey, subval in vals.items():
            # Exclude bools — they're technically int but should not aggregate.
            if isinstance(subval, bool):
                scaled[subkey] = subval
            elif isinstance(subval, (int, float)):
                # round, not int: truncation sends every counter below 1/scale
                # to zero, which deletes real low-sample data instead of
                # down-weighting it.
                scaled[subkey] = round(subval * scale) if isinstance(subval, int) else subval * scale
                any_nonzero = any_nonzero or scaled[subkey] != 0
            else:
                scaled[subkey] = subval
                any_nonzero = True
        # An entry scaled to all-zeros carries no information; keeping it would
        # accumulate dead keys in the aggregate file across every merge.
        if any_nonzero:
            out[key] = scaled
    return out


_COUNTER_FIELDS = ("card_pick_rates", "card_win_rates", "relic_win_rates",
                   "character_stats", "ascension_stats")


def _sanitise_import(imported: dict) -> dict:
    """Drop anything that is not a numeric counter before it can be persisted.

    json.loads succeeding is not validation. A sync server or a hand-crafted
    /api/import/stats body could put a string, null or nested object where a
    count belongs; the merge stored it verbatim, and every later read of the
    community page then failed on it. Accepting bad input is recoverable —
    persisting it is not, since the bad value outlives the request.
    """
    clean: dict = {"run_count": 0}
    count = imported.get("run_count", 0)
    if isinstance(count, bool) or not isinstance(count, (int, float)):
        raise ValueError("run_count must be a number")
    clean["run_count"] = max(0, int(count))

    for field in _COUNTER_FIELDS:
        source = imported.get(field)
        if not isinstance(source, dict):
            continue
        kept: dict = {}
        for key, values in source.items():
            if not isinstance(key, str) or not isinstance(values, dict):
                continue
            numeric = {k: v for k, v in values.items()
                       if isinstance(k, str) and not isinstance(v, bool)
                       and isinstance(v, (int, float)) and v >= 0}
            if numeric:
                kept[key] = numeric
        clean[field] = kept
    return clean


def merge_aggregate(existing: dict, imported: dict) -> dict:
    """Weighted merge with anti-manipulation cap."""
    imported = _sanitise_import(imported)
    if not existing or existing.get("run_count", 0) == 0:
        # Apply min-cap even on first import — prevents a malicious first file
        # from seeding massive bogus stats that then anchor the future cap.
        # Scale inner counters too so a 10k-run import doesn't sneak inflated
        # sub-counts through under a clamped run_count.
        imported_count = imported.get("run_count", 0)
        if imported_count > _MIN_IMPORT_CAP and imported_count > 0:
            scale = _MIN_IMPORT_CAP / imported_count
            scaled = {"run_count": _MIN_IMPORT_CAP}
            for field in ("card_pick_rates", "card_win_rates", "relic_win_rates",
                          "character_stats", "ascension_stats"):
                scaled[field] = _scale_subcounts(imported.get(field, {}), scale)
            return scaled
        return copy.deepcopy(imported)

    existing_count = existing.get("run_count", 0)
    imported_count = imported.get("run_count", 0)
    cap = max(existing_count * _MAX_IMPORT_FACTOR, _MIN_IMPORT_CAP)
    sub_scale = 1.0
    if imported_count > cap:
        # Scale the inner counters by the same factor the run_count was clamped
        # by, or a 1M-run import sneaks 1M-weight sub-counts in under a capped
        # run_count — the same leak the first-import path already closes.
        sub_scale = cap / imported_count
        imported_count = cap

    merged = {"run_count": existing_count + imported_count}

    # Merge dict-of-dicts fields. Deep-copy nested dicts from `existing` so the
    # caller's in-memory aggregate is not mutated when we add imported counts.
    for field in ("card_pick_rates", "card_win_rates", "relic_win_rates",
                  "character_stats", "ascension_stats"):
        ex = existing.get(field, {})
        im = imported.get(field, {})
        if sub_scale < 1.0:
            im = _scale_subcounts(im, sub_scale)
        merged_field = {k: dict(v) if isinstance(v, dict) else v for k, v in ex.items()}
        for key, vals in im.items():
            if not isinstance(vals, dict):
                continue
            if key in merged_field and isinstance(merged_field[key], dict):
                for subkey, subval in vals.items():
                    # Exclude bools — isinstance(True, int) is True.
                    if isinstance(subval, bool):
                        continue
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
