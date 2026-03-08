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
        return {"overview": {"total": 0}, "hp_tracking": [], "death_floors": [],
                "ascension_curve": [], "card_quality": [], "damage_percentiles": []}

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

    # --- Win Rate Trend (rolling window) ---
    win_trend = []
    if total >= 5:
        window = min(10, max(3, total // 3))
        for i in range(window - 1, total):
            chunk = runs[i - window + 1:i + 1]
            chunk_wins = sum(1 for r in chunk if r.win)
            win_trend.append({
                "run": i + 1,
                "win_rate": round(chunk_wins / window * 100, 1),
            })

    # --- Relic Co-occurrence (synergy matrix) ---
    relic_cooccurrence = Counter()
    for run in wins:
        unique_relics = sorted(set(run.relics))
        for i, r1 in enumerate(unique_relics):
            for r2 in unique_relics[i + 1:]:
                relic_cooccurrence[(r1, r2)] += 1

    relic_synergy_edges = []
    for (r1, r2), count in relic_cooccurrence.most_common(30):
        if count < 2:
            break
        relic_synergy_edges.append({"source": r1, "target": r2, "weight": count})

    # --- Potion Usage Stats ---
    potion_used_count = Counter()
    potion_gained_count = Counter()
    potion_used_in_wins = Counter()
    potion_used_in_runs = Counter()  # run-level (used at least once)
    for run in runs:
        potions_this_run: set[str] = set()
        for floor in run.floors:
            for p_id in floor.potions_used:
                potion_used_count[p_id] += 1
                potions_this_run.add(p_id)
            for p_id in floor.potions_gained:
                potion_gained_count[p_id] += 1
        for p_id in potions_this_run:
            potion_used_in_runs[p_id] += 1
            if run.win:
                potion_used_in_wins[p_id] += 1

    potion_stats = {}
    for p_id in potion_used_count:
        used_in = potion_used_in_runs[p_id]
        potion_stats[p_id] = {
            "times_used": potion_used_count[p_id],
            "times_gained": potion_gained_count.get(p_id, 0),
            "runs_used_in": used_in,
            "wins_when_used": potion_used_in_wins.get(p_id, 0),
            "win_rate": round(potion_used_in_wins.get(p_id, 0) / used_in * 100, 1) if used_in else 0,
        }

    # --- HP Tracking by Floor (wins vs losses) ---
    hp_by_floor_win: dict[int, list[float]] = defaultdict(list)
    hp_by_floor_loss: dict[int, list[float]] = defaultdict(list)
    for run in runs:
        target = hp_by_floor_win if run.win else hp_by_floor_loss
        for floor in run.floors:
            if floor.max_hp > 0 and floor.floor <= 60:
                target[floor.floor].append(floor.current_hp / floor.max_hp * 100)

    all_floor_nums = sorted(set(hp_by_floor_win.keys()) | set(hp_by_floor_loss.keys()))
    hp_tracking = []
    for fn in all_floor_nums:
        win_vals = hp_by_floor_win.get(fn, [])
        loss_vals = hp_by_floor_loss.get(fn, [])
        hp_tracking.append({
            "floor": fn,
            "win_avg_pct": round(sum(win_vals) / len(win_vals), 1) if win_vals else 0,
            "loss_avg_pct": round(sum(loss_vals) / len(loss_vals), 1) if loss_vals else 0,
        })

    # --- Death Floor Distribution ---
    death_floor_counts: Counter = Counter()
    for run in losses:
        if run.floors:
            death_floor_counts[len(run.floors)] += 1
    death_floors = [{"floor": f, "deaths": d} for f, d in sorted(death_floor_counts.items())]

    # --- Ascension Curve ---
    asc_wins: Counter = Counter()
    asc_total: Counter = Counter()
    for run in runs:
        asc_total[run.ascension] += 1
        if run.win:
            asc_wins[run.ascension] += 1
    ascension_curve = []
    for asc in sorted(asc_total.keys()):
        t = asc_total[asc]
        w = asc_wins[asc]
        ascension_curve.append({
            "ascension": asc,
            "total": t,
            "wins": w,
            "win_rate": round(w / t * 100, 1) if t else 0,
        })

    # --- Card Pick Quality (cross-reference pick rates with win rates) ---
    win_rate_by_id = {c["id"]: c["win_rate"] for c in card_rankings}
    card_quality = [{**c, "win_rate": win_rate_by_id[c["id"]]}
                    for c in card_pick_rates if c["id"] in win_rate_by_id]
    card_quality.sort(key=lambda x: (-x["win_rate"], -x["pick_rate"]))

    # --- Damage Percentiles (enrich deadly encounters) ---
    damage_percentiles = []
    for enc_id, dmg_list in encounter_damage.items():
        if len(dmg_list) < 3:
            continue
        s = sorted(dmg_list)
        n = len(s)
        damage_percentiles.append({
            "id": enc_id,
            "fights": n,
            "p25": s[n // 4],
            "median": s[n // 2],
            "p75": s[3 * n // 4],
            "deaths": encounter_deaths.get(enc_id, 0),
        })
    damage_percentiles.sort(key=lambda x: -x["median"])

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
        "relic_synergy_edges": relic_synergy_edges,
        "potion_stats": potion_stats,
        "win_trend": win_trend,
        "hp_tracking": hp_tracking,
        "death_floors": death_floors,
        "ascension_curve": ascension_curve,
        "card_quality": card_quality[:30],
        "damage_percentiles": damage_percentiles[:15],
    }


def analyze_run(run: RunHistory) -> dict:
    """Generate post-mortem insights for a single run."""
    insights = []
    total_damage = sum(f.damage_taken for f in run.floors)
    combat_floors = [f for f in run.floors if f.damage_taken > 0]

    # Deck size analysis
    if len(run.deck) > 30:
        insights.append({"type": "warning", "text": f"Bloated deck ({len(run.deck)} cards) — key cards drawn less often. Consider skipping weak picks."})
    elif len(run.deck) < 12:
        insights.append({"type": "warning", "text": f"Very thin deck ({len(run.deck)} cards) — risky if key cards get exhausted."})
    elif 15 <= len(run.deck) <= 25:
        insights.append({"type": "good", "text": f"Healthy deck size ({len(run.deck)} cards)."})

    # Damage spikes — find the single worst hit
    if combat_floors:
        worst = max(combat_floors, key=lambda f: f.damage_taken)
        if worst.damage_taken > 30:
            enc_name = worst.encounter or "unknown"
            insights.append({"type": "bad", "text": f"Took {worst.damage_taken} damage on floor {worst.floor} ({enc_name}) — your biggest spike. Consider more Block for this fight."})

    # Low HP danger zones
    danger_floors = [f for f in run.floors if f.max_hp > 0 and f.current_hp / f.max_hp < 0.2]
    if len(danger_floors) >= 3:
        insights.append({"type": "warning", "text": f"Dropped below 20% HP on {len(danger_floors)} floors — consider prioritizing healing or Block."})

    # Cards picked analysis
    cards_picked = [f.card_picked for f in run.floors if f.card_picked]
    if run.floors and len(cards_picked) == 0:
        insights.append({"type": "warning", "text": "No card rewards picked this run — skipping all rewards weakens your deck."})

    # Relics
    if len(run.relics) >= 8:
        insights.append({"type": "good", "text": f"Collected {len(run.relics)} relics — strong relic game."})
    elif len(run.relics) <= 2 and len(run.floors) > 20:
        insights.append({"type": "warning", "text": f"Only {len(run.relics)} relics by floor {len(run.floors)} — try fighting more elites for relic drops."})

    # Win-specific
    if run.win:
        time_min = run.run_time / 60
        if time_min < 20:
            insights.append({"type": "good", "text": f"Speed run! Completed in {time_min:.0f} minutes."})
        insights.append({"type": "good", "text": f"Victory with {total_damage} total damage taken across {len(combat_floors)} combats."})
    else:
        if run.killed_by:
            insights.append({"type": "bad", "text": f"Killed by {run.killed_by} on floor {len(run.floors)}."})

    return {"insights": insights}
