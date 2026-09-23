"""Aggregate stats: compute and merge player-sourced data."""
import copy
import hashlib
import json
import logging
import math
from pathlib import Path

from sts2.models import RunHistory
from sts2.persist import write_text_atomic

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
                # Every pick, not just the last: shops and some fights
                # take several cards on one floor.
                for picked_id in floor.cards_picked:
                    cp = card_pick_rates.setdefault(picked_id, {"picked": 0, "offered": 0})
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
        scaled: dict = {}
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

# The two counters each family's entries carry, exactly as
# compute_aggregate_stats writes them: (part, whole).
_FAMILY_COUNTERS = {"card_pick_rates": ("picked", "offered"),
                    "card_win_rates": ("wins", "total"),
                    "relic_win_rates": ("wins", "total"),
                    "character_stats": ("wins", "total"),
                    "ascension_stats": ("wins", "total")}

# Families compute_aggregate_stats counts at most once per run (a card or
# relic once per run it appears in, however many copies), so no entry can
# have been seen in more runs than the file contributes.
_PER_RUN_FAMILIES = ("card_win_rates", "relic_win_rates",
                     "character_stats", "ascension_stats")
# Every run lands in exactly one character and one ascension bucket, so each
# of these families' totals together cannot exceed the run count either.
_PARTITION_FAMILIES = ("character_stats", "ascension_stats")
# Pick counters are per floor, not per run, so the per-run bound does not
# apply to them. They are bounded by the caps the run importer enforces
# instead: at most 500 floors per run and 50 cards offered per floor.
_MAX_FLOORS_PER_RUN = 500
_MAX_OFFERS_PER_FLOOR = 50
# Ceiling for any single counter. Ints are compared directly: math.isfinite()
# converts to float and raised OverflowError on a 400-digit JSON integer.
_MAX_COUNT = 10 ** 12
# How many accepted-import digests the stored aggregate remembers.
_MAX_IMPORT_DIGESTS = 1000


class AggregateImportError(ValueError):
    """An import rejected for a reason the caller may show to the user.

    The message is always fixed text written here, never a fragment of the
    submitted file, so it is safe to return in a response.
    """


class DuplicateImportError(AggregateImportError):
    """The exact same aggregate content has already been merged."""


def _counter(value):
    """Return value if it is a usable counter, else None (0 is usable)."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if 0 <= value <= _MAX_COUNT else None
    if isinstance(value, float) and math.isfinite(value) and 0 <= value <= _MAX_COUNT:
        return value
    return None


def _sanitise_import(imported: dict) -> dict:
    """Reject incomplete or incoherent submitted counters before persistence.

    json.loads succeeding is not validation. A sync server or a hand-crafted
    /api/import/stats body could put a string, null or nested object where a
    count belongs; the merge stored it verbatim, and every later read of the
    community page then failed on it. Accepting bad input is recoverable —
    persisting it is not, since the bad value outlives the request.

    An entry is kept only with both of its family's counters: a character
    entry holding "total" but no "wins" used to be accepted and persisted,
    and then failed the community page's wins/total on every later view.
    Counts impossible for the declared run_count raise AggregateImportError
    instead of being merged at full weight under a tiny run_count.
    """
    clean: dict = {"run_count": 0}
    count = imported.get("run_count", 0)
    # json.loads accepts Infinity/NaN; int(inf) raised an uncaught
    # OverflowError here, turning a hand-crafted import into a 500. Ints are
    # range-checked without a float conversion, which overflowed on huge ones.
    if (isinstance(count, bool) or not isinstance(count, (int, float))
            or (isinstance(count, float) and not math.isfinite(count))):
        raise ValueError("run_count must be a finite number")
    if count < 0 or count != int(count):
        raise AggregateImportError("run_count must be a nonnegative whole number")
    clean["run_count"] = int(count)
    if clean["run_count"] > _MAX_COUNT:
        raise ValueError("run_count must be a finite number")

    for field, (part, whole) in _FAMILY_COUNTERS.items():
        source = imported.get(field)
        if field not in imported:
            continue
        if not isinstance(source, dict):
            raise AggregateImportError("Invalid aggregate counter family.")
        kept: dict = {}
        for key, values in source.items():
            if not isinstance(key, str) or not isinstance(values, dict):
                raise AggregateImportError("Invalid aggregate entry: both finite counters are required.")
            part_n = _counter(values.get(part))
            whole_n = _counter(values.get(whole))
            if part_n is None or whole_n is None:
                raise AggregateImportError("Invalid aggregate entry: both finite counters are required.")
            kept[key] = {part: part_n, whole: whole_n}
        clean[field] = kept

    # Counters must satisfy their own definitions. More wins than runs, or an
    # entry seen in more runs than the file contributes, is manipulated or
    # corrupt data; clamping it still granted it weight, so it is rejected.
    runs = clean["run_count"]
    for field in _PER_RUN_FAMILIES:
        for values in clean.get(field, {}).values():
            if values["wins"] > values["total"]:
                raise AggregateImportError(
                    "Invalid aggregate file: an entry records more wins than runs.")
            if values["total"] > runs:
                raise AggregateImportError(
                    "Invalid aggregate file: an entry appears in more runs than "
                    "the file's run_count.")
    for field in _PARTITION_FAMILIES:
        if sum(v["total"] for v in clean.get(field, {}).values()) > runs:
            raise AggregateImportError(
                "Invalid aggregate file: character or ascension totals add up "
                "to more runs than the file's run_count.")
    for values in clean.get("card_pick_rates", {}).values():
        if (values["offered"] > runs * _MAX_FLOORS_PER_RUN * _MAX_OFFERS_PER_FLOOR
                or values["picked"] > runs * _MAX_FLOORS_PER_RUN):
            raise AggregateImportError(
                "Invalid aggregate file: pick counts are impossible for the "
                "file's run_count.")
        # A pick of a card missing from its floor's offer list is a data
        # quirk rather than manipulation: clamp it instead of rejecting.
        if values["picked"] > values["offered"]:
            values["picked"] = values["offered"]
    return clean


def _import_digest(clean: dict) -> str:
    """Content digest of a sanitised import. Key order and whitespace in the
    submitted file do not change it, so a reformatted copy still matches."""
    canonical = json.dumps(clean, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _stored_digests(existing: dict) -> list:
    digests = existing.get("import_digests") if existing else None
    if not isinstance(digests, list):
        return []
    return [d for d in digests if isinstance(d, str) and len(d) == 64]


def merge_aggregate(existing: dict, imported: dict) -> dict:
    """Weighted merge with anti-manipulation cap.

    Raises DuplicateImportError when the identical content was merged
    before: the merge is additive, so a repeated import counted the same
    runs twice. Distinct files are still merged as before — a content digest
    cannot tell whether two different files share runs.
    """
    imported = _sanitise_import(imported)
    digest = _import_digest(imported)
    seen = _stored_digests(existing)
    if digest in seen:
        raise DuplicateImportError(
            "This aggregate file has already been imported.")
    if len(seen) >= _MAX_IMPORT_DIGESTS:
        raise AggregateImportError("Import ledger is full. Export a backup before resetting community statistics.")
    digests = seen + [digest]
    if not existing or existing.get("run_count", 0) == 0:
        # Apply min-cap even on first import — prevents a malicious first file
        # from seeding massive bogus stats that then anchor the future cap.
        # Scale inner counters too so a 10k-run import doesn't sneak inflated
        # sub-counts through under a clamped run_count.
        imported_count = imported.get("run_count", 0)
        if imported_count > _MIN_IMPORT_CAP and imported_count > 0:
            scale = _MIN_IMPORT_CAP / imported_count
            scaled: dict = {"run_count": _MIN_IMPORT_CAP}
            for field in ("card_pick_rates", "card_win_rates", "relic_win_rates",
                          "character_stats", "ascension_stats"):
                scaled[field] = _scale_subcounts(imported.get(field, {}), scale)
            scaled["import_digests"] = digests
            return scaled
        first = copy.deepcopy(imported)
        first["import_digests"] = digests
        return first

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

    merged["import_digests"] = digests
    return merged


def _repair_stored(data: dict) -> dict:
    """Make a stored aggregate safe to render and merge into.

    Imports are validated before they are persisted, but a file written by an
    older version (or edited by hand) can still hold an entry with a missing
    or non-numeric counter, and one such entry used to fail the community
    page on every view until the file was deleted. Repair rather than
    reject: this is the user's own accumulated state, so incoherent entries
    are dropped and everything else is kept.
    """
    count = _counter(data.get("run_count", 0))
    clean: dict = {"run_count": int(count) if count is not None else 0}
    dropped = 0
    for field, (part, whole) in _FAMILY_COUNTERS.items():
        source = data.get(field)
        if not isinstance(source, dict):
            continue
        kept: dict = {}
        for key, values in source.items():
            part_n = _counter(values.get(part)) if isinstance(values, dict) else None
            whole_n = _counter(values.get(whole)) if isinstance(values, dict) else None
            if not isinstance(key, str) or part_n is None or whole_n is None:
                dropped += 1
                continue
            kept[key] = {part: min(part_n, whole_n), whole: whole_n}
        clean[field] = kept
    if "import_digests" in data:
        clean["import_digests"] = _stored_digests(data)
    if dropped:
        log.warning("Dropped %d incoherent entries from the stored aggregate",
                    dropped)
    return clean


def import_aggregate(imported: dict) -> dict:
    """Commit the merged counters and duplicate ledger in one transaction."""
    from sts2.state_lock import state_lock
    with state_lock(_aggregate_storage_path()):
        merged = merge_aggregate(load_aggregate(), imported)
        if not save_aggregate(merged):
            raise OSError("Aggregate could not be persisted")
        return merged


def load_aggregate() -> dict:
    """Load aggregate from disk, return empty dict if missing or malformed."""
    path = _aggregate_storage_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        # ValueError covers JSONDecodeError and also undecodable bytes and
        # over-long integer literals, which are not JSONDecodeError.
        return {}
    # Valid JSON is not necessarily an aggregate: a top-level array here made
    # every downstream .get() a 500 until the file was hand-deleted.
    return _repair_stored(data) if isinstance(data, dict) else {}


def reset_aggregate() -> bool:
    """Delete aggregate file. Returns True if file was deleted."""
    from sts2.state_lock import state_lock
    path = _aggregate_storage_path()
    with state_lock(path):
        if path.exists():
            path.unlink()
            return True
        return False


def save_aggregate(data: dict) -> bool:
    """Atomic write aggregate to disk. Returns False when nothing was
    persisted (too large, non-finite numbers, or unwritable) so callers can
    say so instead of reporting success for a write that never happened."""
    path = _aggregate_storage_path()
    try:
        content = json.dumps(data, indent=2, allow_nan=False)
    except ValueError:
        log.error("Refusing to persist non-finite numbers to %s", path)
        return False
    if len(content) > 5_000_000:
        log.warning("Aggregate file too large (%d bytes), skipping write", len(content))
        return False
    return write_text_atomic(path, content)
