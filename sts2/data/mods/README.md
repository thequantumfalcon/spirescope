# Spirescope Mod Support

Place `.json` files in this directory to add mod cards, relics, and enemies.

## File Format

```json
{
  "mod_name": "Example Mod",
  "cards": [
    {
      "id": "MOD.CARD_NAME",
      "name": "Card Name",
      "character": "Ironclad",
      "cost": "1",
      "type": "Attack",
      "rarity": "Common",
      "description": "Deal 10 damage.",
      "keywords": ["Block"]
    }
  ],
  "relics": [
    {
      "id": "MOD.RELIC_NAME",
      "name": "Relic Name",
      "rarity": "Common",
      "description": "Does something cool."
    }
  ],
  "enemies": [
    {
      "id": "MOD.ENEMY_NAME",
      "name": "Enemy Name",
      "act": ["1"],
      "type": "normal",
      "hp_range": "40-50",
      "patterns": ["Attacks for 10 damage"],
      "tips": ["Block early"]
    }
  ]
}
```

## Notes

- All entity types (cards, relics, enemies) are optional per file.
- Base game data always takes priority — conflicting IDs are skipped.
- Restart Spirescope or call `POST /api/reload` after adding files.
