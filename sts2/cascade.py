"""Cascade Map — trace the downstream impact of a single card pick."""


def trace_card_impact(run, card_id, kb):
    """Trace the downstream impact of picking a specific card.

    Compares pre-pick vs post-pick performance metrics:
    damage taken, fight length, HP trajectory.
    """
    # Find when the card was picked
    pick_floor = None
    for floor in run.floors:
        if floor.card_picked == card_id:
            pick_floor = floor.floor
            break

    if pick_floor is None:
        return {"error": "Card not found in run floor history"}

    pre = [f for f in run.floors if f.floor < pick_floor]
    post = [f for f in run.floors if f.floor >= pick_floor]

    pre_combats = [f for f in pre if f.type in ("monster", "elite", "boss") and f.turns > 0]
    post_combats = [f for f in post if f.type in ("monster", "elite", "boss") and f.turns > 0]

    pre_avg_dmg = sum(f.damage_taken for f in pre_combats) / len(pre_combats) if pre_combats else 0
    post_avg_dmg = sum(f.damage_taken for f in post_combats) / len(post_combats) if post_combats else 0

    pre_avg_turns = sum(f.turns for f in pre_combats) / len(pre_combats) if pre_combats else 0
    post_avg_turns = sum(f.turns for f in post_combats) / len(post_combats) if post_combats else 0

    card = kb.get_card_by_id(card_id) if kb else None

    return {
        "card_name": card.name if card else card_id,
        "card_id": card_id,
        "picked_floor": pick_floor,
        "floors_survived_after": len(post),
        "total_floors": len(run.floors),
        "damage_delta": round(post_avg_dmg - pre_avg_dmg, 1),
        "turns_delta": round(post_avg_turns - pre_avg_turns, 1),
        "pre_avg_damage": round(pre_avg_dmg, 1),
        "post_avg_damage": round(post_avg_dmg, 1),
        "pre_avg_turns": round(pre_avg_turns, 1),
        "post_avg_turns": round(post_avg_turns, 1),
        "impact": "positive" if post_avg_dmg < pre_avg_dmg else "negative" if post_avg_dmg > pre_avg_dmg else "neutral",
    }


def trace_all_picks(run, kb):
    """Trace impact of every card picked during the run."""
    results = []
    seen = set()
    for floor in run.floors:
        if floor.card_picked and floor.card_picked not in seen:
            seen.add(floor.card_picked)
            result = trace_card_impact(run, floor.card_picked, kb)
            if "error" not in result:
                results.append(result)
    return sorted(results, key=lambda r: r["picked_floor"])
