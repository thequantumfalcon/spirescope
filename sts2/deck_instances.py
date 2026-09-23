"""Positional card copies. Unknown upgrade/enchantment metadata stays unknown."""
from pydantic import BaseModel, ConfigDict, Field

from sts2.card_properties import CardProperties


class DeckInstance(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    card_id: str = Field(min_length=1, max_length=200)
    upgrade_level: int | None = Field(default=None, ge=0, le=10000)
    properties: CardProperties | None = None
    enchantment: str | None = Field(default=None, max_length=200)


def instances_from_run(run) -> list[dict]:
    upgrades = run.deck_upgrades
    enchantments = run.deck_enchantments
    return [DeckInstance(
        card_id=card_id,
        upgrade_level=int(upgrades[i]) if len(upgrades) == len(run.deck) else None,
        properties=run.deck_properties[i] if len(run.deck_properties) == len(run.deck) else None,
        enchantment=enchantments[i] if len(enchantments) == len(run.deck) else None,
    ).model_dump() for i, card_id in enumerate(run.deck)]
