"""Exact-version mechanics and fingerprints for derived translations.

A profile is a reviewed, deliberately bounded set of card mechanics. Missing
cards and unknown versions remain unverified; an identity match is not proof
that the reference catalog describes a particular game build.
"""
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from sts2.game_version import read_game_release
from sts2.identities import canonical_id
from sts2.models import Card, Enemy, Epoch, Event, EventChoice, Potion, Relic

log = logging.getLogger(__name__)


class CardTraits(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = ""  # only a version-specific rename; empty preserves the reference name
    cost: str = Field(pattern=r"^(?:[0-9]+|X|Unplayable|Choice|Unknown)$", max_length=12)
    star_cost: str = Field(pattern=r"^(?:[0-9]+|X)?$", max_length=12)
    cost_upgraded: str = Field(pattern=r"^(?:[0-9]+|X|Unplayable|Choice|Unknown)?$", max_length=12)
    type: Literal["Attack", "Skill", "Power", "Status", "Curse", "Quest", "Variable", "Unknown"]
    rarity: str
    mp_only: bool
    sp_only: bool
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class CardMechanics(CardTraits):
    verification: Literal["native-review", "native-template-alignment"] = "native-review"
    description: str = Field(min_length=1)
    description_upgraded: str
    keywords: list[str]
    keywords_upgraded: list[str] | None = None
    instance_rule: str = ""
    no_upgrade: bool


class PotionMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=1)
    rarity: str
    usage: Literal["CombatOnly", "AnyTime", "Automatic"]
    target: str
    usage_note: str = ""
    can_generate_in_combat: bool
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification: Literal["native-review", "native-template-alignment"]


class RelicMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    description: str = Field(min_length=1)
    rarity: str
    mechanics_note: str = ""
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification: Literal["native-review", "native-template-alignment"]


class MonsterStats(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    hp_base: list[int] = Field(min_length=2, max_length=2)
    hp_ascension_8: list[int] = Field(min_length=2, max_length=2)
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_ranges(self) -> "MonsterStats":
        for lower, upper in (self.hp_base, self.hp_ascension_8):
            if not 1 <= lower <= upper <= 1_000_000:
                raise ValueError("invalid initial monster HP range")
        return self


class EncounterRoster(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    monster_ids: list[str] = Field(min_length=1, max_length=100)
    room_type: Literal["normal", "elite", "boss"]
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def validate_monster_ids(self) -> "EncounterRoster":
        if len(set(self.monster_ids)) != len(self.monster_ids):
            raise ValueError("duplicate possible monster")
        if any(not i.startswith("MONSTER.") or canonical_id(i) != i for i in self.monster_ids):
            raise ValueError("encounters must reference canonical monster identifiers")
        return self


class EpochMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    name: str = Field(min_length=1)
    category: Literal["core", "character", "score", "act", "ancient", "mode"]
    character: str
    requirement: str = Field(min_length=1)
    unlocks: list[str] = Field(min_length=1)
    unlock_type: str
    status: Literal["active", "placeholder"]
    mechanics_note: str
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EventOptionMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    option: str = Field(min_length=1)
    outcome: str = Field(min_length=1)


class EventMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    kind: Literal["event", "ancient"]
    act: list[Literal["Act 1", "Act 2", "Act 3"]] = Field(min_length=1, max_length=3)
    locations: list[str] = Field(min_length=1, max_length=4)
    sp_only: bool

    description: str = Field(min_length=1)
    choices: list[EventOptionMechanics] = Field(min_length=1)
    notes: str
    availability_note: str
    is_shared: bool
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


class EnchantmentMechanics(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    extra_card_text: str = ""
    eligibility: str = Field(min_length=1)
    mechanics_note: str = ""
    definition_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    verification: Literal["native-review"]


class MechanicsProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    game_version: str = Field(pattern=r"^v[0-9]+\.[0-9]+\.[0-9]+$")
    game_commit: str = Field(min_length=1, max_length=128)
    branch: str = Field(pattern=r"^(main|beta)$")
    reviewed_at: str
    complete: Literal[False]
    scope: str
    cards: dict[str, CardMechanics]
    card_traits: dict[str, CardTraits] = {}
    potions: dict[str, PotionMechanics] = {}
    relics: dict[str, RelicMechanics] = {}
    monster_stats: dict[str, MonsterStats] = {}
    encounter_rosters: dict[str, EncounterRoster] = {}
    epochs: dict[str, EpochMechanics] = {}
    events: dict[str, EventMechanics] = {}
    enchantments: dict[str, EnchantmentMechanics] = {}


class MechanicsCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    schema_version: int = Field(ge=1, le=1)
    profiles: list[MechanicsProfile]


def read_profiles(path: Path) -> dict[str, MechanicsProfile]:
    """Validate the whole optional file before exposing any of its records."""
    if not path.exists():
        return {}
    with path.open("rb") as handle:
        raw = handle.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        raise ValueError("mechanics catalog exceeds size limit")
    data = MechanicsCatalog.model_validate_json(raw)
    profiles = {}
    for profile in data.profiles:
        if profile.game_version in profiles:
            raise ValueError("duplicate mechanics version")
        for identifier in profile.cards.keys() | profile.card_traits.keys():
            if not identifier.startswith("CARD.") or canonical_id(identifier) != identifier:
                raise ValueError("mechanics must use canonical card identifiers")
        for identifier in profile.events:
            if not identifier.startswith("EVENT.") or canonical_id(identifier) != identifier:
                raise ValueError("event mechanics must use canonical event identifiers")
        for identifier in profile.epochs:
            if not identifier.endswith("_EPOCH") or not identifier.replace("_", "").isalnum() or identifier != identifier.upper():
                raise ValueError("epoch mechanics must use native timeline identifiers")
        for identifier in profile.encounter_rosters:
            if not identifier.startswith("ENCOUNTER.") or canonical_id(identifier) != identifier:
                raise ValueError("encounter rosters must use canonical encounter identifiers")
        for identifier in profile.monster_stats:
            if not identifier.startswith("MONSTER.") or canonical_id(identifier) != identifier:
                raise ValueError("monster stats must use canonical monster identifiers")
        for identifier in profile.relics:
            if not identifier.startswith("RELIC.") or canonical_id(identifier) != identifier:
                raise ValueError("mechanics must use canonical relic identifiers")
        for identifier in profile.potions:
            if not identifier.startswith("POTION.") or canonical_id(identifier) != identifier:
                raise ValueError("mechanics must use canonical potion identifiers")
        for identifier in profile.enchantments:
            if not identifier.startswith("ENCHANTMENT.") or canonical_id(identifier) != identifier:
                raise ValueError("mechanics must use canonical enchantment identifiers")
        for identifier, mechanics in profile.cards.items():
            traits = profile.card_traits.get(identifier)
            if traits and any(mechanics.model_dump()[key] != value
                              for key, value in traits.model_dump().items()):
                raise ValueError("card traits disagree with complete mechanics")
        profiles[profile.game_version] = profile
    return profiles


def select_game_version(game_dir: Path, profiles: dict[str, MechanicsProfile]) -> str:
    release = read_game_release(game_dir)
    version = release.get("game_version", "")
    profile = profiles.get(version)
    if profile and release.get("game_commit") != profile.game_commit:
        # Same version label, different/missing commit: do not silently apply
        # a reviewed binary's mechanics to an unidentified build.
        return ""
    return version


def apply_card_profile(card: Card, profile: MechanicsProfile | None) -> Card:
    if profile is None or card.source == "mod":
        return card
    identifier = canonical_id(card.id)
    facts = profile.cards.get(identifier)
    traits = profile.card_traits.get(identifier)
    if facts is None and traits is None:
        return card
    selected = facts or traits
    assert selected is not None
    fields = selected.model_dump(exclude={"definition_sha256"})
    if not fields.get("name"):
        fields.pop("name", None)
    fields.update(traits_version=profile.game_version)
    if facts is not None:
        fields.update(mechanics_version=profile.game_version)
    # `branch` describes availability, not which version this view uses.
    # Do not overwrite it with the profile's branch.
    return card.model_copy(update=fields)


def apply_potion_profile(potion: Potion, profile: MechanicsProfile | None) -> Potion:
    if profile is None or potion.source == "mod":
        return potion
    facts = profile.potions.get(canonical_id(potion.id))
    if facts is None:
        return potion
    fields = facts.model_dump(exclude={"definition_sha256", "verification"})
    fields["mechanics_version"] = profile.game_version
    return potion.model_copy(update=fields)


def apply_relic_profile(relic: Relic, profile: MechanicsProfile | None) -> Relic:
    if profile is None or relic.source == "mod":
        return relic
    facts = profile.relics.get(canonical_id(relic.id))
    if facts is None:
        return relic
    fields = facts.model_dump(exclude={"definition_sha256", "verification"})
    fields["mechanics_version"] = profile.game_version
    return relic.model_copy(update=fields)


def apply_monster_stats(enemy: Enemy, profile: MechanicsProfile | None) -> Enemy:
    if profile is None or enemy.source == "mod":
        return enemy
    facts = profile.monster_stats.get(canonical_id(enemy.id))
    if facts is None:
        return enemy

    def label(hp: list[int]) -> str:
        return str(hp[0]) if hp[0] == hp[1] else f"{hp[0]}–{hp[1]}"

    hp_range = label(facts.hp_base)
    if facts.hp_ascension_8 != facts.hp_base:
        hp_range += f" (Ascension 8+: {label(facts.hp_ascension_8)})"
    return enemy.model_copy(update={
        "hp_range": hp_range, "stats_version": profile.game_version,
        "stats_note": "Initial HP before multiplayer scaling, encounter effects and modifiers.",
    })


def apply_enemy_profile(enemy: Enemy, profile: MechanicsProfile | None) -> Enemy:
    enemy = apply_monster_stats(enemy, profile)
    if profile is None or enemy.source == "mod":
        return enemy
    facts = profile.encounter_rosters.get(canonical_id(enemy.id))
    if facts is None:
        return enemy
    return enemy.model_copy(update={
        "monster_ids": list(facts.monster_ids), "roster_version": profile.game_version,
        "type": facts.room_type,
        # An encounter has several possible monsters, not one HP range.
        "hp_range": "", "stats_version": "", "stats_note": "",
    })


def apply_epoch_profile(epoch: Epoch, profile: MechanicsProfile | None) -> Epoch:
    if profile is None or epoch.source == "mod":
        return epoch
    facts = profile.epochs.get(epoch.id)
    if facts is None:
        return epoch
    fields = facts.model_dump(exclude={"definition_sha256"})
    fields["mechanics_version"] = profile.game_version
    return epoch.model_copy(update=fields)


def apply_event_profile(event: Event, profile: MechanicsProfile | None) -> Event:
    if profile is None or event.source == "mod":
        return event
    facts = profile.events.get(canonical_id(event.id))
    if facts is None:
        return event
    fields = facts.model_dump(exclude={"definition_sha256", "choices"})
    fields["choices"] = [EventChoice(**choice.model_dump()) for choice in facts.choices]
    fields["mechanics_version"] = profile.game_version
    return event.model_copy(update=fields)


_TEXT_INPUTS: dict[str, Any] = {
    "description": "", "description_upgraded": "", "cost": "", "star_cost": "",
    "cost_upgraded": "", "type": "", "rarity": "", "keywords": [],
    "no_upgrade": False, "mp_only": False, "sp_only": False,
    "mechanics_version": "", "keywords_upgraded": None, "instance_rule": "",
    "mechanics_note": "",
    "usage": "", "target": "", "usage_note": "", "can_generate_in_combat": None,
}


def mechanics_fingerprint(record: dict) -> str:
    """Pin derived text to the exact English mechanics it was built from.

    Ignore names/provenance timestamps: those do not change the numeric inputs
    or effect being translated. Default missing optional fields consistently
    between source JSON and loaded models.
    """
    inputs = {key: record.get(key, default) for key, default in _TEXT_INPUTS.items()}
    return hashlib.sha256(json.dumps(inputs, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":")).encode()).hexdigest()


def overlay_matches(entry: dict, record: dict, metadata: object, game_version: str) -> bool:
    if not isinstance(metadata, dict) or metadata.get("game_version") != game_version:
        return False
    return entry.get("_mechanics_fingerprint") == mechanics_fingerprint(record)
