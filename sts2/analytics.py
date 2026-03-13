"""Analytics engine: compute aggregate stats from run history."""
from collections import Counter, defaultdict

from sts2.models import PlayerProgress, RunHistory


def _estimate_act(floor: int) -> int:
    """Estimate which act a floor belongs to based on floor number."""
    if floor <= 17:
        return 1
    if floor <= 34:
        return 2
    return 3


def _pearson_r(xs: list[float], ys: list[float]) -> float:
    """Compute Pearson correlation coefficient between two lists."""
    n = len(xs)
    if n < 3 or n != len(ys):
        return 0.0
    mx = sum(xs) / n
    my = sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    den = (sum((x - mx) ** 2 for x in xs) * sum((y - my) ** 2 for y in ys)) ** 0.5
    return round(num / den, 3) if den else 0.0


def compute_analytics(runs: list[RunHistory], card_stats: dict = None, kb=None) -> dict:
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
        for floor in run.floors:
            if floor.damage_taken > 0:
                act_damage[_estimate_act(floor.floor)].append(floor.damage_taken)

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

    # --- Turn Efficiency ---
    fight_turns: list[int] = []
    elite_turns: list[int] = []
    boss_turns: list[int] = []
    turn_damage_pairs: list[tuple[float, float]] = []
    act_turns: dict[int, list[int]] = {1: [], 2: [], 3: []}
    for run in runs:
        for floor in run.floors:
            if floor.turns > 0 and floor.type in ("monster", "elite", "boss"):
                fight_turns.append(floor.turns)
                if floor.type == "elite":
                    elite_turns.append(floor.turns)
                elif floor.type == "boss":
                    boss_turns.append(floor.turns)
                turn_damage_pairs.append((float(floor.turns), float(floor.damage_taken)))
                act = _estimate_act(floor.floor)
                if act in act_turns:
                    act_turns[act].append(floor.turns)

    turn_efficiency = {
        "avg_turns_per_fight": round(sum(fight_turns) / len(fight_turns), 1) if fight_turns else 0,
        "avg_turns_per_elite": round(sum(elite_turns) / len(elite_turns), 1) if elite_turns else 0,
        "avg_turns_per_boss": round(sum(boss_turns) / len(boss_turns), 1) if boss_turns else 0,
        "turns_vs_damage": _pearson_r(
            [t for t, _ in turn_damage_pairs],
            [d for _, d in turn_damage_pairs],
        ) if turn_damage_pairs else 0,
        "efficiency_trend": [
            round(sum(act_turns[a]) / len(act_turns[a]), 1) if act_turns[a] else 0
            for a in (1, 2, 3)
        ],
    }

    # --- Per-Act Breakdown ---
    act_stats: dict[int, dict] = {1: {"damage": [], "cards_added": [], "gold": []},
                                  2: {"damage": [], "cards_added": [], "gold": []},
                                  3: {"damage": [], "cards_added": [], "gold": []}}
    act_deaths: Counter = Counter()
    for run in runs:
        for floor in run.floors:
            act = _estimate_act(floor.floor)
            if act in act_stats:
                if floor.damage_taken > 0:
                    act_stats[act]["damage"].append(floor.damage_taken)
                if floor.card_picked:
                    act_stats[act]["cards_added"].append(1)
                if floor.gold > 0:
                    act_stats[act]["gold"].append(floor.gold)
        if not run.win and run.floors:
            act_deaths[_estimate_act(len(run.floors))] += 1

    per_act = {}
    for act_num in (1, 2, 3):
        s = act_stats[act_num]
        per_act[act_num] = {
            "avg_damage": round(sum(s["damage"]) / len(s["damage"]), 1) if s["damage"] else 0,
            "cards_added": len(s["cards_added"]),
            "avg_cards_per_run": round(len(s["cards_added"]) / total, 1) if total else 0,
            "death_count": act_deaths.get(act_num, 0),
            "avg_gold": round(sum(s["gold"]) / len(s["gold"]), 0) if s["gold"] else 0,
        }

    # --- Archetype Stats ---
    archetype_stats: dict[str, dict] = {}
    if kb:
        for run in runs:
            result = kb.classify_archetype(run.deck, run.character)
            arch_name = result["name"]
            if arch_name not in archetype_stats:
                archetype_stats[arch_name] = {"wins": 0, "losses": 0}
            if run.win:
                archetype_stats[arch_name]["wins"] += 1
            else:
                archetype_stats[arch_name]["losses"] += 1
        for arch in archetype_stats.values():
            t = arch["wins"] + arch["losses"]
            arch["win_rate"] = round(arch["wins"] / t * 100, 1) if t else 0

    # --- Card Pick Timing ---
    early_picks: Counter = Counter()
    mid_picks: Counter = Counter()
    late_picks: Counter = Counter()
    pick_floors: dict[str, list[int]] = defaultdict(list)
    for run in runs:
        for floor in run.floors:
            if floor.card_picked:
                pick_floors[floor.card_picked].append(floor.floor)
                if floor.floor <= 10:
                    early_picks[floor.card_picked] += 1
                elif floor.floor <= 25:
                    mid_picks[floor.card_picked] += 1
                else:
                    late_picks[floor.card_picked] += 1

    def _pick_list(counter: Counter) -> list[dict]:
        return [{"card": card, "count": count,
                 "avg_floor": round(sum(pick_floors[card]) / len(pick_floors[card]), 1)}
                for card, count in counter.most_common(10) if count >= 2]

    card_pick_timing = {
        "early_picks": _pick_list(early_picks),
        "mid_picks": _pick_list(mid_picks),
        "late_picks": _pick_list(late_picks),
    }

    # --- Encounter Danger Ratings ---
    encounter_danger = {}
    for enc_id, dmg_list in encounter_damage.items():
        if len(dmg_list) < 2:
            continue
        avg_dmg = round(sum(dmg_list) / len(dmg_list), 1)
        deaths = encounter_deaths.get(enc_id, 0)
        kill_rate = round(deaths / len(dmg_list) * 100, 1)
        if avg_dmg < 10:
            grade = "Low"
        elif avg_dmg < 25:
            grade = "Medium"
        elif avg_dmg < 40:
            grade = "High"
        else:
            grade = "Extreme"
        encounter_danger[enc_id] = {
            "avg_damage": avg_dmg, "kill_rate": kill_rate, "grade": grade,
            "fights": len(dmg_list), "deaths": deaths,
        }

    # --- Gold Economy ---
    all_gold_values: list[int] = []
    gold_at_death: list[int] = []
    gold_by_floor: dict[int, list[int]] = defaultdict(list)
    highest_gold: dict | None = None
    win_gold: list[int] = []
    loss_gold: list[int] = []
    for run in runs:
        run_golds = [f.gold for f in run.floors if f.gold > 0]
        if run_golds:
            final_gold = run_golds[-1]
            all_gold_values.append(final_gold)
            if run.win:
                win_gold.append(final_gold)
            else:
                loss_gold.append(final_gold)
                gold_at_death.append(final_gold)
        for floor in run.floors:
            if floor.gold > 0:
                bucket = ((floor.floor - 1) // 10) * 10 + 5
                gold_by_floor[bucket].append(floor.gold)
                if highest_gold is None or floor.gold > highest_gold["gold"]:
                    highest_gold = {"gold": floor.gold, "run_id": run.id, "floor": floor.floor}

    gold_economy = {
        "avg_gold_per_run": round(sum(all_gold_values) / len(all_gold_values), 0) if all_gold_values else 0,
        "avg_gold_at_death": round(sum(gold_at_death) / len(gold_at_death), 0) if gold_at_death else 0,
        "gold_curve": [{"floor": k, "avg_gold": round(sum(v) / len(v), 0)}
                       for k, v in sorted(gold_by_floor.items())],
        "highest_gold": highest_gold,
        "win_vs_loss_gold": {
            "win_avg": round(sum(win_gold) / len(win_gold), 0) if win_gold else 0,
            "loss_avg": round(sum(loss_gold) / len(loss_gold), 0) if loss_gold else 0,
        },
    }

    # --- Co-op Stats ---
    coop_runs = [r for r in runs if getattr(r, "total_players", 1) > 1]
    coop_stats = None
    if coop_runs:
        solo_runs = [r for r in runs if getattr(r, "total_players", 1) == 1]
        coop_wins = sum(1 for r in coop_runs if r.win)
        solo_wins = sum(1 for r in solo_runs if r.win)
        coop_stats = {
            "total_coop_runs": len(coop_runs),
            "coop_win_rate": round(coop_wins / len(coop_runs) * 100, 1) if coop_runs else 0,
            "solo_win_rate": round(solo_wins / len(solo_runs) * 100, 1) if solo_runs else 0,
        }

    # --- Healing Sources ---
    rest_healing = {"total": 0, "count": 0}
    combat_healing = {"total": 0, "count": 0}
    other_healing = {"total": 0, "count": 0}
    total_healing = 0
    for run in runs:
        for floor in run.floors:
            if floor.hp_healed > 0:
                total_healing += floor.hp_healed
                if floor.type == "rest":
                    rest_healing["total"] += floor.hp_healed
                    rest_healing["count"] += 1
                elif floor.type in ("monster", "elite", "boss"):
                    combat_healing["total"] += floor.hp_healed
                    combat_healing["count"] += 1
                else:
                    other_healing["total"] += floor.hp_healed
                    other_healing["count"] += 1

    healing_sources = {
        "rest_healing": {**rest_healing, "avg": round(rest_healing["total"] / rest_healing["count"], 1) if rest_healing["count"] else 0},
        "combat_healing": combat_healing,
        "other_healing": other_healing,
        "total_healing": total_healing,
    }

    # --- Card Regret Analysis ---
    win_picks: Counter = Counter()
    win_skips: Counter = Counter()
    loss_picks: Counter = Counter()
    loss_skips: Counter = Counter()
    for run in runs:
        target_pick = win_picks if run.win else loss_picks
        target_skip = win_skips if run.win else loss_skips
        for floor in run.floors:
            if floor.cards_offered:
                for offered_id in floor.cards_offered:
                    if offered_id:
                        if offered_id == floor.card_picked:
                            target_pick[offered_id] += 1
                        else:
                            target_skip[offered_id] += 1

    card_regret = {"most_skipped_in_wins": [], "most_picked_in_losses": [], "high_regret": []}
    # Cards you skip in wins (maybe you should pick them?)
    for card_id, skip_count in win_skips.most_common(10):
        total_offered_wins = win_picks.get(card_id, 0) + skip_count
        if total_offered_wins >= 3:
            card_regret["most_skipped_in_wins"].append({
                "card": card_id,
                "skip_rate": round(skip_count / total_offered_wins * 100, 1),
                "times_skipped": skip_count,
            })
    # Cards you pick in losses (maybe you should skip them?)
    for card_id, pick_count in loss_picks.most_common(10):
        total_offered_losses = pick_count + loss_skips.get(card_id, 0)
        if total_offered_losses >= 3:
            card_regret["most_picked_in_losses"].append({
                "card": card_id,
                "pick_rate": round(pick_count / total_offered_losses * 100, 1),
                "times_picked": pick_count,
            })
    # High regret: picked often in losses but skipped in wins
    all_cards_offered = set(loss_picks.keys()) | set(win_skips.keys())
    for card_id in all_cards_offered:
        loss_total = loss_picks.get(card_id, 0) + loss_skips.get(card_id, 0)
        win_total = win_picks.get(card_id, 0) + win_skips.get(card_id, 0)
        if loss_total < 3 or win_total < 3:
            continue
        loss_pick_rate = loss_picks.get(card_id, 0) / loss_total
        win_pick_rate = win_picks.get(card_id, 0) / win_total
        regret_score = round(loss_pick_rate - win_pick_rate, 3)
        if regret_score > 0.1:
            card_regret["high_regret"].append({"card": card_id, "score": regret_score})
    card_regret["high_regret"].sort(key=lambda x: -x["score"])
    card_regret["high_regret"] = card_regret["high_regret"][:10]

    result = {
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
        "per_act": per_act,
        "turn_efficiency": turn_efficiency,
        "card_pick_timing": card_pick_timing,
        "encounter_danger": encounter_danger,
        "gold_economy": gold_economy,
        "healing_sources": healing_sources,
        "card_regret": card_regret,
        "archetype_stats": archetype_stats,
    }
    if coop_stats:
        result["coop_stats"] = coop_stats
    return result


def analyze_run(run: RunHistory, kb=None) -> dict:
    """Generate post-mortem insights for a single run.

    Pass kb (KnowledgeBase) for card-type-aware analysis: deck balance,
    defensive gap detection, and card stacking warnings.
    """
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

    # KB-powered insights: deck balance, defensive gaps, card stacking
    if kb and run.deck:
        try:
            typed = [kb.get_card_by_id(c) for c in run.deck]
            typed = [c for c in typed if c]
            if typed:
                n = len(typed)
                skl = sum(1 for c in typed if getattr(c, "type", "") == "Skill")
                skl_pct = round(skl / n * 100)
                if skl_pct < 20:
                    insights.append({"type": "warning",
                        "text": f"Only {skl_pct}% Skills ({skl}/{n}) — severely limited defense. Winning decks average ~40% Skills."})
                elif skl_pct < 30:
                    insights.append({"type": "warning",
                        "text": f"{skl_pct}% Skills ({skl}/{n}) — below average defense."})

                # Defensive gap
                kw_set = set()
                for c in typed:
                    kw_set.update(getattr(c, "keywords", []))
                has_block = any(k in kw_set for k in ("Block", "Dexterity", "Frost"))
                if not has_block:
                    severity = "bad" if not run.win else "warning"
                    insights.append({"type": severity,
                        "text": "Zero Block/defensive keywords in entire deck — this is the #1 cause of early deaths."})
        except Exception:
            pass

        # Card stacking
        try:
            stacked = [(cid, cnt) for cid, cnt in Counter(run.deck).items() if cnt >= 3]
            if stacked:
                names = [kb.id_to_name(cid) for cid, _ in stacked[:3]]
                insights.append({"type": "warning",
                    "text": f"Card stacking: {', '.join(names)} — diminishing returns from duplicates."})
        except Exception:
            pass

    return {"insights": insights}


def analyze_run_patterns(runs: list[RunHistory], kb=None) -> list[dict]:
    """Detect recurring patterns across multiple runs."""
    if len(runs) < 3:
        return []

    patterns = []
    recent = runs[:10]

    # Pattern: consistently skipping defense
    if kb:
        defense_skip = 0
        for run in recent:
            typed = [kb.get_card_by_id(c) for c in run.deck]
            typed = [c for c in typed if c]
            kw_set = set()
            for c in typed:
                kw_set.update(getattr(c, "keywords", []))
            if not any(k in kw_set for k in ("Block", "Dexterity", "Frost")):
                defense_skip += 1
        if defense_skip >= len(recent) * 0.6:
            patterns.append({
                "type": "recurring",
                "text": f"Defense neglected in {defense_skip}/{len(recent)} recent runs — this is a consistent blind spot.",
                "severity": "high",
            })

    # Pattern: dying in same act repeatedly
    death_acts: Counter = Counter()
    for run in recent:
        if not run.win and run.floors:
            death_acts[_estimate_act(len(run.floors))] += 1
    for act, count in death_acts.items():
        if count >= 3:
            patterns.append({
                "type": "recurring",
                "text": f"Died in Act {act} in {count} of your last {len(recent)} runs — review Act {act} strategy.",
                "severity": "medium",
            })

    return patterns


def compute_records(runs: list[RunHistory], progress: PlayerProgress | None = None) -> dict:
    """Compute personal records / hall of fame from run history and progress."""
    if not runs:
        return {}

    wins = [r for r in runs if r.win]

    # Fastest win
    fastest_win = None
    if wins:
        fastest = min(wins, key=lambda r: r.run_time)
        fastest_win = {"time": fastest.run_time, "character": fastest.character, "run_id": fastest.id}

    # Highest ascension win
    highest_asc_win = None
    if wins:
        best_asc = max(wins, key=lambda r: r.ascension)
        highest_asc_win = {"ascension": best_asc.ascension, "character": best_asc.character, "run_id": best_asc.id}

    # Biggest / smallest deck (from wins only)
    biggest_deck = None
    smallest_deck = None
    if wins:
        big = max(wins, key=lambda r: len(r.deck))
        biggest_deck = {"size": len(big.deck), "character": big.character, "run_id": big.id}
        small = min(wins, key=lambda r: len(r.deck))
        smallest_deck = {"size": len(small.deck), "character": small.character, "run_id": small.id}

    # Most gold on a single floor
    most_gold = None
    for run in runs:
        for floor in run.floors:
            if floor.gold > 0 and (most_gold is None or floor.gold > most_gold["gold"]):
                most_gold = {"gold": floor.gold, "run_id": run.id, "floor": floor.floor}

    # Most damage taken on a single floor
    most_damage_floor = None
    for run in runs:
        for floor in run.floors:
            if most_damage_floor is None or floor.damage_taken > most_damage_floor["damage"]:
                most_damage_floor = {"damage": floor.damage_taken, "floor": floor.floor, "run_id": run.id}

    # Flawless bosses (boss floors with 0 damage taken)
    flawless_bosses = 0
    for run in runs:
        for floor in run.floors:
            if floor.type == "boss" and floor.damage_taken == 0:
                flawless_bosses += 1

    # Longest streak from progress
    longest_streak = None
    if progress and progress.character_stats:
        best_char = max(progress.character_stats.items(),
                        key=lambda kv: kv[1].get("best_streak", 0))
        streak = best_char[1].get("best_streak", 0)
        if streak > 0:
            longest_streak = {"count": streak, "character": best_char[0]}

    # Per-character breakdown
    char_runs = defaultdict(list)
    for run in runs:
        char_runs[run.character].append(run)

    per_character = {}
    for char, char_run_list in sorted(char_runs.items()):
        char_wins = [r for r in char_run_list if r.win]
        best_asc = max((r.ascension for r in char_wins), default=0)
        fastest = min((r.run_time for r in char_wins), default=0)
        per_character[char] = {
            "wins": len(char_wins),
            "losses": len(char_run_list) - len(char_wins),
            "best_ascension": best_asc,
            "fastest": fastest,
        }

    return {
        "fastest_win": fastest_win,
        "highest_ascension_win": highest_asc_win,
        "longest_streak": longest_streak,
        "most_gold": most_gold,
        "biggest_deck": biggest_deck,
        "smallest_deck": smallest_deck,
        "most_damage_floor": most_damage_floor,
        "flawless_bosses": flawless_bosses,
        "per_character": per_character,
    }
