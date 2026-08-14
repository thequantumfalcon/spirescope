"""Cascade Map — observational before/after comparison around a card pick.

For each floor where a card was picked, this compares combat performance in
the floors before the pick to the floors after it. It is NOT a measurement of
what the pick caused: later floors are systematically harder regardless of
what you picked, so a positive reading may just mean the run was still
comfortable, and a negative one may just mean Act 2 started. Read each row as
"this is what happened after the pick," not "this is what the pick did."
"""


def trace_card_impact(run, card_id, kb, pick_floor=None):
    """Compare combat metrics in the floors before vs after a card pick.

    Observational only (see module docstring) — a before/after split of the
    run's own combats, not a controlled comparison.

    `pick_floor` disambiguates which pick to trace when the same card_id was
    picked more than once in a run; if omitted, the first floor with
    card_picked == card_id is used.

    Returns {"error": ...} instead of a row when the card can't be located,
    or when either side of the comparison has fewer than 2 combats — with
    that few data points a "delta" is noise, not a comparison.
    """
    if pick_floor is None:
        for floor in run.floors:
            if floor.card_picked == card_id:
                pick_floor = floor.floor
                break

    if pick_floor is None:
        return {"error": "Card not found in run floor history"}

    pre = [f for f in run.floors if f.floor < pick_floor]
    # The acquisition floor itself is the reward floor, not a floor played
    # with the new card — exclude it from "post".
    post = [f for f in run.floors if f.floor > pick_floor]

    pre_combats = [f for f in pre if f.type in ("monster", "elite", "boss") and f.turns > 0]
    post_combats = [f for f in post if f.type in ("monster", "elite", "boss") and f.turns > 0]

    if len(pre_combats) < 2 or len(post_combats) < 2:
        return {"error": "Not enough combats before/after this pick for a comparison"}

    pre_avg_dmg = sum(f.damage_taken for f in pre_combats) / len(pre_combats)
    post_avg_dmg = sum(f.damage_taken for f in post_combats) / len(post_combats)

    pre_avg_turns = sum(f.turns for f in pre_combats) / len(pre_combats)
    post_avg_turns = sum(f.turns for f in post_combats) / len(post_combats)

    pre_avg_hp = sum(f.current_hp for f in pre_combats) / len(pre_combats)
    post_avg_hp = sum(f.current_hp for f in post_combats) / len(post_combats)

    card = kb.get_card_by_id(card_id) if kb else None

    return {
        "card_name": card.name if card else card_id,
        "card_id": card_id,
        "picked_floor": pick_floor,
        "floors_survived_after": len(post),
        "total_floors": len(run.floors),
        "damage_delta": round(post_avg_dmg - pre_avg_dmg, 1),
        "turns_delta": round(post_avg_turns - pre_avg_turns, 1),
        "hp_delta": round(post_avg_hp - pre_avg_hp, 1),
        "pre_avg_damage": round(pre_avg_dmg, 1),
        "post_avg_damage": round(post_avg_dmg, 1),
        "pre_avg_turns": round(pre_avg_turns, 1),
        "post_avg_turns": round(post_avg_turns, 1),
        "impact": "positive" if post_avg_dmg < pre_avg_dmg else "negative" if post_avg_dmg > pre_avg_dmg else "neutral",
    }


def trace_all_picks(run, kb):
    """Trace the before/after comparison for every card picked during the run.

    Each floor with a card pick gets its own row, keyed by that floor —
    picking the same card twice in a run produces two independent rows
    instead of one (previously the second and later picks of a repeated
    card_id were silently dropped).
    """
    results = []
    for floor in run.floors:
        if floor.card_picked:
            result = trace_card_impact(run, floor.card_picked, kb, pick_floor=floor.floor)
            if "error" not in result:
                results.append(result)
    return sorted(results, key=lambda r: r["picked_floor"])
