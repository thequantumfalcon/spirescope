"""Bounded native card properties and exact-build views of customized copies."""
from typing import TYPE_CHECKING, Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

from sts2.identities import canonical_id

if TYPE_CHECKING:
    from sts2.models import Card

_KNOWN = {"CurrentBlock", "IncreasedBlock", "CurrentDamage", "IncreasedDamage",
          "TinkerTimeType", "TinkerTimeRider"}
_Value = Annotated[int, Field(ge=0, le=2147483647)]


class CardProperties(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")

    ints: dict[str, _Value] = Field(default_factory=dict, max_length=6)
    unmodeled: bool = False

    @field_validator("ints")
    @classmethod
    def known_names(cls, value: dict[str, int]) -> dict[str, int]:
        if not value.keys() <= _KNOWN:
            raise ValueError("unsupported card property name")
        return value


def read_card_properties(raw: object) -> CardProperties | None:
    """Read the native SavedProperties shape without retaining arbitrary data.

    A malformed/duplicate value makes the whole property set unavailable.
    Unknown native properties are flagged; they cannot certify a card copy.
    """
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    entries = raw.get("ints", [])
    if not isinstance(entries, list) or len(entries) > 32:
        return None
    values: dict[str, int] = {}
    seen: set[str] = set()
    unmodeled = any(key != "ints" and value not in (None, []) for key, value in raw.items())
    for entry in entries:
        if not isinstance(entry, dict):
            return None
        name, value = entry.get("name"), entry.get("value")
        if not isinstance(name, str) or name in seen or type(value) is not int or not 0 <= value <= 2147483647:
            return None
        seen.add(name)
        if name in _KNOWN:
            values[name] = value
        else:
            unmodeled = True
    return CardProperties(ints=values, unmodeled=unmodeled)


def card_copy(card: "Card", properties: CardProperties | None) -> "Card":
    """Project only reviewed v0.107.1 copy rules; never mutate the catalog."""
    if not card.instance_rule:
        return card
    unavailable = card.model_copy(update={
        "description": "", "description_upgraded": "", "keywords": [], "keywords_upgraded": [],
        "instance_note": "This copy's saved values are unavailable or unsupported; its effects are excluded from advice.",
    })
    if card.mechanics_version != "v0.107.1" or properties is None or properties.unmodeled:
        return unavailable
    values = properties.ints
    identifier = canonical_id(card.id)
    if identifier in {"CARD.GENETIC_ALGORITHM", "CARD.THE_SCYTHE"}:
        block = identifier == "CARD.GENETIC_ALGORITHM"
        current, increased, initial = ("CurrentBlock", "IncreasedBlock", 1) if block else (
            "CurrentDamage", "IncreasedDamage", 13)
        if set(values) != {current, increased} or values[current] != initial + values[increased]:
            return unavailable
        amount = values[current]
        base = f"Gain {amount} Block." if block else f"Deal {amount} damage."
        noun = "Block" if block else "damage"
        gain = 3 if block else 4
        text = base + f" Permanently increase this card's {noun} by {gain}. Exhaust."
        upgraded = base + f" Permanently increase this card's {noun} by {gain + 1}. Exhaust."
        return card.model_copy(update={"description": text, "description_upgraded": upgraded,
                                       "instance_note": "Uses this copy's saved permanent value."})
    if identifier != "CARD.MAD_SCIENCE" or not values.keys() <= {"TinkerTimeType", "TinkerTimeRider"}:
        return unavailable
    kind, rider = values.get("TinkerTimeType"), values.get("TinkerTimeRider", 0)
    allowed = {1: {0, 1, 2, 3}, 2: {0, 4, 5, 6}, 3: {7, 8, 9}}
    if kind not in allowed or rider not in allowed[kind]:
        return unavailable
    effects = {
        0: "", 1: " Apply 2 Weak and 2 Vulnerable.",
        2: "", 3: " This turn, each subsequent card you play makes the target lose 6 HP.",
        4: " Gain 2 Energy.", 5: " Draw 3 cards.",
        6: " Add a random card from your character's pool to your Hand. It is free this turn.",
        7: "Gain 2 Strength and 2 Dexterity.",
        8: "Your Power cards cost 1 less Energy this combat.",
        9: "At the end of combat, permanently upgrade a random upgradeable card in your deck.",
    }
    text = (("Deal 12 damage 3 times." if rider == 2 else "Deal 12 damage.") if kind == 1
            else "Gain 8 Block." if kind == 2 else "") + effects[rider]
    # These are mention tags, consistent with the catalog, not a simulation.
    from sts2.fetcher import _extract_keywords
    return card.model_copy(update={
        "type": {1: "Attack", 2: "Skill", 3: "Power"}[kind],
        "description": text, "description_upgraded": "Innate. " + text,
        "keywords": _extract_keywords(text), "keywords_upgraded": _extract_keywords("Innate. " + text),
        "instance_note": "Uses this copy's saved Tinker Time choices.",
    })
