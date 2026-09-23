"""Pydantic models for STS2 game entities."""
from pydantic import BaseModel, model_validator

from sts2.card_properties import CardProperties


class Card(BaseModel):
    id: str
    name: str
    name_en: str = ""  # English name, kept when a locale overlay renames this entity
    character: str  # Ironclad, Silent, Defect, Necrobinder, Regent, Colorless, Curse, Status
    cost: str  # "0", "1", "2", "3", "X", "Unplayable"
    # Regent cards spend Stars alongside Energy, so the two costs are separate
    # values, not alternatives. "" means the card has no Star cost.
    star_cost: str = ""
    # Energy cost once upgraded, when upgrading changes it. "" means unchanged;
    # every card the source carries this for genuinely differs (Barricade 3->2).
    cost_upgraded: str = ""
    # True when the card has no upgraded form at all. Distinct from "upgraded
    # text happens to equal the base text", which is what comparing the two
    # strings can tell you and is not the same question.
    no_upgrade: bool = False
    type: str  # Attack, Skill, Power, Status, Curse
    rarity: str  # Starter, Common, Uncommon, Rare, Special
    description: str = ""
    description_upgraded: str = ""
    keywords: list[str] = []
    keywords_upgraded: list[str] | None = None
    instance_rule: str = ""
    instance_note: str = ""
    tier: str = ""  # S, A, B, C, D
    source: str = "base"  # base, mod, discovered
    # Schema v2 — all optional so v1 data files load unchanged
    mp_only: bool = False  # multiplayer-only card
    sp_only: bool = False  # single-player-only card
    mechanics_version: str = ""  # exact version of reviewed card mechanics
    traits_version: str = ""  # reviewed printed costs/type/rarity/player restriction
    branch: str = ""  # main | beta | both ("" = unknown)
    introduced: str = ""  # patch that added it, e.g. "v0.109.0"
    last_changed: str = ""  # patch that last reworked/rebalanced it
    tags: list[str] = []  # e.g. enchantment-interaction keywords
    fetched_from: str = ""  # provenance: source that last changed this record
    fetched_at: str = ""  # provenance: date this record last changed


class Relic(BaseModel):
    mechanics_version: str = ""
    mechanics_note: str = ""
    id: str
    name: str
    name_en: str = ""  # English name, kept when a locale overlay renames this entity
    character: str = "Shared"  # Character-specific or Shared
    rarity: str = ""  # Starter, Common, Uncommon, Rare, Boss, Event, Shop
    description: str = ""
    source: str = "base"
    branch: str = ""
    introduced: str = ""
    last_changed: str = ""
    fetched_from: str = ""
    fetched_at: str = ""


class Potion(BaseModel):
    mechanics_version: str = ""
    usage: str = ""
    target: str = ""
    usage_note: str = ""
    can_generate_in_combat: bool | None = None
    id: str
    name: str
    name_en: str = ""  # English name, kept when a locale overlay renames this entity
    rarity: str = ""  # Common, Uncommon, Rare
    description: str = ""
    source: str = "base"
    branch: str = ""
    introduced: str = ""
    last_changed: str = ""
    fetched_from: str = ""
    fetched_at: str = ""


class Enemy(BaseModel):
    id: str
    name: str
    name_en: str = ""  # English name, kept when a locale overlay renames this entity
    act: list[str] = []  # Which acts they appear in
    type: str = ""  # normal, elite, boss
    hp_range: str = ""  # e.g. "40-44" or "250"
    stats_version: str = ""  # only initial HP; separate from attack-pattern verification
    stats_note: str = ""
    monster_ids: list[str] = []  # declared possible monsters, not simultaneous counts
    roster_version: str = ""
    patterns: list[str] = []  # Description of attack patterns
    tips: list[str] = []  # Strategy tips
    source: str = "base"
    branch: str = ""
    introduced: str = ""
    last_changed: str = ""  # enemy moves can change per patch (era context)
    mechanics_version: str = ""  # exact game version used to verify these mechanics


class Badge(BaseModel):
    id: str
    name: str
    requirement: str = ""  # human-readable earn condition
    source: str = "base"
    requires_win: bool = False
    mp_only: bool = False
    branch: str = ""
    mechanics_version: str = ""


class EventChoice(BaseModel):
    option: str
    outcome: str
    recommendation: str = ""


class Event(BaseModel):
    kind: str = ""
    locations: list[str] = []
    sp_only: bool = False
    mechanics_version: str = ""
    availability_note: str = ""
    is_shared: bool | None = None
    id: str
    name: str
    name_en: str = ""  # English name, kept when a locale overlay renames this entity
    act: list[str] = []
    description: str = ""
    choices: list[EventChoice] = []
    notes: str = ""
    source: str = "base"


class Epoch(BaseModel):
    mechanics_version: str = ""
    mechanics_note: str = ""
    source: str = "base"
    id: str
    name: str
    category: str = ""  # core, character, score, act, ancient, mode
    character: str = ""  # which character this relates to (if any)
    requirement: str = ""  # human-readable unlock condition
    unlocks: list[str] = []  # names of cards/relics/potions/etc unlocked
    unlock_type: str = ""  # cards, relics, potions, character, act, ancient, mode
    status: str = "active"  # active | placeholder | deprecated, version-specific


class SynergyGroup(BaseModel):
    name: str
    description: str = ""
    key_cards: list[str] = []
    key_relics: list[str] = []
    strategy: str = ""


class CharacterStrategy(BaseModel):
    character: str
    description: str = ""
    starting_relic: str = ""
    starting_relic_effect: str = ""
    archetypes: list[SynergyGroup] = []
    general_tips: list[str] = []


class RunFloor(BaseModel):
    floor: int = 0
    type: str = ""  # monster, elite, boss, event, rest, shop, treasure
    encounter: str = ""
    monsters: list[str] = []
    turns: int = 0
    damage_taken: int = 0
    hp_healed: int = 0
    current_hp: int = 0
    max_hp: int = 0
    gold: int = 0
    # None only at construction: old explicit scalar values count as observed.
    gold_observed: bool | None = None
    cards_offered: list[str] = []
    # Every card taken on this floor, in save order. Shops and some fights
    # hand out more than one; the single card_picked kept only the last.
    cards_picked: list[str] = []
    # Legacy convenience for readers that expect one pick: the LAST entry of
    # cards_picked (what the parser always stored here). Kept in sync with
    # cards_picked on construction, so exports from before cards_picked
    # existed still yield their one known pick.
    card_picked: str = ""
    potions_used: list[str] = []
    potions_gained: list[str] = []
    # 1-based act from the save's per-act map_point_history grouping.
    # 0 = unknown (runs parsed or exported before this was recorded); analytics
    # then falls back to estimating the act from the floor number.
    act: int = 0

    @model_validator(mode="after")
    def _sync_picks(self) -> "RunFloor":
        supplied = self.model_fields_set
        if self.gold_observed is None:
            self.gold_observed = "gold" in supplied
        if "cards_picked" not in supplied and self.card_picked:
            self.cards_picked = [self.card_picked]
        elif "card_picked" in supplied and self.card_picked != (self.cards_picked[-1] if self.cards_picked else ""):
            raise ValueError("card_picked must match the final cards_picked entry")
        elif self.cards_picked:
            self.card_picked = self.cards_picked[-1]
        return self


class RunHistory(BaseModel):
    id: str
    character: str
    win: bool
    ascension: int = 0
    seed: str = ""
    acts: list[str] = []
    killed_by: str = ""
    run_time: int = 0
    deck: list[str] = []
    # Per-instance data parallel to `deck` (same length when present; empty =
    # not recorded, e.g. older exports). Upgrade level per card, and the
    # enchantment id per card ("" = none) — the id-keyed `enchantments` dict
    # cannot tell two copies of the same card apart.
    deck_upgrades: list[int] = []
    deck_properties: list[CardProperties | None] = []
    deck_enchantments: list[str] = []
    relics: list[str] = []
    floors: list[RunFloor] = []
    build_id: str = ""
    timestamp: int = 0
    total_players: int = 1
    origin: str = "vanilla"  # save tree the run came from: vanilla | modded
    # card_id -> enchantment id (final deck). Legacy view: with duplicate
    # copies it holds one enchantment per id; deck_enchantments is exact.
    enchantments: dict[str, str] = {}


class CurrentRun(BaseModel):
    active: bool = False
    character: str = ""
    ascension: int = 0  # ghost comparison centers its window on this
    current_hp: int = 0
    max_hp: int = 0
    gold: int = 0
    act: int = 1
    floor: int = 0
    run_time: int = 0
    deck: list[str] = []
    deck_upgrades: list[bool] = []
    deck_properties: list[CardProperties | None] = []
    deck_enchantments: list[str] = []  # parallel to deck: enchantment id or ""
    relics: list[str] = []
    potions: list[str] = []
    events_seen: list[str] = []
    encounters_won: list[str] = []
    floors: list[RunFloor] = []
    player_index: int = 0
    total_players: int = 1
    # The watched player's id as the save records it ("1" in solo, a
    # SteamID64 in co-op). The game log names players by this id, not by
    # seat index, so it is what log telemetry is matched on.
    player_id: str = ""
    # Run seed; lets save and log state be matched to the same run.
    seed: str = ""
    # Supporting session evidence, never a filesystem path/account credential.
    start_time: int = 0
    telemetry_status: str = "unavailable"  # matched, log_only, unavailable, mismatched
    # Combat telemetry from the game log; pydantic silently dropped these
    # before they were declared, so API/SSE consumers never saw them.
    # Save-file-only paths simply leave the defaults.
    cards_played: list[str] = []
    extra_turns: int = 0
    elites_defeated: int = 0


class PlayerProgress(BaseModel):
    total_playtime: int = 0
    character_stats: dict = {}
    card_stats: dict = {}
    encounter_stats: dict = {}
    enemy_stats: dict = {}
    discovered_cards: list[str] = []
    discovered_relics: list[str] = []
    discovered_potions: list[str] = []
    discovered_events: list[str] = []
    epochs: list[dict] = []
    badges: dict = {}  # badge id -> {"bronze": n, "silver": n, "gold": n}
