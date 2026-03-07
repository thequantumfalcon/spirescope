"""Analytics engine: compute aggregate stats from run history."""
from collections import Counter, defaultdict

from sts2.models import RunHistory


def compute_analytics(runs: list[RunHistory], card_stats: dict = None) -> dict:
    """Compute aggregate analytics from all completed runs.

    Returns a dict with:
    - overview: total runs, wins, losses, win rate, avg run time, avg deck size
    - card_rankings: cards sorted by win rate (min 2 appearances)
    - relic_rankings: relics sorted by win rate (min 2 appearances)
    - character_breakdown: per-character win rates and pick patterns
    - card_pick_rates: most/least picked cards from offerings
    - damage_by_act: average damage taken per act
    - floor_survival: how far runs typically get
    - deadly_encounters: encounters with highest loss rates
    - winning_deck_traits: what winning decks have in common
    """
    if not runs:
        return {"overview": {"total": 0}}

    total = len(runs)
    wins = [r for r in runs if r.win]
    losses = [r for r in runs if not r.win]
    win_count = len(wins)

    # --- Overview ---
    avg_time = sum(r.run_time for r in runs) / total if total else 0
    avg_deck = sum(len(r.deck) for r in runs) / total if total else 0
    avg_floors = sum(len(r.floors) for r in runs) / total if total else 0

    overview = {
        "total": total,
        "wins": win_count,
        "losses": len(losses),
        "win_rate": round(win_count / total * 100, 1) if total else 0,
        "avg_time_min": round(avg_time / 60, 1),
        "avg_deck_size": round(avg_deck, 1),
        "avg_floors": round(avg_floors, 1),
    }

    # --- Card Win Rates ---
    card_wins = Counter()
    card_total = Counter()
    for run in runs:
        for card_id in set(run.deck):  # unique cards per run
            card_total[card_id] += 1
            if run.win:
                card_wins[card_id] += 1

    card_rankings = []
    for card_id, appearances in card_total.most_common():
        if appearances < 2:
            continue
        wr = round(card_wins[card_id] / appearances * 100, 1)
        card_rankings.append({
            "id": card_id,
            "appearances": appearances,
            "wins": card_wins[card_id],
            "win_rate": wr,
        })
    card_rankings.sort(key=lambda x: (-x["win_rate"], -x["appearances"]))

    # --- Relic Win Rates ---
    relic_wins = Counter()
    relic_total = Counter()
    for run in runs:
        for relic_id in set(run.relics):
            relic_total[relic_id] += 1
            if run.win:
                relic_wins[relic_id] += 1

    relic_rankings = []
    for relic_id, appearances in relic_total.most_common():
        if appearances < 2:
            continue
        wr = round(relic_wins[relic_id] / appearances * 100, 1)
        relic_rankings.append({
            "id": relic_id,
            "appearances": appearances,
            "wins": relic_wins[relic_id],
            "win_rate": wr,
        })
    relic_rankings.sort(key=lambda x: (-x["win_rate"], -x["appearances"]))

    # --- Character Breakdown ---
    char_runs = defaultdict(list)
    for run in runs:
        char_runs[run.character].append(run)

    character_breakdown = {}
    for char, char_run_list in sorted(char_runs.items()):
        char_wins = sum(1 for r in char_run_list if r.win)
        char_total = len(char_run_list)
        character_breakdown[char] = {
            "total": char_total,
            "wins": char_wins,
            "losses": char_total - char_wins,
            "win_rate": round(char_wins / char_total * 100, 1) if char_total else 0,
            "avg_deck_size": round(sum(len(r.deck) for r in char_run_list) / char_total, 1),
            "avg_floors": round(sum(len(r.floors) for r in char_run_list) / char_total, 1),
        }

    # --- Card Pick Rates (from floor card_picked / cards_offered) ---
    card_offered = Counter()
    card_picked = Counter()
    for run in runs:
        for floor in run.floors:
            if floor.cards_offered:
                for offered_id in floor.cards_offered:
                    if offered_id:
                        card_offered[offered_id] += 1
                if floor.card_picked:
                    card_picked[floor.card_picked] += 1

    card_pick_rates = []
    for card_id, offered in card_offered.most_common():
        if offered < 2:
            continue
        picked = card_picked.get(card_id, 0)
        card_pick_rates.append({
            "id": card_id,
            "offered": offered,
            "picked": picked,
            "pick_rate": round(picked / offered * 100, 1),
        })
    card_pick_rates.sort(key=lambda x: (-x["pick_rate"], -x["offered"]))

    # --- Damage by Act ---
    act_damage = defaultdict(list)
    for run in runs:
        act_num = 1
        floor_count = 0
        for floor in run.floors:
            floor_count += 1
            # Rough act boundaries (~17 floors per act)
            if floor_count > 34:
                act_num = 3
            elif floor_count > 17:
                act_num = 2
            if floor.damage_taken > 0:
                act_damage[act_num].append(floor.damage_taken)

    damage_by_act = {}
    for act_num in sorted(act_damage.keys()):
        dmg_list = act_damage[act_num]
        damage_by_act[f"Act {act_num}"] = {
            "avg_per_floor": round(sum(dmg_list) / len(dmg_list), 1) if dmg_list else 0,
            "total_floors": len(dmg_list),
            "max_hit": max(dmg_list) if dmg_list else 0,
        }

    # --- Floor Survival Distribution ---
    floor_counts = Counter()
    for run in runs:
        bucket = (len(run.floors) // 5) * 5  # group by 5s
        floor_counts[bucket] += 1
    floor_survival = [{"floors": f"{k}-{k+4}", "runs": v}
                      for k, v in sorted(floor_counts.items())]

    # --- Deadliest Encounters ---
    encounter_damage = defaultdict(list)
    encounter_deaths = Counter()
    for run in runs:
        for floor in run.floors:
            if floor.encounter and floor.damage_taken > 0:
                encounter_damage[floor.encounter].append(floor.damage_taken)
        if run.killed_by:
            encounter_deaths[run.killed_by] += 1

    deadly_encounters = []
    for enc_id, dmg_list in encounter_damage.items():
        if len(dmg_list) < 2:
            continue
        deadly_encounters.append({
            "id": enc_id,
            "avg_damage": round(sum(dmg_list) / len(dmg_list), 1),
            "fights": len(dmg_list),
            "deaths": encounter_deaths.get(enc_id, 0),
        })
    deadly_encounters.sort(key=lambda x: -x["avg_damage"])

    # --- Winning Deck Traits vs Losing ---
    def _deck_traits(run_list):
        if not run_list:
            return {}
        types = Counter()
        for r in run_list:
            types["total_cards"] += len(r.deck)
        return {
            "avg_deck_size": round(types["total_cards"] / len(run_list), 1),
            "avg_relics": round(sum(len(r.relics) for r in run_list) / len(run_list), 1),
            "avg_floors": round(sum(len(r.floors) for r in run_list) / len(run_list), 1),
            "avg_time_min": round(sum(r.run_time for r in run_list) / len(run_list) / 60, 1),
        }

    winning_deck_traits = {
        "wins": _deck_traits(wins),
        "losses": _deck_traits(losses),
    }

    # --- Card Synergy Network (co-occurrence in winning decks) ---
    card_cooccurrence = Counter()
    for run in wins:
        unique_cards = sorted(set(run.deck))
        for i, c1 in enumerate(unique_cards):
            for c2 in unique_cards[i + 1:]:
                card_cooccurrence[(c1, c2)] += 1

    synergy_edges = []
    for (c1, c2), count in card_cooccurrence.most_common(50):
        if count < 2:
            break
        synergy_edges.append({"source": c1, "target": c2, "weight": count})

    return {
        "overview": overview,
        "card_rankings": card_rankings[:30],
        "relic_rankings": relic_rankings[:20],
        "character_breakdown": character_breakdown,
        "card_pick_rates": card_pick_rates[:30],
        "damage_by_act": damage_by_act,
        "floor_survival": floor_survival,
        "deadly_encounters": deadly_encounters[:15],
        "winning_deck_traits": winning_deck_traits,
        "synergy_edges": synergy_edges,
    }
