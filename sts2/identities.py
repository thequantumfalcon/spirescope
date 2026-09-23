"""Explicit compatibility mappings from older catalog IDs to native game IDs.

These mappings were checked against v0.107.1 model definitions and localization.
They do not infer identity from names or suffixes. Unknown and namespaced mod IDs
remain untouched. Native save/export records stay intact; analysis may request a
copy with equivalent catalog identifiers unified.
"""
from collections.abc import Iterable, Mapping
from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from sts2.models import RunHistory

LEGACY_TO_NATIVE = {
    **{f"CARD.{name}_EVENT": f"CARD.{name}" for name in (
        "CALTROPS", "CLASH", "DISTRACTION", "DUAL_WIELD", "ENTRENCH",
        "HELLO_WORLD", "MAD_SCIENCE", "OUTMANEUVER", "REBOUND", "RIP_AND_TEAR", "STACK",
    )},
    **{f"RELIC.{name}_FAKE": f"RELIC.FAKE_{name}" for name in (
        "ANCHOR", "BLOOD_VIAL", "HAPPY_FLOWER", "LEES_WAFFLE", "MANGO",
        "ORICHALCUM", "SNECKO_EYE", "STRIKE_DUMMY", "VENERABLE_TEA_SET",
    )},
    "RELIC.THE_MERCHANTS_RUG_FAKE": "RELIC.FAKE_MERCHANTS_RUG",
    "RELIC.THE_CHOSEN_CHEESE": "RELIC.CHOSEN_CHEESE",
    "POTION.CLARITY_EXTRACT": "POTION.CLARITY",
    "BOSS.AEONGLASS": "MONSTER.AEONGLASS",
}

# Registered monster models that are never enemies (v0.107.1 registry status
# "companion"). Byrdpip and Pael's Legion are pets a relic adds to the
# player's side; Osty is the Necrobinder's pet. The game appends every
# creature with a monster model to the room's monster_ids when it joins a
# combat, whichever side it is on, so these ids do occur in saved history.
# Their initial HP values are placeholders.
COMPANION_MONSTER_IDS = frozenset({"MONSTER.OSTY", "MONSTER.BYRDPIP", "MONSTER.PAELS_LEGION"})

# The ending sequence after the final act (registry status "ending"): an
# event room whose encounter is declared as a Monster room with a creature
# that has no moves and placeholder HP. The score shown as damage numbers is
# a visual effect, not combat damage.
ENDING_MODEL_IDS = frozenset({
    "EVENT.THE_ARCHITECT", "ENCOUNTER.THE_ARCHITECT_EVENT_ENCOUNTER", "MONSTER.ARCHITECT",
})

_T = TypeVar("_T")


def canonical_id(identifier: str) -> str:
    return LEGACY_TO_NATIVE.get(identifier, identifier)


def native_monster_id(identifier: str) -> str:
    """Saved monster_ids may omit the MONSTER. prefix."""
    return identifier if "." in identifier else f"MONSTER.{identifier}"


def is_companion_monster(identifier: str) -> bool:
    """True for a player-side pet recorded among a room's monsters."""
    return canonical_id(native_monster_id(identifier)) in COMPANION_MONSTER_IDS


def is_ending_model(identifier: str) -> bool:
    """True for the Architect ending's event, encounter or creature."""
    return canonical_id(native_monster_id(identifier)) in ENDING_MODEL_IDS


def canonical_ids(identifiers: Iterable[str]) -> list[str]:
    return [canonical_id(identifier) for identifier in identifiers]


def contains_entity(identifiers: Iterable[str], target: str) -> bool:
    target = canonical_id(target)
    return any(canonical_id(identifier) == target for identifier in identifiers)


def identity_index(entries: Mapping[str, _T]) -> dict[str, _T]:
    """Make both spellings readable; an explicit native entry wins collisions.

    Supports both old installed data bundles and newly corrected catalogs.
    This is an index, not an expanded list: aliases never add collection entries.
    """
    result = dict(entries)
    for legacy, native in LEGACY_TO_NATIVE.items():
        if native in entries:
            result[legacy] = entries[native]
        elif legacy in entries:
            result[native] = entries[legacy]
    return result


def canonical_run(run: "RunHistory") -> "RunHistory":
    """Non-mutating projection used for statistical grouping and comparisons."""
    updates: dict[str, Any] = {}
    for field in ("deck", "relics"):
        original = getattr(run, field)
        normalized = canonical_ids(original)
        if normalized != original:
            updates[field] = normalized
    if (killed_by := canonical_id(run.killed_by)) != run.killed_by:
        updates["killed_by"] = killed_by
    floors = []
    for floor in run.floors:
        changes: dict[str, Any] = {}
        for field in ("monsters", "cards_offered", "cards_picked", "potions_used", "potions_gained"):
            original = getattr(floor, field)
            normalized = canonical_ids(original)
            if normalized != original:
                changes[field] = normalized
        for field in ("encounter", "card_picked"):
            original = getattr(floor, field)
            normalized_id = canonical_id(original)
            if normalized_id != original:
                changes[field] = normalized_id
        floors.append(floor.model_copy(update=changes) if changes else floor)
    if any(a is not b for a, b in zip(floors, run.floors)):
        updates["floors"] = floors
    return run.model_copy(update=updates) if updates else run


def canonical_records(records: list[dict], id_field: str = "id") -> dict[str, dict]:
    """Reject competing records that would otherwise collapse silently."""
    result: dict[str, dict] = {}
    for row in records:
        key = canonical_id(row[id_field])
        normalized = dict(row, **{id_field: key})
        if key in result and result[key] != normalized:
            raise ValueError(f"Conflicting records resolve to {key}")
        result[key] = normalized
    return result
