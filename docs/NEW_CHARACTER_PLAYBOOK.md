# New-character day-one playbook

When Mega Crit ships the confirmed new character, this is the ordered
checklist to full support. Target: same-day release. Every step names its
verification. A dry run against a fake character (all steps below, then
revert) takes well under an hour.

## 0. Prep (before the patch drops)

Nothing to build — the slots below are the only touch points. Skim this doc.

## 1. Config: register the character

`sts2/config.py`:

```python
CHARACTERS = ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent", "<Name>"]
CHARACTER_IDS = {
    ...,
    "CHARACTER.<UPPER_ID>": "<Name>",   # id observed in save files
}
```

The save-file id appears in `current_run.save` / run history as
`character_id` — grab it from the first run (or `python -m sts2 update
--save-only` output). → verify: run history shows the character by name,
not raw id.

## 2. Analytics: official-character allowlist

`sts2/analytics.py`:

```python
OFFICIAL_CHARACTERS = frozenset({..., "<Name>"})
```

→ verify: a run with the character appears in the per-character breakdown
on /analytics.

## 3. Data: fetch the character's cards

`sts2/sources.py` — add the wiki module to `_WIKI_CARD_MODULES`:

```python
"Module:Cards/StS2 data/<Name>",
```

The primary source (slaythespire2.gg) needs no change — it serves all
characters from `/cards`. Character-name normalization: if the site uses a
prefixed form ("The <Name>"), add a mapping next to the existing
`if character == "The Regent"` in `fetcher._scrape_cards`.

Run `python -m sts2 update`. → verify: `python - <<'EOF'` count cards with
the new character in `sts2/data/cards.json`; spot-check 3 descriptions
against the site.

## 4. Rarity canonicalizer

`scripts/fix_card_rarity.py` — add the character's card lists from the wiki
Lua module (`Module:Cards/StS2 data/<Name>`), same `_add(...)` blocks as
the existing characters. Basic → Starter mapping applies.
→ verify: `RARITY:` drift lines in update output are taxonomy-only.

## 5. Strategy entry

`sts2/data/strategy.json` — append:

```json
{
  "character": "<Name>",
  "overview": "…",
  "core_mechanics": ["…"],
  "beginner_tips": ["…"],
  "archetypes": [
    {"name": "<Archetype>", "cards": ["CARD.X", "CARD.Y"],
     "description": "…", "priority": "high"}
  ]
}
```

Archetype seeds power deck analysis + live pick suggestions; 2–3 archetypes
with 4–6 cards each is enough for day one.
→ verify: /strategy/<Name> renders; deck analyzer detects an archetype from
a fixture deck.

## 6. UI color

`sts2/static/style.css` — add a `.char-<name>` color class (lowercase),
mirroring `.char-ironclad` etc. Templates use `char-{{ character|lower }}`
everywhere; a missing class degrades gracefully (default color).
→ verify: character name is tinted on /runs.

## 7. Patch manifest

`sts2/data/patches.json` — append the release patch entry (branch, date,
build id); stamp `introduced` on the character's cards if bulk-tagging is
wanted (optional day-one).
→ verify: `pytest tests/test_patches.py`.

## 8. Tests

Add the character to any test that asserts the CHARACTERS list length (grep
`CHARACTERS` in tests/). Add one run-history fixture with the new
character. → verify: `pytest -q` green.

## 9. Release

CHANGELOG entry, version bump (`sts2/config.py` + `pyproject.toml`), tag
`vX.Y.Z`, push tag (app release), then `git tag data-v$(date +%Y.%m.%d) &&
git push origin data-v...` (data release). → verify: both workflows green;
in-app data banner offers the bundle on an older install.

## Order rationale

1–2 make existing runs display correctly (players have runs before we have
data). 3–5 bring reference data. 6–9 polish + ship. Steps 1–2 alone are a
worthwhile emergency release if the patch lands at a bad time.
