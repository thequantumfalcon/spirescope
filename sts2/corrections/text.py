"""Pin card text the wiki has not caught up on, from official patch notes.

slaythespire2.gg is the primary source for card text, and it lags the game.
After the v0.111.0 scrape three cards were still serving superseded text, and
one of them -- Expect a Fight -- was served text from *before* v0.109.0, so the
refresh actively reintroduced a clause that patch had removed. Nothing in the
pipeline noticed, because a scrape that returns a plausible string looks
exactly like a correct one.

This runs after a wiki refresh, alongside fix_card_rarity, and re-pins those
fields from the published patch notes.

An override is not a blind assignment. Each one records the stale value it
expects to find, which gives three outcomes:

  stale     the field still matches `expect`      -> apply the fix
  caught-up the field already matches `replace`   -> no-op, and say so, because
                                                     the override can be retired
  drifted   the field matches neither             -> REFUSE and warn

The drifted case is the whole point. A later patch will change these cards
again, and an override that overwrote whatever it found would silently pin the
game to a version two patches old -- the same failure it exists to correct, but
harder to see because it would look deliberate. Refusing forces a human to
re-read the notes.

`verbatim` records whether the replacement text is quoted from the notes or
reconstructed from them. Reconstructed entries are printed separately: the
mechanical change is certain, the exact in-game phrasing is not.

Not representable here: v0.111.0 also changed Regent Star costs (Alignment
3 -> 2, Guiding Star 2 -> 1). A card record has `cost` but no star field, so
there is nothing to pin -- that needs a schema change, not an override.

Usage:
    python scripts/fix_card_text.py            # apply
    python scripts/fix_card_text.py --dry-run  # report only
"""
import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
CARDS_PATH = Path(__file__).resolve().parents[1] / "data" / "cards.json"

# Each entry: the card, where the correction comes from, the stale value it
# replaces, and the value to write. Keys in `expect` and `replace` are card
# fields; every key in `expect` must also appear in `replace`.
OVERRIDES: list[dict] = [
    {
        "id": "CARD.EXPECT_A_FIGHT",
        "source": "v0.111.0 (2026-08-14)",
        "verbatim": True,
        "note": (
            'Reworked: "Uncommon - Skill - Cost 3 - Gain 15(16) Block. Gains '
            '5(8) additional Block for each Strength you have." The wiki still '
            "serves the pre-v0.109.0 text, which v0.109.0 had already removed "
            'the "cannot gain additional Energy" clause from.'
        ),
        "expect": {
            "cost": "2",
            # The wiki still carries the pre-rework upgrade discount (2 -> 1).
            # Pinning the base cost without this one would leave the card
            # claiming an upgraded cost lower than its own base.
            "cost_upgraded": "1",
            "description": (
                "Gain 1 Energy for each Attack in your Hand. You cannot gain "
                "additional Energy this turn"
            ),
            "description_upgraded": (
                "Gain 1 Energy for each Attack in your Hand. You cannot gain "
                "additional Energy this turn"
            ),
        },
        "replace": {
            "cost": "3",
            # v0.111.0 gives one cost, "Cost 3", with the upgrade changing only
            # the Block numbers -- so upgrading no longer changes the cost.
            "cost_upgraded": "",
            "description": (
                "Gain 15 Block. Gains 5 additional Block for each Strength you have."
            ),
            "description_upgraded": (
                "Gain 16 Block. Gains 8 additional Block for each Strength you have."
            ),
        },
    },
    {
        "id": "CARD.BRIGHTEST_FLAME",
        "source": "v0.111.0 (2026-08-14)",
        "verbatim": True,
        "note": "Nerfed: max HP loss increased from 1 -> 2.",
        "expect": {
            "description": "Gain 2 Energy. Draw 2 cards. Lose 1 Max HP.",
            "description_upgraded": "Gain 3 Energy. Draw 3 cards. Lose 1 Max HP.",
        },
        "replace": {
            "description": "Gain 2 Energy. Draw 2 cards. Lose 2 Max HP.",
            "description_upgraded": "Gain 3 Energy. Draw 3 cards. Lose 2 Max HP.",
        },
    },
    {
        "id": "CARD.GUIDING_STAR",
        "source": "v0.111.0 (2026-08-14)",
        "verbatim": False,
        "note": (
            "Changed: card draw moved from this turn to next turn. The notes "
            "state the effect, not the string, so the replacement is "
            "reconstructed -- but the wording is not invented. The game's own "
            "English localisation carries, for Predator, "
            '"Deal {Damage:diff()} damage.\\nNext turn, draw 2 cards." -- the '
            "same two clauses in the same order, and the second identical "
            "character for character to what is written here. Glow and Relax "
            'use the same "Next turn, draw N cards" form. Checked against the '
            "installed game rather than against the wiki, so it is the game's "
            "phrasing and not a scrape of someone's description of it.\n"
            "Unconfirmed, and the only reason verbatim stays False: that "
            "v0.111.0 chose this form for THIS card. Its own string in the "
            "installed build is still the pre-rework one, because stable has "
            "not taken v0.111.0. Re-check once an install carries it."
        ),
        "expect": {
            "description": "Deal 12 damage. Draw 2 cards.",
            "description_upgraded": "Deal 13 damage. Draw 3 cards.",
        },
        "replace": {
            "description": "Deal 12 damage. Next turn, draw 2 cards.",
            "description_upgraded": "Deal 13 damage. Next turn, draw 3 cards.",
        },
    },
]


def classify(card: dict, override: dict) -> str:
    """'stale', 'caught-up', or 'drifted' for this card against this override."""
    if all(card.get(k) == v for k, v in override["expect"].items()):
        return "stale"
    if all(card.get(k) == v for k, v in override["replace"].items()):
        return "caught-up"
    return "drifted"


def apply_overrides(cards: list[dict], overrides: list[dict] | None = None
                    ) -> tuple[list[str], list[str], list[str]]:
    """Apply every override in place. Returns (applied, caught_up, drifted)."""
    overrides = OVERRIDES if overrides is None else overrides
    by_id: dict[str, dict] = {c["id"]: c for c in cards if "id" in c}
    applied, caught_up, drifted = [], [], []
    for ov in overrides:
        card = by_id.get(ov["id"])
        if card is None:
            drifted.append(f"{ov['id']}: not present in cards.json")
            continue
        state = classify(card, ov)
        if state == "stale":
            for key, value in ov["replace"].items():
                card[key] = value
            mark = "" if ov.get("verbatim", True) else "  [wording reconstructed]"
            applied.append(f"{ov['id']} ({ov['source']}){mark}")
        elif state == "caught-up":
            # cards.json cannot say which: a fresh scrape whose wiki text is now
            # correct looks identical to a file this override already fixed.
            # Only a scrape followed immediately by --dry-run distinguishes them.
            caught_up.append(f"{ov['id']}: already correct (wiki caught up, or this ran)")
        else:
            fields = ", ".join(
                f"{k}={card.get(k)!r}" for k in ov["expect"] if card.get(k) != ov["expect"][k]
            )
            drifted.append(
                f"{ov['id']}: matches neither the stale nor the corrected text "
                f"-- NOT applied. Now: {fields}"
            )
    return applied, caught_up, drifted


def main(dry_run: bool = False, data_path: Path | None = None) -> int:
    cards_path = data_path or CARDS_PATH
    cards = json.loads(cards_path.read_text(encoding="utf-8"))
    applied, caught_up, drifted = apply_overrides(cards)

    for line in applied:
        print(f"  TEXT PINNED: {line}")
    for line in caught_up:
        print(f"  UP TO DATE:  {line}")
    for line in drifted:
        print(f"  ::warning::DRIFTED: {line}", file=sys.stderr)

    if applied and not dry_run:
        cards_path.write_text(
            json.dumps(cards, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        print(f"  Wrote {len(cards)} cards to {CARDS_PATH}")
    elif not applied:
        print("  No card text needed pinning.")

    # Drift is a warning, not a failure: a refresh should still complete, and
    # the operator sees the line. Exit non-zero only when asked to check.
    return 1 if (drifted and dry_run) else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="report without writing; exit 1 if any override drifted")
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
