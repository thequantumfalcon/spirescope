"""Behavior analysis — tilt detection, anti-patterns, decision quality."""
import math

# ── Tilt Detection ──

def detect_tilt(runs, session_window_hours=4):
    """Detect tilt from recent run patterns.

    Returns momentum score (-100 to +100) and whether tilting.
    """
    if len(runs) < 3:
        return {"tilting": False, "momentum": 0, "message": ""}

    sessions = _group_sessions(runs, session_window_hours)
    current = sessions[-1] if sessions else runs[-5:]
    if not current:
        return {"tilting": False, "momentum": 0, "message": ""}

    avg_floors = _avg_last_floor(current)
    hist_avg = _avg_last_floor(runs)
    consecutive_losses = _count_trailing_losses(current)
    durations = [r.run_time for r in current if r.run_time > 0]
    shortening = len(durations) > 2 and durations[-1] < durations[0] * 0.5

    momentum = 0
    if hist_avg > 0 and avg_floors < hist_avg * 0.6:
        momentum -= 40
    if consecutive_losses >= 3:
        momentum -= 30
    if consecutive_losses >= 5:
        momentum -= 20
    if shortening:
        momentum -= 20
    if current[-1].win:
        momentum += 30
    if len(current) <= 2:
        momentum += 10  # Short session, no pattern yet

    message = ""
    if momentum < -40:
        message = (
            f"Your last {len(current)} runs averaged floor {avg_floors:.0f}. "
            f"Your overall average is floor {hist_avg:.0f}. Consider taking a break."
        )

    return {
        "tilting": momentum < -40,
        "momentum": momentum,
        "consecutive_losses": consecutive_losses,
        "session_avg_floor": round(avg_floors, 1),
        "historical_avg_floor": round(hist_avg, 1),
        "session_size": len(current),
        "message": message,
    }


def _group_sessions(runs, window_hours):
    """Group runs into sessions based on timestamp proximity."""
    if not runs:
        return []
    sorted_runs = sorted(runs, key=lambda r: r.timestamp)
    sessions = [[sorted_runs[0]]]
    for r in sorted_runs[1:]:
        if r.timestamp - sessions[-1][-1].timestamp < window_hours * 3600:
            sessions[-1].append(r)
        else:
            sessions.append([r])
    return sessions


def _avg_last_floor(runs):
    floors = [r.floors[-1].floor for r in runs if r.floors]
    return sum(floors) / len(floors) if floors else 0


def _count_trailing_losses(runs):
    count = 0
    for r in reversed(runs):
        if r.win:
            break
        count += 1
    return count


# ── Anti-Pattern Detection ──

def detect_anti_patterns(runs):
    """Scan run history for named recurring mistakes."""
    if len(runs) < 5:
        return []

    patterns = []
    losses = [r for r in runs if not r.win]
    wins = [r for r in runs if r.win]

    # The Hoarder — dying with unused potions
    hoard_count = 0
    for r in losses:
        gained = sum(len(f.potions_gained) for f in r.floors)
        used = sum(len(f.potions_used) for f in r.floors)
        if gained >= 2 and used == 0:
            hoard_count += 1
    if hoard_count >= 3:
        patterns.append({
            "name": "The Hoarder",
            "description": f"You died with unused potions in {hoard_count} of {len(losses)} losses.",
            "severity": "warning",
            "stat": f"{hoard_count}/{len(losses)} deaths",
        })

    # The Greedy Builder — losing decks are larger
    if losses:
        avg_loss_size = sum(len(r.deck) for r in losses) / len(losses)
        if wins:
            avg_win_size = sum(len(r.deck) for r in wins) / len(wins)
            if avg_loss_size > avg_win_size * 1.3:
                patterns.append({
                    "name": "The Greedy Builder",
                    "description": f"Your losing decks average {avg_loss_size:.0f} cards vs {avg_win_size:.0f} in wins.",
                    "severity": "warning",
                    "stat": f"{avg_loss_size:.0f} vs {avg_win_size:.0f} cards",
                })
        elif avg_loss_size > 30:
            patterns.append({
                "name": "The Greedy Builder",
                "description": f"Your decks average {avg_loss_size:.0f} cards. Tighter decks draw key cards more often.",
                "severity": "info",
                "stat": f"avg {avg_loss_size:.0f} cards",
            })

    # The Coward — skipping elites
    total_elite_floors = 0
    total_combat_floors = 0
    for r in runs:
        for f in r.floors:
            if f.type in ("monster", "elite", "boss"):
                total_combat_floors += 1
            if f.type == "elite":
                total_elite_floors += 1
    if total_combat_floors > 20:
        elite_rate = total_elite_floors / total_combat_floors
        if elite_rate < 0.08:
            patterns.append({
                "name": "The Coward",
                "description": f"Only {elite_rate*100:.0f}% of your fights are elites. Elites give relics that carry runs.",
                "severity": "info",
                "stat": f"{elite_rate*100:.0f}% elite rate",
            })

    # Potion Paralysis — dying with potions in hand (different from hoarder: checks final state)
    potions_at_death = 0
    deaths_checked = 0
    for r in losses:
        gained = sum(len(f.potions_gained) for f in r.floors)
        used = sum(len(f.potions_used) for f in r.floors)
        remaining = gained - used
        if remaining >= 2:
            potions_at_death += 1
        deaths_checked += 1
    if deaths_checked > 5 and potions_at_death / deaths_checked > 0.3:
        patterns.append({
            "name": "Potion Paralysis",
            "description": f"You die with 2+ potions in {potions_at_death} of {deaths_checked} losses ({potions_at_death*100//deaths_checked}%).",
            "severity": "warning",
            "stat": f"{potions_at_death}/{deaths_checked} deaths",
        })

    return patterns


# ── Decision Quality ──

def decision_quality_profile(run, kb=None):
    """Classify decision-making style using consistency and diversity metrics."""
    decisions = _encode_decisions(run, kb)
    if len(decisions) < 10:
        return {"classification": "insufficient_data", "consistency": 0, "diversity": 0}

    consistency = _consistency_index(decisions)
    diversity = _diversity_score(decisions, m=2)

    if consistency > 1.2:
        classification = "formulaic"
    elif consistency < 0.4:
        classification = "chaotic"
    elif diversity < 0.3:
        classification = "rigid"
    elif diversity > 1.2:
        classification = "adaptive"
    else:
        classification = "strategic"

    return {
        "classification": classification,
        "consistency": round(consistency, 3),
        "diversity": round(diversity, 3),
    }


def _encode_decisions(run, kb):
    """Encode run decisions as a numeric series for analysis."""
    series = []
    for f in run.floors:
        # Encode floor type as base signal
        type_scores = {"monster": 1, "elite": 3, "boss": 5, "shop": 2,
                       "rest_site": 2, "event": 1, "treasure": 1, "unknown": 1}
        score = type_scores.get(f.type, 1)

        # Add card pick diversity signal
        if f.card_picked and kb:
            card = kb.get_card_by_id(f.card_picked)
            if card:
                type_bonus = {"Attack": 1, "Skill": 2, "Power": 3}.get(card.type, 0)
                score += type_bonus

        # Add damage signal (normalized)
        if f.damage_taken > 0 and f.max_hp > 0:
            score += int(f.damage_taken / f.max_hp * 5)

        series.append(score)
    return series


def _consistency_index(series):
    """Measure how consistent decision patterns are across the run (pure Python)."""
    n = len(series)
    if n < 10:
        return 0.5
    mean = sum(series) / n
    devs = [x - mean for x in series]
    cumdev = []
    s = 0
    for d in devs:
        s += d
        cumdev.append(s)
    R = max(cumdev) - min(cumdev)
    S = (sum(d * d for d in devs) / n) ** 0.5
    if S == 0 or R == 0:
        return 0.5
    return math.log(R / S) / math.log(n)


def _diversity_score(series, m=2):
    """Measure decision diversity — how varied the play patterns are (pure Python)."""
    n = len(series)
    if n < m + 2:
        return 0
    r = 0.2 * _std(series)
    if r == 0:
        return 0

    def count_matches(template_len):
        count = 0
        for i in range(n - template_len):
            for j in range(i + 1, n - template_len):
                if all(abs(series[i + k] - series[j + k]) <= r for k in range(template_len)):
                    count += 1
        return count

    A = count_matches(m)
    B = count_matches(m + 1)
    if A == 0 or B == 0:
        return 0
    return -math.log(B / A)


def _std(series):
    n = len(series)
    if n < 2:
        return 0
    mean = sum(series) / n
    return (sum((x - mean) ** 2 for x in series) / n) ** 0.5
