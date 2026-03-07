"""Pydantic models for STS2 game entities."""
from pydantic import BaseModel


class Card(BaseModel):
    id: str
    name: str
    character: str  # Ironclad, Silent, Defect, Necrobinder, Regent, Colorless, Curse, Status
    cost: str  # "0", "1", "2", "3", "X", "Unplayable"
    type: str  # Attack, Skill, Power, Status, Curse
    rarity: str  # Starter, Common, Uncommon, Rare, Special
    description: str = ""
    description_upgraded: str = ""
    keywords: list[str] = []
    tier: str = ""  # S, A, B, C, D


class Relic(BaseModel):
    id: str
    name: str
    character: str = "Shared"  # Character-specific or Shared
    rarity: str = ""  # Starter, Common, Uncommon, Rare, Boss, Event, Shop
    description: str = ""


class Potion(BaseModel):
    id: str
    name: str
    rarity: str = ""  # Common, Uncommon, Rare
    description: str = ""


class Enemy(BaseModel):
    id: str
    name: str
    act: list[str] = []  # Which acts they appear in
    type: str = ""  # normal, elite, boss
    hp_range: str = ""  # e.g. "40-44" or "250"
    patterns: list[str] = []  # Description of attack patterns
    tips: list[str] = []  # Strategy tips


class EventChoice(BaseModel):
    option: str
    outcome: str
    recommendation: str = ""


class Event(BaseModel):
    id: str
    name: str
    act: list[str] = []
    description: str = ""
    choices: list[EventChoice] = []
    notes: str = ""


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
    cards_offered: list[str] = []
    card_picked: str = ""
    potions_used: list[str] = []
    potions_gained: list[str] = []


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
    relics: list[str] = []
    floors: list[RunFloor] = []
    build_id: str = ""


class CurrentRun(BaseModel):
    active: bool = False
    character: str = ""
    current_hp: int = 0
    max_hp: int = 0
    gold: int = 0
    act: int = 1
    floor: int = 0
    run_time: int = 0
    deck: list[str] = []
    deck_upgrades: list[bool] = []
    relics: list[str] = []
    potions: list[str] = []
    events_seen: list[str] = []
    floors: list[RunFloor] = []


class PlayerProgress(BaseModel):
    total_playtime: int = 0
    character_stats: dict = {}
    card_stats: dict = {}
    encounter_stats: dict = {}
    discovered_cards: list[str] = []
    discovered_relics: list[str] = []
    discovered_potions: list[str] = []
    discovered_events: list[str] = []
