"""Ghost splits, prophecy predictions, rivalry diffs, and the POSIX fsync path.

These four are small enough that a single test file keeps them together: each
is a pure function over run history, and each had only a smoke test asserting
that a mock was called -- so any of them could have returned a constant.

The persist case at the bottom is here because the durability path it covers
only runs on POSIX, and every developer machine on this project is Windows,
where it is an unconditional early return.
"""
import os

import pytest

from sts2.ghost import compute_splits, find_ghost_run, ghost_summary
from sts2.models import CurrentRun, RunFloor, RunHistory
from sts2.prophecy import (
    _find_danger_zone,
    _generate_recommendation,
    generate_prophecy,
    grade_prophecy,
)
from sts2.rivalry import compare_seed_runs


def _floor(n, hp=70, gold=100, pick=""):
    return RunFloor(floor=n, type="monster", current_hp=hp, max_hp=80,
                    gold=gold, card_picked=pick)


def _run(rid, win=False, asc=5, char="Ironclad", floors=None, run_time=1200,
         deck=None, seed="SEED1"):
    return RunHistory(id=rid, character=char, win=win, ascension=asc, seed=seed,
                      run_time=run_time, deck=deck or ["CARD.X"] * 15,
                      floors=floors if floors is not None else [_floor(10)])


# ------------------------------------------------------------ ghost selection

def test_no_runs_with_this_character_means_no_ghost():
    assert find_ghost_run("Silent", 5, [_run("a", char="Ironclad")]) is None


def test_ghost_prefers_a_win_at_a_similar_ascension():
    runs = [_run("far", win=True, asc=20), _run("near", win=True, asc=6)]
    assert find_ghost_run("Ironclad", 5, runs).id == "near"


def test_ghost_prefers_the_higher_ascension_among_close_wins():
    runs = [_run("a5", win=True, asc=5), _run("a7", win=True, asc=7)]
    assert find_ghost_run("Ironclad", 5, runs).id == "a7"


def test_ghost_breaks_an_ascension_tie_on_the_faster_run():
    runs = [_run("slow", win=True, asc=5, run_time=9000),
            _run("fast", win=True, asc=5, run_time=1200)]
    assert find_ghost_run("Ironclad", 5, runs).id == "fast"


def test_ghost_falls_back_to_any_win_when_none_are_close():
    """Ascension 20 against a fresh ascension-0 run is a poor comparison, but
    it beats having no ghost at all."""
    runs = [_run("distant", win=True, asc=20), _run("loss", win=False, asc=1)]
    assert find_ghost_run("Ironclad", 0, runs).id == "distant"


def test_ghost_falls_back_to_the_deepest_run_when_there_are_no_wins():
    runs = [_run("shallow", floors=[_floor(5)]), _run("deep", floors=[_floor(38)])]
    assert find_ghost_run("Ironclad", 5, runs).id == "deep"


def test_no_wins_and_no_floors_means_no_ghost():
    assert find_ghost_run("Ironclad", 5, [_run("empty", floors=[])]) is None


# --------------------------------------------------------------- ghost splits

def test_splits_against_a_missing_ghost_are_empty():
    assert compute_splits(CurrentRun(active=True), None) == []


def test_splits_against_a_ghost_with_no_floors_are_empty():
    assert compute_splits(CurrentRun(active=True), _run("g", floors=[])) == []


def test_splits_compare_hp_gold_and_deck_floor_by_floor():
    ghost = _run("g", floors=[_floor(1, hp=70, gold=100),
                              _floor(2, hp=60, gold=150, pick="CARD.A")])
    current = _run("c", floors=[_floor(1, hp=75, gold=90),
                                _floor(2, hp=50, gold=200, pick="CARD.B")])
    splits = compute_splits(current, ghost)
    assert [s["floor"] for s in splits] == [1, 2]
    assert splits[0]["hp_delta"] == 5 and splits[0]["ahead"] is True
    assert splits[0]["gold_delta"] == -10
    assert splits[1]["hp_delta"] == -10 and splits[1]["ahead"] is False
    assert splits[1]["gold_delta"] == 50
    # both picked one card, so the deck sizes stay level
    assert splits[1]["deck_delta"] == 0


def test_splits_track_a_deck_that_grew_faster_than_the_ghosts():
    ghost = _run("g", floors=[_floor(1), _floor(2)])
    current = _run("c", floors=[_floor(1, pick="CARD.A"), _floor(2, pick="CARD.B")])
    assert [s["deck_delta"] for s in compute_splits(current, ghost)] == [1, 2]


def test_floors_the_ghost_never_reached_are_skipped():
    ghost = _run("g", floors=[_floor(1)])
    current = _run("c", floors=[_floor(1), _floor(2), _floor(3)])
    assert [s["floor"] for s in compute_splits(current, ghost)] == [1]


def test_a_current_run_without_floors_produces_no_splits():
    assert compute_splits(CurrentRun(active=True), _run("g")) == []


# -------------------------------------------------------------- ghost summary

def test_summary_of_no_splits_is_nothing():
    assert ghost_summary([]) is None


@pytest.mark.parametrize("last_delta, status", [(5, "ahead"), (-5, "behind"), (0, "even")])
def test_summary_status_reflects_the_latest_floor(last_delta, status):
    splits = [{"hp_delta": 10, "gold_delta": 0},
              {"hp_delta": last_delta, "gold_delta": 25}]
    summary = ghost_summary(splits)
    assert summary["status"] == status
    assert summary["current_hp_delta"] == last_delta
    assert summary["current_gold_delta"] == 25


def test_summary_counts_floors_ahead_and_behind_and_averages_the_gap():
    splits = [{"hp_delta": d, "gold_delta": 0} for d in (10, -4, 0, 6)]
    summary = ghost_summary(splits)
    assert summary["floors_ahead"] == 2
    assert summary["floors_behind"] == 1
    assert summary["avg_hp_delta"] == 3.0


# ------------------------------------------------------------------- prophecy

def test_prophecy_needs_five_comparable_runs():
    result = generate_prophecy("Ironclad", 5, [_run(str(i)) for i in range(4)])
    assert result["available"] is False
    assert "have 4" in result["reason"]


def test_prophecy_only_counts_runs_within_two_ascensions():
    runs = [_run(str(i), asc=20) for i in range(10)]
    assert generate_prophecy("Ironclad", 0, runs)["available"] is False


def test_prophecy_win_probability_is_the_empirical_rate():
    runs = [_run(str(i), win=i < 3) for i in range(10)]
    prophecy = generate_prophecy("Ironclad", 5, runs)
    assert prophecy["available"] is True
    assert prophecy["win_probability"] == 30.0
    assert prophecy["sample_size"] == 10


def test_prophecy_reports_the_average_floor_reached():
    runs = [_run(str(f), floors=[_floor(f)]) for f in (10, 20, 30, 40, 50)]
    assert generate_prophecy("Ironclad", 5, runs)["avg_floor"] == 30.0


def test_prophecy_average_floor_survives_runs_with_no_floors():
    """max(..., 1) guards the divisor; without it this is a ZeroDivisionError
    on a history of runs that never recorded a floor."""
    runs = [_run(str(i), floors=[]) for i in range(5)]
    assert generate_prophecy("Ironclad", 5, runs)["avg_floor"] == 0.0


def test_danger_zone_needs_at_least_three_deaths():
    assert _find_danger_zone([10, 12]) is None


def test_danger_zone_bins_deaths_into_five_floor_ranges():
    zone = _find_danger_zone([16, 17, 18, 19, 3])
    assert zone["range"] == "15-19"
    assert zone["deaths"] == 4
    assert zone["percentage"] == 80


def test_prophecy_carries_the_danger_zone_through():
    runs = [_run(str(i), floors=[_floor(f)])
            for i, f in enumerate((6, 7, 8, 9, 30))]
    assert generate_prophecy("Ironclad", 5, runs)["danger_zone"]["range"] == "5-9"


@pytest.mark.parametrize("wins, losses, needle", [
    (5, 0, "winning consistently"),
    (0, 5, None),          # handled by the early/late split below
])
def test_recommendation_covers_the_all_wins_and_all_losses_cases(
        wins, losses, needle):
    runs = [_run(f"w{i}", win=True) for i in range(wins)]
    runs += [_run(f"l{i}", win=False) for i in range(losses)]
    rec = _generate_recommendation(runs, "Ironclad")
    if needle:
        assert needle in rec
    else:
        assert rec


def test_recommendation_for_repeated_early_deaths_talks_about_act_one():
    runs = [_run(str(i), floors=[_floor(8)]) for i in range(5)]
    assert "early survival" in _generate_recommendation(runs, "Ironclad")


def test_recommendation_for_repeated_late_deaths_talks_about_scaling():
    runs = [_run(str(i), floors=[_floor(35)]) for i in range(5)]
    assert "scaling cards" in _generate_recommendation(runs, "Ironclad")


def test_recommendation_calls_out_bloated_losing_decks():
    runs = [_run("w", win=True, deck=["CARD.X"] * 20)]
    runs += [_run(f"l{i}", deck=["CARD.X"] * 40) for i in range(4)]
    rec = _generate_recommendation(runs, "Ironclad")
    assert "more selective" in rec
    assert "20 cards vs 40" in rec


def test_recommendation_falls_through_to_generic_advice():
    runs = [_run("w", win=True, deck=["CARD.X"] * 20),
            _run("l", deck=["CARD.X"] * 21)]
    assert "Study your winning runs" in _generate_recommendation(runs, "Ironclad")


def test_grading_an_unavailable_prophecy_is_nothing():
    assert grade_prophecy({"available": False}, _run("a")) is None


def test_grading_reports_whether_the_run_beat_the_prediction():
    prophecy = {"available": True, "avg_floor": 20.0, "win_probability": 30.0}
    grade = grade_prophecy(prophecy, _run("a", floors=[_floor(35)]))
    assert grade["actual_floor"] == 35
    assert grade["beat_prediction"] is True
    assert grade["beat_odds"] is False          # it was a loss


def test_grading_flags_a_win_against_the_odds():
    prophecy = {"available": True, "avg_floor": 20.0, "win_probability": 12.5}
    grade = grade_prophecy(prophecy, _run("a", win=True, floors=[_floor(50)]))
    assert grade["actual_win"] is True
    assert grade["beat_odds"] is True


def test_a_likely_win_that_lands_is_not_beating_the_odds():
    prophecy = {"available": True, "avg_floor": 20.0, "win_probability": 80.0}
    assert grade_prophecy(prophecy, _run("a", win=True))["beat_odds"] is False


def test_grading_a_run_with_no_floors_reads_floor_zero():
    prophecy = {"available": True, "avg_floor": 20.0, "win_probability": 30.0}
    assert grade_prophecy(prophecy, _run("a", floors=[]))["actual_floor"] == 0


# -------------------------------------------------------------------- rivalry

class _StubKB:
    @staticmethod
    def id_to_name(cid):
        return {"CARD.A": "Anger", "CARD.B": "Bash"}.get(cid, cid)


def test_runs_on_different_seeds_cannot_be_compared():
    result = compare_seed_runs(_run("a", seed="AAA"), _run("b", seed="BBB"))
    assert "Seeds don't match" in result["error"]


def test_rivalry_reports_a_differing_card_pick_by_name():
    a = _run("a", floors=[_floor(1, pick="CARD.A")])
    b = _run("b", floors=[_floor(1, pick="CARD.B")])
    picks = compare_seed_runs(a, b, _StubKB())["card_diffs"]
    assert picks == [{"floor": 1, "type": "card_pick",
                      "yours": "Anger", "rival": "Bash"}]


def test_rivalry_falls_back_to_card_ids_without_a_knowledge_base():
    a = _run("a", floors=[_floor(1, pick="CARD.A")])
    b = _run("b", floors=[_floor(1, pick="CARD.B")])
    assert compare_seed_runs(a, b)["card_diffs"][0]["yours"] == "CARD.A"


def test_rivalry_ignores_a_floor_where_only_one_player_picked():
    a = _run("a", floors=[_floor(1, hp=70, pick="CARD.A")])
    b = _run("b", floors=[_floor(1, hp=70, pick="")])
    assert compare_seed_runs(a, b)["card_diffs"] == []


def test_rivalry_ignores_the_same_pick_on_both_sides():
    a = _run("a", floors=[_floor(1, pick="CARD.A")])
    b = _run("b", floors=[_floor(1, pick="CARD.A")])
    assert compare_seed_runs(a, b)["card_diffs"] == []


def test_rivalry_reports_an_hp_gap_with_its_direction():
    a = _run("a", floors=[_floor(1, hp=70)])
    b = _run("b", floors=[_floor(1, hp=45)])
    hp = [d for d in compare_seed_runs(a, b)["diffs"] if d["type"] == "hp"]
    assert hp == [{"floor": 1, "type": "hp", "yours": 70, "rival": 45, "delta": 25}]


def test_rivalry_skips_floors_the_rival_never_reached():
    a = _run("a", floors=[_floor(1, hp=70), _floor(2, hp=60)])
    b = _run("b", floors=[_floor(1, hp=50)])
    assert {d["floor"] for d in compare_seed_runs(a, b)["diffs"]} == {1}


def test_rivalry_summarises_both_results():
    a = _run("a", win=True, floors=[_floor(50, hp=30)])
    b = _run("b", win=False, floors=[_floor(22, hp=0)])
    result = compare_seed_runs(a, b)
    assert result["seed"] == "SEED1"
    assert result["your_result"] == "win"
    assert result["rival_result"] == "died floor 22"
    assert result["your_floor"] == 50 and result["rival_floor"] == 22


def test_rivalry_handles_runs_with_no_floors():
    a = _run("a", floors=[])
    b = _run("b", floors=[])
    result = compare_seed_runs(a, b)
    assert result["your_floor"] == 0 and result["rival_floor"] == 0
    assert result["diffs"] == []


# --------------------------------------------------- durability on POSIX

def test_directory_fsync_is_skipped_on_windows(monkeypatch):
    """os.open on a directory raises on Windows, so the whole call is a no-op
    there; attempting it would turn a successful write into a reported failure.
    """
    from sts2 import persist
    monkeypatch.setattr(persist.os, "name", "nt")
    calls = []
    monkeypatch.setattr(persist.os, "open", lambda *a, **k: calls.append(a))
    persist._fsync_dir_target = None
    persist._fsync_dir(os.getcwd())
    assert calls == []


def test_directory_fsync_commits_the_rename_on_posix(monkeypatch, tmp_path):
    """The rename is only durably committed once the *directory* is synced.
    This leg never runs on the maintainer's machine, so it is only ever
    exercised here."""
    from sts2 import persist
    monkeypatch.setattr(persist.os, "name", "posix")
    opened, synced, closed = [], [], []
    monkeypatch.setattr(persist.os, "open", lambda p, f: opened.append(p) or 42)
    monkeypatch.setattr(persist.os, "fsync", synced.append)
    monkeypatch.setattr(persist.os, "close", closed.append)
    persist._fsync_dir(tmp_path)
    assert opened == [str(tmp_path)]
    assert synced == [42] and closed == [42]


def test_a_failed_directory_fsync_never_fails_the_write(monkeypatch, tmp_path):
    from sts2 import persist
    monkeypatch.setattr(persist.os, "name", "posix")

    def boom(*_a, **_kw):
        raise OSError("not a directory")

    monkeypatch.setattr(persist.os, "open", boom)
    persist._fsync_dir(tmp_path)          # must not raise


def test_the_descriptor_is_closed_even_when_the_sync_fails(monkeypatch, tmp_path):
    from sts2 import persist
    monkeypatch.setattr(persist.os, "name", "posix")
    closed = []
    monkeypatch.setattr(persist.os, "open", lambda _p, _f: 7)
    monkeypatch.setattr(persist.os, "close", closed.append)

    def boom(_fd):
        raise OSError("sync failed")

    monkeypatch.setattr(persist.os, "fsync", boom)
    persist._fsync_dir(tmp_path)
    assert closed == [7], "a leaked descriptor on every failed sync"
