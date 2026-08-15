"""Tilt detection, anti-pattern scanning and decision-quality scoring.

Every prior reference to this module was a mock asserting `mock.called`, so
each function could have returned a constant and the suite would have stayed
green. These tests assert computed values and contrast inputs that must give
different answers.

The two statistics at the bottom (`_consistency_index`, `_diversity_score`)
are checked against the mathematical properties that define them -- a Hurst
R/S exponent tends to 1 for a pure trend, and a sample entropy is 0 for a
constant series -- rather than against numbers copied out of a previous run,
which would only pin whatever the code happened to do.
"""
import math

import pytest

from sts2.behavior import (
    _avg_last_floor,
    _consistency_index,
    _count_trailing_losses,
    _diversity_score,
    _encode_decisions,
    _group_sessions,
    _std,
    decision_quality_profile,
    detect_anti_patterns,
    detect_tilt,
)
from sts2.models import RunFloor, RunHistory

HOUR = 3600


def _floor(n, ftype="monster", dmg=0, gained=(), used=(), pick="", max_hp=80):
    return RunFloor(floor=n, type=ftype, damage_taken=dmg, max_hp=max_hp,
                    potions_gained=list(gained), potions_used=list(used),
                    card_picked=pick)


def _run(rid, win=False, ts=1_700_000_000, floors=None, deck=None, run_time=600):
    return RunHistory(id=rid, character="Ironclad", win=win, timestamp=ts,
                      run_time=run_time, deck=deck or ["CARD.STRIKE"] * 10,
                      floors=floors if floors is not None else [_floor(1)])


def _climb(rid, top, **kw):
    """A run that reached `top` floors."""
    return _run(rid, floors=[_floor(i) for i in range(1, top + 1)], **kw)


# ------------------------------------------------------------------- helpers

def test_group_sessions_splits_on_a_gap_longer_than_the_window():
    runs = [_run("a", ts=0), _run("b", ts=HOUR), _run("c", ts=HOUR * 10)]
    sessions = _group_sessions(runs, window_hours=4)
    assert [[r.id for r in s] for s in sessions] == [["a", "b"], ["c"]]


def test_group_sessions_orders_by_timestamp_before_grouping():
    """Run history is not guaranteed sorted; grouping unsorted input would
    scatter one sitting across several "sessions"."""
    runs = [_run("c", ts=HOUR * 10), _run("a", ts=0), _run("b", ts=HOUR)]
    assert [[r.id for r in s] for s in _group_sessions(runs, 4)] == [["a", "b"], ["c"]]


def test_group_sessions_of_nothing_is_nothing():
    assert _group_sessions([], 4) == []


def test_avg_last_floor_uses_the_final_floor_of_each_run():
    assert _avg_last_floor([_climb("a", 10), _climb("b", 20)]) == 15


def test_avg_last_floor_of_runs_without_floors_is_zero():
    assert _avg_last_floor([_run("a", floors=[])]) == 0


def test_count_trailing_losses_stops_at_the_most_recent_win():
    runs = [_run("a"), _run("b", win=True), _run("c"), _run("d")]
    assert _count_trailing_losses(runs) == 2


def test_count_trailing_losses_counts_every_run_when_none_were_won():
    assert _count_trailing_losses([_run("a"), _run("b")]) == 2


# --------------------------------------------------------------------- tilt

def test_tilt_needs_at_least_three_runs():
    assert detect_tilt([_run("a"), _run("b")]) == {
        "tilting": False, "momentum": 0, "message": ""}


def test_tilt_fires_when_the_current_session_collapses_against_history():
    """The signal is a session far below the player's own baseline -- not an
    absolute floor number, which would just flag every new player."""
    good = [_climb("g%d" % i, 30, ts=i * HOUR, win=True) for i in range(3)]
    bad = [_climb("b%d" % i, 4, ts=HOUR * 100 + i * HOUR) for i in range(3)]
    result = detect_tilt(good + bad)
    assert result["tilting"] is True
    assert result["momentum"] <= -70          # -40 collapse, -30 three losses
    assert result["consecutive_losses"] == 3
    assert result["session_avg_floor"] == 4.0
    assert result["historical_avg_floor"] == 17.0
    assert "Consider taking a break" in result["message"]


def test_tilt_deepens_after_five_straight_losses():
    short = detect_tilt([_climb("b%d" % i, 4, ts=HOUR * 100 + i * HOUR)
                         for i in range(3)])
    long = detect_tilt([_climb("b%d" % i, 4, ts=HOUR * 100 + i * HOUR)
                        for i in range(5)])
    assert long["momentum"] < short["momentum"]


def test_tilt_penalises_sessions_whose_runs_keep_getting_shorter():
    """Rage-quitting earlier and earlier is the behavioural tell; a session of
    equal-length runs with the same results must not score the same."""
    steady = [_climb("s%d" % i, 10, ts=i * HOUR, run_time=1000) for i in range(3)]
    quitting = [_climb("q%d" % i, 10, ts=i * HOUR, run_time=t)
                for i, t in enumerate((1000, 800, 100))]
    assert detect_tilt(quitting)["momentum"] < detect_tilt(steady)["momentum"]


def test_a_win_lifts_momentum():
    losses = [_climb("l%d" % i, 10, ts=i * HOUR) for i in range(3)]
    ending_in_a_win = losses[:2] + [_climb("w", 10, ts=2 * HOUR, win=True)]
    assert detect_tilt(ending_in_a_win)["momentum"] > detect_tilt(losses)["momentum"]


def test_a_session_of_one_or_two_runs_is_not_yet_a_pattern():
    """Two bad runs after a break is noise. Without this credit the tool would
    tell someone to take a break they just came back from."""
    history = [_climb("h%d" % i, 30, ts=i * HOUR, win=True) for i in range(4)]
    fresh = [_climb("n", 3, ts=HOUR * 500)]
    assert detect_tilt(history + fresh)["momentum"] >= -30
    assert detect_tilt(history + fresh)["tilting"] is False


def test_tilt_reports_no_message_when_not_tilting():
    winners = [_climb("w%d" % i, 40, ts=i * HOUR, win=True) for i in range(4)]
    result = detect_tilt(winners)
    assert result["tilting"] is False
    assert result["message"] == ""


# ------------------------------------------------------------ anti-patterns

def test_anti_patterns_need_at_least_five_runs():
    assert detect_anti_patterns([_run(str(i)) for i in range(4)]) == []


def _named(patterns):
    return {p["name"] for p in patterns}


def test_the_hoarder_fires_on_repeated_deaths_with_unused_potions():
    runs = [_run("h%d" % i, floors=[_floor(1, gained=("P1", "P2"))])
            for i in range(3)]
    runs += [_run("ok%d" % i, floors=[_floor(1, gained=("P1",), used=("P1",))])
             for i in range(3)]
    patterns = detect_anti_patterns(runs)
    assert "The Hoarder" in _named(patterns)
    hoarder = next(p for p in patterns if p["name"] == "The Hoarder")
    assert hoarder["stat"] == "3/6 deaths"
    assert hoarder["severity"] == "warning"


def test_the_hoarder_stays_quiet_when_potions_get_used():
    runs = [_run("u%d" % i, floors=[_floor(1, gained=("P1", "P2"), used=("P1",))])
            for i in range(6)]
    assert "The Hoarder" not in _named(detect_anti_patterns(runs))


def test_the_greedy_builder_compares_losing_decks_against_winning_ones():
    losses = [_run("l%d" % i, deck=["CARD.X"] * 40) for i in range(3)]
    wins = [_run("w%d" % i, win=True, deck=["CARD.X"] * 20) for i in range(3)]
    patterns = detect_anti_patterns(losses + wins)
    greedy = next(p for p in patterns if p["name"] == "The Greedy Builder")
    assert greedy["stat"] == "40 vs 20 cards"
    assert greedy["severity"] == "warning"


def test_the_greedy_builder_falls_back_to_an_absolute_size_without_any_wins():
    """A player with no wins has no personal baseline to compare against, so
    the check becomes advisory rather than a warning."""
    losses = [_run("l%d" % i, deck=["CARD.X"] * 35) for i in range(5)]
    greedy = next(p for p in detect_anti_patterns(losses)
                  if p["name"] == "The Greedy Builder")
    assert greedy["severity"] == "info"
    assert greedy["stat"] == "avg 35 cards"


def test_a_modest_deck_with_no_wins_is_not_flagged():
    losses = [_run("l%d" % i, deck=["CARD.X"] * 20) for i in range(5)]
    assert "The Greedy Builder" not in _named(detect_anti_patterns(losses))


def test_the_coward_fires_when_elites_are_a_tiny_share_of_fights():
    floors = [_floor(i) for i in range(1, 26)]          # 25 monster fights
    runs = [_run("r%d" % i, floors=floors) for i in range(5)]
    coward = next(p for p in detect_anti_patterns(runs) if p["name"] == "The Coward")
    assert coward["stat"] == "0% elite rate"
    assert coward["severity"] == "info"


def test_the_coward_stays_quiet_for_a_healthy_elite_rate():
    floors = [_floor(i, ftype="elite" if i % 4 == 0 else "monster")
              for i in range(1, 26)]
    runs = [_run("r%d" % i, floors=floors) for i in range(5)]
    assert "The Coward" not in _named(detect_anti_patterns(runs))


def test_the_coward_needs_a_meaningful_sample_of_fights():
    """Under 20 combats the rate is noise, so nothing is claimed."""
    floors = [_floor(i) for i in range(1, 4)]
    runs = [_run("r%d" % i, floors=floors) for i in range(5)]
    assert "The Coward" not in _named(detect_anti_patterns(runs))


def test_potion_paralysis_fires_when_most_deaths_leave_potions_unspent():
    runs = [_run("p%d" % i, floors=[_floor(1, gained=("A", "B", "C"), used=("A",))])
            for i in range(6)]
    paralysis = next(p for p in detect_anti_patterns(runs)
                     if p["name"] == "Potion Paralysis")
    assert paralysis["stat"] == "6/6 deaths"
    assert "100%" in paralysis["description"]


def test_potion_paralysis_needs_more_than_five_deaths():
    runs = [_run("p%d" % i, floors=[_floor(1, gained=("A", "B", "C"))])
            for i in range(5)]
    assert "Potion Paralysis" not in _named(detect_anti_patterns(runs))


def test_a_clean_history_reports_no_anti_patterns():
    runs = [_run("w%d" % i, win=True, deck=["CARD.X"] * 15,
                 floors=[_floor(1, ftype="elite")]) for i in range(6)]
    assert detect_anti_patterns(runs) == []


# ----------------------------------------------------------- decision coding

class _StubKB:
    def __init__(self, types):
        self._types = types

    def get_card_by_id(self, cid):
        kind = self._types.get(cid)
        if kind is None:
            return None
        return type("Card", (), {"type": kind})()


def test_encode_decisions_scores_floor_types():
    floors = [_floor(1, ftype=t) for t in
              ("monster", "elite", "boss", "shop", "rest", "event", "treasure")]
    assert _encode_decisions(_run("a", floors=floors), None) == [1, 3, 5, 2, 2, 1, 1]


def test_encode_decisions_scores_an_unknown_floor_type_as_one():
    assert _encode_decisions(_run("a", floors=[_floor(1, ftype="wormhole")]),
                             None) == [1]


def test_encode_decisions_adds_a_bonus_for_the_card_type_picked():
    kb = _StubKB({"CARD.A": "Attack", "CARD.S": "Skill", "CARD.P": "Power",
                  "CARD.C": "Curse"})
    floors = [_floor(1, pick=c) for c in ("CARD.A", "CARD.S", "CARD.P", "CARD.C")]
    assert _encode_decisions(_run("a", floors=floors), kb) == [2, 3, 4, 1]


def test_encode_decisions_ignores_a_card_the_knowledge_base_does_not_know():
    kb = _StubKB({})
    assert _encode_decisions(_run("a", floors=[_floor(1, pick="CARD.MOD")]), kb) == [1]


def test_encode_decisions_ignores_picks_when_there_is_no_knowledge_base():
    assert _encode_decisions(_run("a", floors=[_floor(1, pick="CARD.A")]), None) == [1]


def test_encode_decisions_adds_a_signal_proportional_to_damage_taken():
    floors = [_floor(1, dmg=0, max_hp=80), _floor(2, dmg=40, max_hp=80),
              _floor(3, dmg=80, max_hp=80)]
    assert _encode_decisions(_run("a", floors=floors), None) == [1, 1 + 2, 1 + 5]


def test_encode_decisions_ignores_damage_when_max_hp_is_unknown():
    assert _encode_decisions(_run("a", floors=[_floor(1, dmg=40, max_hp=0)]),
                             None) == [1]


# ------------------------------------------------------------- the statistics

def test_std_of_a_constant_series_is_zero():
    assert _std([4, 4, 4, 4]) == 0


def test_std_matches_the_population_definition():
    # population std of 2,4,4,4,5,5,7,9 is exactly 2
    assert _std([2, 4, 4, 4, 5, 5, 7, 9]) == pytest.approx(2.0)


def test_std_of_fewer_than_two_points_is_zero():
    assert _std([5]) == 0
    assert _std([]) == 0


def test_consistency_of_a_short_series_is_the_neutral_default():
    assert _consistency_index([1, 2, 3]) == 0.5


def test_consistency_of_a_flat_series_is_the_neutral_default():
    """A run with no variation has no rescaled range to measure; returning the
    midpoint keeps it out of both the "formulaic" and "chaotic" buckets."""
    assert _consistency_index([3] * 20) == 0.5


@pytest.mark.parametrize("n", [10, 20, 40, 100])
def test_consistency_of_a_pure_trend_matches_the_closed_form(n):
    """Validated against the analytic value rather than a recorded output.

    For the ramp 1..n the cumulative deviation is S_k = k(k-n)/2, so it peaks
    at 0 (k=n) and bottoms at -n^2/8 (k=n/2), giving R = n^2/8 exactly, while
    S is the population standard deviation sqrt((n^2-1)/12). Anything that
    quietly changes the estimator -- sample vs population variance, a
    different cumulative-deviation convention -- breaks this equality.
    """
    R = n * n / 8
    S = math.sqrt((n * n - 1) / 12)
    assert _consistency_index(list(range(1, n + 1))) == pytest.approx(
        math.log(R / S) / math.log(n))


def test_consistency_of_a_trend_rises_slowly_towards_one_with_length():
    """The Hurst exponent of a deterministic ramp tends to 1, but only as
    log(0.433n)/log(n) -- it is still ~0.77 at n=40, which is why this is a
    monotonicity check and not an assertion that it is close to 1."""
    assert (_consistency_index(list(range(1, 21)))
            < _consistency_index(list(range(1, 41)))
            < _consistency_index(list(range(1, 201))) < 1)


def test_a_trend_scores_higher_than_an_alternating_series():
    trend = _consistency_index(list(range(1, 41)))
    alternating = _consistency_index([1, 2] * 20)
    assert trend > alternating


def test_diversity_of_a_constant_series_is_zero():
    """Sample entropy of a series with no variation is 0 by definition."""
    assert _diversity_score([7] * 30) == 0


def test_diversity_of_too_short_a_series_is_zero():
    assert _diversity_score([1, 2, 3], m=2) == 0


def test_diversity_of_a_repeating_pattern_is_lower_than_of_a_varied_one():
    periodic = _diversity_score([1, 2, 3] * 10)
    varied = _diversity_score([1, 9, 2, 8, 3, 7, 1, 6, 4, 2, 9, 5,
                               3, 8, 1, 7, 2, 6, 4, 9, 5, 3, 8, 2,
                               7, 1, 6, 9, 4, 5])
    assert varied > periodic


def test_diversity_is_non_negative_and_finite():
    score = _diversity_score([1, 3, 2, 5, 4, 2, 6, 1, 3, 5, 2, 4, 6, 1, 3])
    assert score >= 0 and math.isfinite(score)


# ------------------------------------------------------- decision classification

def _run_with_floors(n):
    return _run("a", floors=[_floor(i) for i in range(1, n + 1)])


def test_decision_profile_needs_ten_decisions():
    assert decision_quality_profile(_run_with_floors(5)) == {
        "classification": "insufficient_data", "consistency": 0, "diversity": 0}


@pytest.mark.parametrize("consistency, diversity, expected", [
    (1.5, 0.8, "formulaic"),      # consistency dominates
    (0.2, 0.8, "chaotic"),
    (0.8, 0.1, "rigid"),
    (0.8, 1.5, "adaptive"),
    (0.8, 0.8, "strategic"),
    # boundaries: the thresholds are exclusive on both sides
    (1.2, 0.8, "strategic"),
    (0.4, 0.8, "strategic"),
])
def test_decision_profile_classifies_by_consistency_then_diversity(
        monkeypatch, consistency, diversity, expected):
    monkeypatch.setattr("sts2.behavior._consistency_index", lambda _s: consistency)
    monkeypatch.setattr("sts2.behavior._diversity_score", lambda _s, m=2: diversity)
    profile = decision_quality_profile(_run_with_floors(12))
    assert profile["classification"] == expected
    assert profile["consistency"] == round(consistency, 3)
    assert profile["diversity"] == round(diversity, 3)


def test_decision_profile_runs_end_to_end_on_a_real_run():
    """No monkeypatching: a varied run must produce a real classification and
    finite statistics."""
    floors = [_floor(i, ftype=t, dmg=d) for i, (t, d) in enumerate(
        [("monster", 5), ("elite", 20), ("rest", 0), ("monster", 8),
         ("shop", 0), ("monster", 12), ("elite", 25), ("event", 0),
         ("monster", 3), ("boss", 40), ("rest", 0), ("monster", 7)], start=1)]
    profile = decision_quality_profile(_run("a", floors=floors))
    assert profile["classification"] in {
        "formulaic", "chaotic", "rigid", "adaptive", "strategic"}
    assert math.isfinite(profile["consistency"])
    assert math.isfinite(profile["diversity"])
