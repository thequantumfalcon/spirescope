"""The Graveyard — procedural epitaphs for dead runs."""
import hashlib

from sts2.models import RunHistory


def generate_epitaph(run: RunHistory, kb=None) -> str:
    """Generate a procedural epitaph for a dead run.

    Deterministic: same run ID always produces the same epitaph.
    Returns empty string for winning runs.
    """
    if run.win:
        return ""

    facts = _collect_facts(run, kb)
    templates = _get_templates(facts)
    if not templates:
        return _fallback_epitaph(run)

    seed = int(hashlib.md5(run.id.encode()).hexdigest()[:8], 16)
    return templates[seed % len(templates)]


def _collect_facts(run: RunHistory, kb) -> dict:
    """Extract notable facts from a run for epitaph generation."""
    facts = {}
    last_floor = run.floors[-1].floor if run.floors else 0

    # Potion hoarding
    total_gained = sum(len(f.potions_gained) for f in run.floors)
    total_used = sum(len(f.potions_used) for f in run.floors)
    if total_gained >= 3 and total_used == 0:
        facts["potion_hoarder"] = total_gained
    elif total_gained >= 4 and total_used <= 1:
        facts["potion_miser"] = (total_gained, total_used)

    # Deck size extremes
    deck_size = len(run.deck)
    if deck_size > 40:
        facts["bloated_deck"] = deck_size
    elif deck_size <= 12 and last_floor > 10:
        facts["tiny_deck"] = deck_size

    # Starter cards still in deck
    starters = sum(1 for c in run.deck if "STRIKE" in c or "DEFEND" in c)
    if starters >= 8 and last_floor > 15:
        facts["never_removed_starters"] = starters

    # Instant death
    if last_floor <= 5:
        facts["instant_death"] = last_floor

    # Boss death
    if run.floors and run.floors[-1].type == "boss":
        boss_name = run.killed_by.replace("ENCOUNTER.", "").replace("_", " ").title() if run.killed_by else "the boss"
        facts["boss_death"] = boss_name

    # Marathon
    if run.run_time > 3600:
        facts["marathon"] = run.run_time // 60

    # Speedrun death (fast run that got far)
    if run.run_time < 300 and last_floor > 10:
        facts["speedrun_death"] = run.run_time // 60

    # High damage taken on death floor
    if run.floors and run.floors[-1].damage_taken > 50:
        facts["overkill"] = run.floors[-1].damage_taken

    # Died with lots of gold
    if run.floors and run.floors[-1].gold > 200:
        facts["died_rich"] = run.floors[-1].gold

    # Got very far but still lost
    if last_floor >= 40:
        facts["so_close"] = last_floor

    # All attacks, no defense
    if deck_size > 10:
        attack_count = 0
        for cid in run.deck:
            if kb:
                card = kb.get_card_by_id(cid)
                if card and card.type == "Attack":
                    attack_count += 1
        if attack_count > deck_size * 0.7:
            facts["all_attacks"] = attack_count

    return facts


def _get_templates(facts: dict) -> list[str]:
    """Generate epitaph options from collected facts."""
    templates = []

    if "potion_hoarder" in facts:
        n = facts["potion_hoarder"]
        templates.append(f"Had {n} potions. Used none of them.")
        templates.append(f"Collected {n} potions for a rainy day. It poured.")
        templates.append(f"{n} potions. Zero courage.")

    if "potion_miser" in facts:
        gained, used = facts["potion_miser"]
        templates.append(f"Gained {gained} potions. Used {used}. Regret is a potion you can't drink.")

    if "bloated_deck" in facts:
        n = facts["bloated_deck"]
        templates.append(f"{n} cards in deck. Saw the right one once.")
        templates.append(f"Never met a card reward they didn't like. {n} cards.")
        templates.append(f"A {n}-card deck. Quantity has a quality all its own. Except here.")

    if "tiny_deck" in facts:
        n = facts["tiny_deck"]
        templates.append(f"A {n}-card deck. Bold. Wrong, but bold.")
        templates.append(f"Only {n} cards. Every draw was predictable. So was the ending.")

    if "never_removed_starters" in facts:
        n = facts["never_removed_starters"]
        templates.append(f"Still had {n} starter cards. Believed in the basics.")
        templates.append(f"{n} starter cards remained. Loyalty is not always a virtue.")

    if "instant_death" in facts:
        f = facts["instant_death"]
        templates.append(f"Floor {f}. That's it. That's the run.")
        templates.append("The Spire barely noticed.")
        templates.append(f"Floor {f}. A promising career cut tragically short.")

    if "boss_death" in facts:
        boss = facts["boss_death"]
        templates.append(f"Made it to {boss}. Almost.")
        templates.append(f"Fell at the feet of {boss}. So close to glory.")

    if "marathon" in facts:
        m = facts["marathon"]
        templates.append(f"Played for {m} minutes. Still lost.")
        templates.append(f"{m} minutes of careful play. One moment of carelessness.")

    if "speedrun_death" in facts:
        templates.append("Speedran straight into the grave.")

    if "overkill" in facts:
        d = facts["overkill"]
        templates.append(f"Took {d} damage on the final floor. It was not close.")

    if "died_rich" in facts:
        g = facts["died_rich"]
        templates.append(f"Died with {g} gold. Can't take it with you.")
        templates.append(f"{g} gold in pocket. The shopkeeper weeps.")

    if "so_close" in facts:
        f = facts["so_close"]
        templates.append(f"Floor {f}. Could almost see the top.")
        templates.append(f"Made it to floor {f}. The Spire giveth, the Spire taketh away.")

    if "all_attacks" in facts:
        n = facts["all_attacks"]
        templates.append(f"{n} Attack cards. Zero plan for staying alive.")
        templates.append(f"The best offense is not, in fact, {n} Attack cards.")

    return templates


def _fallback_epitaph(run: RunHistory) -> str:
    """Generic epitaph when no specific facts are notable."""
    floor = run.floors[-1].floor if run.floors else 0
    char = run.character
    fallbacks = [
        f"Floor {floor}. Another soul for the Spire.",
        f"Reached floor {floor}. The Spire remembers.",
        f"{char}, floor {floor}. Gone but not forgotten.",
        f"Floor {floor}. The climb continues. Not for this one.",
    ]
    seed = int(hashlib.md5(run.id.encode()).hexdigest()[:8], 16)
    return fallbacks[seed % len(fallbacks)]
