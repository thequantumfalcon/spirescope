# Spirescope Mod Support

Mod `.json` files add cards, relics, potions and enemies. Spirescope reads them
from its mods directory, not from this one: `STS2_MODS_DIR` if set, otherwise
`mods/` beside the executable in packaged builds, or `mods/` under the state
directory (`STS2_STATE_DIR`) in a source install. Mod files left here by older
versions are moved to `mods/` under the state directory at startup; this README
stays here to document the format.

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

- All entity types (cards, relics, potions, enemies) are optional per file.
- Base game data always takes priority — conflicting IDs are skipped.
- Restart Spirescope or call `POST /api/reload` (needs the `X-Admin-Token`
  header and `SPIRESCOPE_ADMIN_TOKEN` set) after adding files.

## Schema v2 fields (optional)

Cards additionally accept: `mp_only` (bool), `branch` ("main" | "beta" |
"both"), `introduced` (patch version string), `last_changed` (patch version
string), `tags` (list of strings). Relics, potions, and enemies accept
`branch`, `introduced`, `last_changed`. All are optional — v1 mod files load
unchanged.

## Mod namespace (`mod_id`)

Add a top-level `"mod_id": "my-mod"` to a mod file and its entities are
registered under namespaced ids (`mod:my-mod:CARD_NAME`), which can never
collide with base-game ids or other mods. Files without `mod_id` keep their
ids as written (legacy behavior).
