"""Hypothesis Lab — test strategic beliefs with a Beta-Binomial model.

Each hypothesis splits run history into a matching arm and a non-matching
arm and compares win rates. Both arms get a uniform Beta(1,1) prior; the
posterior probability that the matching arm's true win rate is higher is
computed exactly (no sampling) and drives the verdict. The previous scoring
subtracted two raw win rates and called 0.5 + effect/2 a "posterior" — no
prior, no likelihood, no uncertainty.
"""
import json
import math
import time

from sts2.config import state_path

# A verdict requires at least this many runs in EACH arm, and 95% posterior
# probability in one direction.
_MIN_RUNS_PER_ARM = 3
_DECISION_THRESHOLD = 0.95


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


def evaluate_hypotheses(hypotheses: dict, runs) -> dict:
    """Re-evaluate every hypothesis against a snapshot of run history.

    Pure computation on the passed dict — no file I/O. The previous design
    reloaded and rewrote the whole hypotheses file once per run x hypothesis
    (roughly 10,001 synchronous writes for one page view at 1,000 runs and
    10 hypotheses), blocked the event loop doing it, and silently corrupted
    counters whenever a mid-loop write failed.
    """
    for hyp in hypotheses.values():
        hyp["runs_tested"] = 0
        hyp["runs_matching"] = 0
        hyp["runs_not_matching"] = 0
        hyp["wins_matching"] = 0
        hyp["wins_not_matching"] = 0
        hyp["verdict"] = "insufficient_data"
        for stale in ("effect_size", "prob_effect", "posterior_match",
                      "posterior_not_matching", "prior"):
            hyp.pop(stale, None)
    for run in runs:
        for hyp in hypotheses.values():
            if _check_condition(hyp, run):
                hyp["runs_matching"] += 1
                if run.win:
                    hyp["wins_matching"] += 1
            else:
                hyp["runs_not_matching"] += 1
                if run.win:
                    hyp["wins_not_matching"] += 1
            hyp["runs_tested"] += 1
    for hyp in hypotheses.values():
        _finalise_verdict(hyp)
    return hypotheses


def _prob_first_beats_second(a1: int, b1: int, a2: int, b2: int) -> float:
    """Exact P(p1 > p2) for p1 ~ Beta(a1,b1), p2 ~ Beta(a2,b2), integer a1.

    Closed form: sum over i in [0, a1) of
        B(a2+i, b1+b2) / ((b1+i) * B(1+i, b1) * B(a2, b2))
    evaluated in log space to stay finite for large counts. Validated in
    tests against an analytically known case (Beta(2,1) vs Beta(1,2) = 5/6).
    """
    def lbeta(x: float, y: float) -> float:
        return math.lgamma(x) + math.lgamma(y) - math.lgamma(x + y)

    total = 0.0
    for i in range(int(a1)):
        total += math.exp(lbeta(a2 + i, b1 + b2) - math.log(b1 + i)
                          - lbeta(1 + i, b1) - lbeta(a2, b2))
    return min(1.0, max(0.0, total))


def _finalise_verdict(hyp: dict) -> None:
    """Beta-Binomial posterior comparison of the two arms' win rates."""
    n_match, w_match = hyp["runs_matching"], hyp["wins_matching"]
    n_other, w_other = hyp["runs_not_matching"], hyp["wins_not_matching"]
    if n_match < _MIN_RUNS_PER_ARM or n_other < _MIN_RUNS_PER_ARM:
        return
    a1, b1 = 1 + w_match, 1 + n_match - w_match
    a2, b2 = 1 + w_other, 1 + n_other - w_other
    posterior_match = a1 / (a1 + b1)
    posterior_other = a2 / (a2 + b2)
    prob = _prob_first_beats_second(a1, b1, a2, b2)
    hyp["posterior_match"] = round(posterior_match, 3)
    hyp["posterior_not_matching"] = round(posterior_other, 3)
    hyp["effect_size"] = round(posterior_match - posterior_other, 3)
    hyp["prob_effect"] = round(prob, 3)
    if prob >= _DECISION_THRESHOLD:
        hyp["verdict"] = "confirmed"
    elif prob <= 1 - _DECISION_THRESHOLD:
        hyp["verdict"] = "refuted"
    else:
        hyp["verdict"] = "inconclusive"


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
