"""Pheromone strategy memory — track which strategies you use vs forget."""
import json
import time
from pathlib import Path

from sts2.config import DATA_DIR

PHEROMONE_FILE = DATA_DIR / "pheromones.json"
DECAY_RATE = 0.95


def load_pheromones():
    """Load pheromone state from disk."""
    if PHEROMONE_FILE.exists():
        try:
            return json.loads(PHEROMONE_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def update_pheromones(run, kb):
    """Decay all trails and strengthen the strategy used in this run."""
    pheromones = load_pheromones()

    # Decay all existing trails
    for strategy in pheromones:
        pheromones[strategy]["strength"] *= DECAY_RATE

    # Strengthen used strategy
    archetype = kb.classify_archetype(run.deck, run.character) if run.deck else {}
    if archetype.get("name"):
        name = f"{run.character}: {archetype['name']}"
        if name not in pheromones:
            pheromones[name] = {"strength": 0, "total_runs": 0, "wins": 0}
        pheromones[name]["strength"] = min(1.0, pheromones[name]["strength"] + 0.15)
        pheromones[name]["total_runs"] += 1
        if run.win:
            pheromones[name]["wins"] += 1
        pheromones[name]["last_used"] = time.time()

    # Prune dead trails (strength < 0.01)
    pheromones = {k: v for k, v in pheromones.items() if v.get("strength", 0) >= 0.01}

    # Save
    try:
        PHEROMONE_FILE.write_text(json.dumps(pheromones, indent=2), encoding="utf-8")
    except OSError:
        pass

    return pheromones


def get_strategy_memory():
    """Get all strategies sorted by strength (brightest trails first)."""
    pheromones = load_pheromones()
    return sorted(
        [{"name": k, **v} for k, v in pheromones.items()],
        key=lambda p: -p.get("strength", 0),
    )
