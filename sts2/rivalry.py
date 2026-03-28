"""Rivalry Seed System — asynchronous seed-based competition."""


def compare_seed_runs(run_a, run_b, kb=None):
    """Compare two runs on the same seed, floor by floor.

    Returns decision diffs: where the two players made different choices.
    """
    if run_a.seed != run_b.seed:
        return {"error": f"Seeds don't match: {run_a.seed} vs {run_b.seed}"}

    diffs = []
    b_floors = {f.floor: f for f in run_b.floors}

    for fa in run_a.floors:
        fb = b_floors.get(fa.floor)
        if not fb:
            continue

        # Card pick difference
        if fa.card_picked and fb.card_picked and fa.card_picked != fb.card_picked:
            name_a = kb.id_to_name(fa.card_picked) if kb else fa.card_picked
            name_b = kb.id_to_name(fb.card_picked) if kb else fb.card_picked
            diffs.append({
                "floor": fa.floor,
                "type": "card_pick",
                "yours": name_a,
                "rival": name_b,
            })

        # HP difference
        if fa.current_hp != fb.current_hp:
            diffs.append({
                "floor": fa.floor,
                "type": "hp",
                "yours": fa.current_hp,
                "rival": fb.current_hp,
                "delta": fa.current_hp - fb.current_hp,
            })

    last_a = run_a.floors[-1].floor if run_a.floors else 0
    last_b = run_b.floors[-1].floor if run_b.floors else 0

    return {
        "seed": run_a.seed,
        "diffs": diffs,
        "card_diffs": [d for d in diffs if d["type"] == "card_pick"],
        "your_result": "win" if run_a.win else f"died floor {last_a}",
        "rival_result": "win" if run_b.win else f"died floor {last_b}",
        "your_floor": last_a,
        "rival_floor": last_b,
    }
