"""Regression tests for the M18-M23 analytics-truth audit fixes.

Covers: graveyard newest-50 selection/order, spectral health score range +
integer edge count + Jacobi convergence, cascade acquisition-floor exclusion
+ minimum-sample skip + duplicate-pick rows + hp_delta, drift alert minimum
trajectory length, home-page prophecy/tilt wiring, and run-detail prophecy
grading.
"""
from unittest.mock import AsyncMock, patch

import pytest

from sts2.cascade import trace_all_picks, trace_card_impact
from sts2.drift import detect_drift_alert
from sts2.models import RunFloor, RunHistory
from sts2.spectral import _compute_components, deck_spectral_health

# ---------------------------------------------------------------------------
# Fake card / knowledge-base helpers for spectral tests — full control over
# keyword overlap without depending on the shape of shipped card data.
# ---------------------------------------------------------------------------

class _FakeCard:
    def __init__(self, id, name, keywords, type_="Skill", cost="1"):
        self.id = id
        self.name = name
        self.keywords = keywords
        self.type = type_
        self.cost = cost


class _FakeKB:
    def __init__(self, cards):
        self._by_id = {c.id: c for c in cards}

    def get_card_by_id(self, cid):
        return self._by_id.get(cid)


# ---------------------------------------------------------------------------
# M22 — Graveyard: newest-50 selection, newest-first display
# ---------------------------------------------------------------------------

async def test_graveyard_shows_newest_50_deaths_newest_first(client):
    """With 60 losses (newest-first, matching _get_runs' real order), the
    page must show the newest death and must not show the 51st-oldest one
    that [-50:] on a newest-first list used to keep instead."""
    runs = [
        RunHistory(id=f"loss-{i}", character="Ironclad", win=False,
                   floors=[RunFloor(floor=5, type="boss")])
        for i in range(60)
    ]  # index 0 = newest
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=runs)):
        resp = await client.get("/graveyard")
    assert resp.status_code == 200
    assert "/runs/loss-0" in resp.text
    assert "/runs/loss-49" in resp.text
    # These were the ones the old [-50:] slice kept and the new [:50] drops.
    assert "/runs/loss-50" not in resp.text
    assert "/runs/loss-59" not in resp.text
    # Display order is newest-first.
    assert resp.text.index("/runs/loss-0") < resp.text.index("/runs/loss-1")


# ---------------------------------------------------------------------------
# M19 — Spectral: 0-100 range, integer edge count, Jacobi convergence
# ---------------------------------------------------------------------------

def test_spectral_health_reaches_100_for_an_ideal_fully_connected_deck():
    """An ideal deck (no orphans, max density, fully connected) must reach
    the promised 100 — previously capped at 90 by halving the connectivity
    component after already capping it at 20."""
    cards = [_FakeCard(f"CARD.X{i}", f"Card{i}", ["Block", "Strength"]) for i in range(6)]
    kb = _FakeKB(cards)
    result = deck_spectral_health([c.id for c in cards], kb)
    assert result["health_score"] == 100
    assert result["orphans"] == []


def test_spectral_total_edges_is_an_integer_count_not_weighted_mass():
    """Two decks with the same complete-graph topology (every pair
    connected) must report the same edge count whether each pair shares 1
    keyword or 3 — the old weighted sum reported 6 vs 18 for these."""
    weak = [_FakeCard(f"CARD.W{i}", f"W{i}", ["Block"]) for i in range(4)]
    strong = [_FakeCard(f"CARD.S{i}", f"S{i}", ["Block", "Strength", "Dexterity"])
              for i in range(4)]
    weak_result = deck_spectral_health([c.id for c in weak], _FakeKB(weak))
    strong_result = deck_spectral_health([c.id for c in strong], _FakeKB(strong))
    assert weak_result["total_edges"] == 6  # C(4,2)
    assert strong_result["total_edges"] == 6
    assert isinstance(weak_result["total_edges"], int)
    assert weak_result["avg_degree"] == strong_result["avg_degree"] == 3.0


def test_compute_components_converges_on_p3_path_graph():
    """P3 (a 3-node path, 0-1-2) has an analytically known Laplacian
    spectrum of 0, 1, 3 — a direct check that the Jacobi rotation routine
    actually converges to the right answer, not just that it halts."""
    laplacian = [[1, -1, 0], [-1, 2, -1], [0, -1, 1]]
    result = sorted(_compute_components(laplacian, max_iter=1000))
    assert result[0] == pytest.approx(0, abs=1e-6)
    assert result[1] == pytest.approx(1, abs=1e-6)
    assert result[2] == pytest.approx(3, abs=1e-6)


def test_spectral_connectivity_converges_on_a_larger_graph():
    """Regression for the audited failure: a fixed 100-rotation budget left
    a 30-node graph's connectivity at 0.129 vs a true value of 0.011 (a
    sparser graph); here a 30-node *complete* unit-weight graph has a known
    algebraic connectivity of exactly 30 (Laplacian eigenvalues 0 and n),
    which the scaled iteration budget must actually reach."""
    cards = [_FakeCard(f"CARD.N{i}", f"N{i}", ["Block"]) for i in range(30)]
    result = deck_spectral_health([c.id for c in cards], _FakeKB(cards))
    assert result["connectivity"] == pytest.approx(30, abs=0.5)


# ---------------------------------------------------------------------------
# M18 — Cascade: acquisition-floor exclusion, min-sample skip, duplicate
# picks each get their own row, hp_delta is present
# ---------------------------------------------------------------------------

def test_cascade_excludes_the_acquisition_floor_from_the_post_window():
    floors = [
        RunFloor(floor=1, type="monster", turns=2, damage_taken=10, current_hp=70, max_hp=80),
        RunFloor(floor=2, type="monster", turns=2, damage_taken=10, current_hp=60, max_hp=80),
        RunFloor(floor=3, type="monster", turns=1, damage_taken=50, current_hp=10, max_hp=80,
                 card_picked="CARD.BASH"),
        RunFloor(floor=4, type="monster", turns=2, damage_taken=5, current_hp=70, max_hp=80),
        RunFloor(floor=5, type="monster", turns=2, damage_taken=5, current_hp=75, max_hp=80),
    ]
    run = RunHistory(id="r1", character="Ironclad", win=True, floors=floors)
    result = trace_card_impact(run, "CARD.BASH", kb=None)
    assert "error" not in result
    # If the acquisition floor (3, dmg=50) leaked into "post" it would drag
    # post_avg_damage up to 20.0 instead of 5.0.
    assert result["post_avg_damage"] == 5.0
    assert result["floors_survived_after"] == 2  # floors 4, 5 only — not 3
    assert result["hp_delta"] == 7.5  # post avg hp 72.5 - pre avg hp 65.0


def test_cascade_skips_when_either_window_has_fewer_than_2_combats():
    """No combats before the pick used to compare post-pick damage against
    a zero baseline; now it's skipped entirely rather than faking a verdict."""
    floors = [
        RunFloor(floor=1, type="monster", turns=2, damage_taken=10, current_hp=70, max_hp=80,
                 card_picked="CARD.BASH"),
        RunFloor(floor=2, type="monster", turns=2, damage_taken=5, current_hp=65, max_hp=80),
    ]
    run = RunHistory(id="r2", character="Ironclad", win=True, floors=floors)
    result = trace_card_impact(run, "CARD.BASH", kb=None)
    assert "error" in result
    # trace_all_picks must not surface a fabricated row for it either.
    assert trace_all_picks(run, kb=None) == []


def test_cascade_gives_each_duplicate_pick_its_own_row():
    floors = [
        RunFloor(floor=1, type="monster", turns=2, damage_taken=10, current_hp=70, max_hp=80),
        RunFloor(floor=2, type="monster", turns=2, damage_taken=10, current_hp=60, max_hp=80),
        RunFloor(floor=3, type="monster", turns=2, damage_taken=8, current_hp=55, max_hp=80,
                 card_picked="CARD.STRIKE"),
        RunFloor(floor=4, type="monster", turns=2, damage_taken=6, current_hp=50, max_hp=80),
        RunFloor(floor=5, type="monster", turns=2, damage_taken=6, current_hp=48, max_hp=80),
        RunFloor(floor=6, type="monster", turns=2, damage_taken=4, current_hp=60, max_hp=80,
                 card_picked="CARD.STRIKE"),
        RunFloor(floor=7, type="monster", turns=2, damage_taken=4, current_hp=62, max_hp=80),
        RunFloor(floor=8, type="monster", turns=2, damage_taken=4, current_hp=65, max_hp=80),
    ]
    run = RunHistory(id="r3", character="Ironclad", win=True, floors=floors)
    results = trace_all_picks(run, kb=None)
    picked_floors = sorted(r["picked_floor"] for r in results if r["card_id"] == "CARD.STRIKE")
    assert picked_floors == [3, 6]


# ---------------------------------------------------------------------------
# M20 — Drift: alert minimum trajectory length
# ---------------------------------------------------------------------------

def test_drift_alert_does_not_fire_below_minimum_trajectory_length():
    trajectory = [{"archetype": "Alpha"}, {"archetype": "Alpha"}, {"archetype": "Beta"}]
    assert detect_drift_alert(trajectory) is None


def test_drift_alert_fires_at_minimum_trajectory_length_with_a_real_shift():
    trajectory = [{"archetype": a} for a in ["Alpha", "Alpha", "Alpha", "Beta", "Beta", "Beta"]]
    alert = detect_drift_alert(trajectory)
    assert alert is not None
    assert "Alpha" in alert and "Beta" in alert


# ---------------------------------------------------------------------------
# M21 — Home-page prophecy card + tilt warning; run-detail prophecy grade
# ---------------------------------------------------------------------------

async def test_index_shows_prophecy_card_and_tilt_warning(client):
    run = RunHistory(id="latest", character="Ironclad", win=False, ascension=5,
                     floors=[RunFloor(floor=10, type="monster", current_hp=0, max_hp=80)])
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=[run])), \
         patch("sts2.prophecy.generate_prophecy") as mock_prophecy, \
         patch("sts2.behavior.detect_tilt") as mock_tilt:
        mock_prophecy.return_value = {
            "available": True, "character": "Ironclad", "ascension": 5,
            "win_probability": 42.0, "sample_size": 8,
        }
        mock_tilt.return_value = {
            "tilting": True, "momentum": -60,
            "message": "Your last 3 runs averaged floor 4. Consider taking a break.",
        }
        resp = await client.get("/")
    assert resp.status_code == 200
    assert mock_prophecy.called
    assert mock_tilt.called
    assert "42.0%" in resp.text
    assert "Tilt warning" in resp.text
    assert "Consider taking a break" in resp.text


async def test_index_hides_prophecy_and_tilt_when_no_run_history(client):
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=[])):
        resp = await client.get("/")
    assert resp.status_code == 200
    assert "Tilt warning" not in resp.text


async def test_run_detail_shows_prophecy_grade(client):
    run = RunHistory(id="graded-run", character="Ironclad", win=True, ascension=5,
                     timestamp=5000,
                     floors=[RunFloor(floor=20, type="boss", current_hp=30, max_hp=80)])
    # A grade needs history that predates the run — a prophecy computed from
    # the run itself (or from later runs) is not a prediction.
    earlier = RunHistory(id="earlier", character="Ironclad", win=False,
                         ascension=5, timestamp=1000)
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)), \
         patch("sts2.app._get_runs", new=AsyncMock(return_value=[run, earlier])), \
         patch("sts2.prophecy.generate_prophecy") as mock_gen, \
         patch("sts2.prophecy.grade_prophecy") as mock_grade:
        mock_gen.return_value = {"available": True, "win_probability": 30.0, "avg_floor": 15.0}
        mock_grade.return_value = {
            "predicted_avg_floor": 15.0, "actual_floor": 20, "beat_prediction": True,
            "predicted_win_prob": 30.0, "actual_win": True, "beat_odds": True,
        }
        resp = await client.get("/runs/graded-run")
    assert resp.status_code == 200
    assert mock_gen.called
    assert mock_grade.called
    assert "Prophecy said" in resp.text
    assert "30.0%" in resp.text


class TestProphecyUsesOnlyPriorRuns:
    """A graded prophecy must be the prediction that was available BEFORE the
    run, not one recomputed later from runs that had not happened yet.

    Excluding only the run itself left every LATER run in the comparison set,
    so the displayed historical prediction drifted as new runs accumulated.
    """

    @staticmethod
    def _run(rid, ts, win, character="Ironclad"):
        from sts2.models import RunHistory
        return RunHistory(id=rid, character=character, win=win, ascension=0,
                          timestamp=ts, deck=["CARD.STRIKE"])

    async def test_later_runs_do_not_change_an_earlier_grade(self, client):
        from unittest.mock import AsyncMock, patch

        graded = self._run("target", 5000, False)
        earlier = [self._run(f"e{i}", 1000 + i, i % 2 == 0) for i in range(8)]
        later = [self._run(f"L{i}", 9000 + i, True) for i in range(20)]

        async def render(history):
            with patch("sts2.app._get_run_by_id",
                       new=AsyncMock(return_value=graded)), \
                 patch("sts2.app._get_runs",
                       new=AsyncMock(return_value=history)):
                return (await client.get("/runs/target")).text

        without_future = await render(earlier + [graded])
        with_future = await render(earlier + [graded] + later)

        import re
        pat = re.compile(r"Prophecy said <strong>([\d.]+)%")
        a = pat.search(without_future)
        b = pat.search(with_future)
        assert a, "prophecy grade did not render for a run with prior history"
        assert a.group(1) == b.group(1), (
            "adding later runs changed an earlier run's displayed prophecy")

    async def test_no_grade_without_prior_history(self, client):
        from unittest.mock import AsyncMock, patch

        first = self._run("first", 1000, False)
        later = [self._run(f"L{i}", 9000 + i, True) for i in range(10)]
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=first)), \
             patch("sts2.app._get_runs", new=AsyncMock(return_value=[first] + later)):
            html = (await client.get("/runs/first")).text
        assert "Prophecy said" not in html
