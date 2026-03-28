"""The Prophecy Engine — pre-run predictions based on historical data."""


def generate_prophecy(character, ascension, runs):
    """Predict outcome before starting a run.

    Uses historical runs with the same character at similar ascension
    to estimate win probability, danger zones, and recommendations.
    """
    comparable = [
        r for r in runs
        if r.character == character and abs(r.ascension - ascension) <= 2
    ]
    if len(comparable) < 5:
        return {"available": False, "reason": f"Need 5+ {character} runs (have {len(comparable)})"}

    wins = sum(1 for r in comparable if r.win)
    win_rate = wins / len(comparable)

    # Floor-of-death distribution
    death_floors = [r.floors[-1].floor for r in comparable if not r.win and r.floors]
    danger_zone = _find_danger_zone(death_floors)

    # Recommendation
    recommendation = _generate_recommendation(comparable, character)

    return {
        "available": True,
        "character": character,
        "ascension": ascension,
        "win_probability": round(win_rate * 100, 1),
        "sample_size": len(comparable),
        "danger_zone": danger_zone,
        "recommendation": recommendation,
        "avg_floor": round(
            sum(r.floors[-1].floor for r in comparable if r.floors)
            / max(sum(1 for r in comparable if r.floors), 1), 1
        ),
    }


def grade_prophecy(prophecy, run):
    """After a run ends, grade how the prophecy did."""
    if not prophecy.get("available"):
        return None

    actual_floor = run.floors[-1].floor if run.floors else 0
    predicted_avg = prophecy.get("avg_floor", 0)
    beat_prediction = actual_floor > predicted_avg

    return {
        "predicted_avg_floor": predicted_avg,
        "actual_floor": actual_floor,
        "beat_prediction": beat_prediction,
        "predicted_win_prob": prophecy["win_probability"],
        "actual_win": run.win,
        "beat_odds": run.win and prophecy["win_probability"] < 50,
    }


def _find_danger_zone(death_floors):
    """Find the floor range where most deaths occur."""
    if len(death_floors) < 3:
        return None

    # Bin into ranges of 5
    bins = {}
    for f in death_floors:
        bin_start = (f // 5) * 5
        key = f"{bin_start}-{bin_start + 4}"
        bins[key] = bins.get(key, 0) + 1

    if not bins:
        return None

    worst_range = max(bins, key=bins.get)
    worst_count = bins[worst_range]
    pct = int(worst_count / len(death_floors) * 100)

    return {
        "range": worst_range,
        "deaths": worst_count,
        "percentage": pct,
    }


def _generate_recommendation(runs, character):
    """Generate a strategic recommendation based on win/loss patterns."""
    wins = [r for r in runs if r.win]
    losses = [r for r in runs if not r.win]

    if not losses:
        return "You're winning consistently. Keep doing what you're doing."

    if not wins:
        # Compare early deaths vs late deaths
        early_deaths = sum(1 for r in losses if r.floors and r.floors[-1].floor <= 15)
        if early_deaths > len(losses) * 0.5:
            return "Focus on early survival. Prioritize Block and front-loaded damage in Act 1."
        return "You're reaching mid-game consistently. Focus on scaling cards for boss fights."

    # Compare win deck sizes vs loss deck sizes
    avg_win_size = sum(len(r.deck) for r in wins) / len(wins)
    avg_loss_size = sum(len(r.deck) for r in losses) / len(losses)
    if avg_loss_size > avg_win_size * 1.3:
        return f"Your winning decks average {avg_win_size:.0f} cards vs {avg_loss_size:.0f} in losses. Consider being more selective with card picks."

    return "Study your winning runs for patterns. The Spire rewards consistency."
