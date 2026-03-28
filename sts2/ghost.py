"""Ghost Run Comparison — speedrun-style splits against your best run."""


def find_ghost_run(character, ascension, runs):
    """Find the best comparable historical run to use as ghost.

    Priority: winning run with same character and close ascension.
    Fallback: any win with same character.
    Fallback: longest-surviving run with same character (if no wins).
    """
    same_char = [r for r in runs if r.character == character]
    if not same_char:
        return None

    # Prefer wins at similar ascension
    wins = [r for r in same_char if r.win and abs(r.ascension - ascension) <= 2]
    if wins:
        return max(wins, key=lambda r: (r.ascension, -r.run_time))

    # Any win with this character
    any_wins = [r for r in same_char if r.win]
    if any_wins:
        return max(any_wins, key=lambda r: (r.ascension, -r.run_time))

    # No wins — use the deepest run as ghost
    with_floors = [r for r in same_char if r.floors]
    if with_floors:
        return max(with_floors, key=lambda r: r.floors[-1].floor)

    return None


def compute_splits(current_run, ghost_run):
    """Compare current run state to ghost at each floor.

    Returns a list of split dicts with deltas for HP, gold, and deck size.
    """
    if not ghost_run or not ghost_run.floors:
        return []

    ghost_by_floor = {f.floor: f for f in ghost_run.floors}
    current_floors = getattr(current_run, "floors", [])

    # Reconstruct ghost deck size floor by floor
    ghost_deck_sizes = {}
    ghost_deck = 10  # approximate starter deck
    for f in ghost_run.floors:
        if f.card_picked:
            ghost_deck += 1
        ghost_deck_sizes[f.floor] = ghost_deck

    splits = []
    running_deck = 10  # approximate starter for current run
    for cf in current_floors:
        if cf.card_picked:
            running_deck += 1
        gf = ghost_by_floor.get(cf.floor)
        if not gf:
            continue

        hp_delta = cf.current_hp - gf.current_hp
        gold_delta = cf.gold - gf.gold
        deck_delta = running_deck - ghost_deck_sizes.get(cf.floor, 10)

        splits.append({
            "floor": cf.floor,
            "hp_delta": hp_delta,
            "gold_delta": gold_delta,
            "deck_delta": deck_delta,
            "current_hp": cf.current_hp,
            "ghost_hp": gf.current_hp,
            "current_gold": cf.gold,
            "ghost_gold": gf.gold,
            "ahead": hp_delta > 0,
        })

    return splits


def ghost_summary(splits):
    """Summarize ghost comparison for display."""
    if not splits:
        return None

    last = splits[-1]
    floors_ahead = sum(1 for s in splits if s["hp_delta"] > 0)
    floors_behind = sum(1 for s in splits if s["hp_delta"] < 0)
    avg_hp_delta = sum(s["hp_delta"] for s in splits) / len(splits)

    return {
        "floors_ahead": floors_ahead,
        "floors_behind": floors_behind,
        "avg_hp_delta": round(avg_hp_delta, 1),
        "current_hp_delta": last["hp_delta"],
        "current_gold_delta": last["gold_delta"],
        "status": "ahead" if last["hp_delta"] > 0 else "behind" if last["hp_delta"] < 0 else "even",
    }
