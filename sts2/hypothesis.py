"""Hypothesis Lab — formally test strategic beliefs with Bayesian statistics."""
import json
import time

from sts2.config import state_path


def _hypotheses_file():
    """Resolved per call, not bound at import.

    A module-level constant would freeze the path before tests or the state
    migration could redirect it, and it is user-authored data, so it belongs in
    STATE_DIR rather than the shipped data directory.
    """
    return state_path("hypotheses.json")


def load_hypotheses():
    path = _hypotheses_file()
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
        # Anything but an object is corrupt state; every caller iterates
        # .items() and would 500 on a top-level array.
        if isinstance(data, dict):
            return data
    return {}


def save_hypotheses(hypotheses) -> bool:
    from sts2.persist import write_json_atomic
    return write_json_atomic(_hypotheses_file(), hypotheses)


def register_hypothesis(hyp_id, text, condition_type, params):
    """Register a new hypothesis to track.

    condition_type: 'elite_skip' | 'deck_size' | 'card_pick' | 'character'
    params: dict with condition-specific parameters
    """
    hypotheses = load_hypotheses()
    hypotheses[hyp_id] = {
        "text": text,
        "condition_type": condition_type,
        "params": params,
        "prior": 0.5,
        "runs_tested": 0,
        "runs_matching": 0,
        "wins_matching": 0,
        "wins_not_matching": 0,
        "runs_not_matching": 0,
        "created": time.time(),
        "verdict": "insufficient_data",
    }
    save_hypotheses(hypotheses)
    return hypotheses[hyp_id]


def update_hypothesis(hyp_id, run):
    """Update a hypothesis with data from a new run. Bayesian posterior update."""
    hypotheses = load_hypotheses()
    if hyp_id not in hypotheses:
        return None

    hyp = hypotheses[hyp_id]
    matches = _check_condition(hyp, run)

    if matches:
        hyp["runs_matching"] += 1
        if run.win:
            hyp["wins_matching"] += 1
    else:
        hyp["runs_not_matching"] += 1
        if run.win:
            hyp["wins_not_matching"] += 1

    hyp["runs_tested"] += 1

    # Compute posterior
    if hyp["runs_matching"] >= 3 and hyp["runs_not_matching"] >= 3:
        wr_match = hyp["wins_matching"] / hyp["runs_matching"]
        wr_no_match = hyp["wins_not_matching"] / hyp["runs_not_matching"]
        effect = wr_match - wr_no_match

        if hyp["runs_tested"] >= 10:
            if effect > 0.1:
                hyp["verdict"] = "confirmed"
            elif effect < -0.1:
                hyp["verdict"] = "refuted"
            else:
                hyp["verdict"] = "inconclusive"
        hyp["effect_size"] = round(effect, 3)
        hyp["prior"] = round(0.5 + effect / 2, 3)  # Simple posterior

    save_hypotheses(hypotheses)
    return hyp


def _check_condition(hyp, run):
    """Check if a run matches the hypothesis condition."""
    ct = hyp["condition_type"]
    params = hyp.get("params", {})

    if ct == "elite_skip":
        elite_count = sum(1 for f in run.floors if f.type == "elite")
        return elite_count == 0

    if ct == "deck_size":
        threshold = params.get("max_size", 25)
        return len(run.deck) <= threshold

    if ct == "card_pick":
        card_id = params.get("card_id", "")
        return card_id in run.deck

    if ct == "character":
        return run.character == params.get("character", "")

    return False
