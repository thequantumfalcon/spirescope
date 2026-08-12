"""Hypothesis Lab: pure evaluation, real Beta-Binomial, read-only GET.

The GET handler used to reset every hypothesis and then rewrite the whole
hypotheses JSON file once per run x hypothesis (~10,001 writes for one page
view at 1,000 runs and 10 hypotheses), and the "posterior" was
0.5 + effect/2 with no prior, likelihood, or uncertainty anywhere.
"""
import math
from unittest.mock import AsyncMock, patch

from sts2.hypothesis import (
    _prob_first_beats_second,
    evaluate_hypotheses,
    register_hypothesis,
)
from sts2.models import RunFloor, RunHistory


def _run(win: bool, character="Ironclad", deck_size=10, elites=0) -> RunHistory:
    floors = [RunFloor(floor=i + 1, type="elite") for i in range(elites)]
    return RunHistory(id=f"r-{win}-{character}-{deck_size}-{elites}-{id(floors)}",
                      character=character, win=win,
                      deck=["CARD.STRIKE"] * deck_size, floors=floors)


def _hyp(condition_type="character", params=None) -> dict:
    return {"text": "t", "condition_type": condition_type,
            "params": params or {"character": "Ironclad"},
            "runs_tested": 0, "runs_matching": 0, "runs_not_matching": 0,
            "wins_matching": 0, "wins_not_matching": 0,
            "verdict": "insufficient_data"}


class TestExactPosteriorProbability:
    """RULE: validate the instrument against independently known answers."""

    def test_analytic_case_beta21_vs_beta12(self):
        # P(X > Y), X~Beta(2,1), Y~Beta(1,2) integrates to exactly 5/6.
        assert math.isclose(_prob_first_beats_second(2, 1, 1, 2), 5 / 6,
                            rel_tol=1e-12)

    def test_symmetric_case_is_half(self):
        assert math.isclose(_prob_first_beats_second(1, 1, 1, 1), 0.5,
                            rel_tol=1e-12)
        assert math.isclose(_prob_first_beats_second(5, 5, 5, 5), 0.5,
                            rel_tol=1e-9)

    def test_matches_monte_carlo(self):
        import random
        rng = random.Random(42)
        a1, b1, a2, b2 = 8, 4, 3, 9
        samples = 200_000
        hits = sum(rng.betavariate(a1, b1) > rng.betavariate(a2, b2)
                   for _ in range(samples))
        assert abs(_prob_first_beats_second(a1, b1, a2, b2)
                   - hits / samples) < 0.01

    def test_large_counts_stay_finite(self):
        p = _prob_first_beats_second(600, 400, 450, 550)
        assert 0.99 <= p <= 1.0


class TestEvaluateHypotheses:
    def test_counters_and_strong_effect(self):
        hyps = {"h1": _hyp()}
        runs = ([_run(True)] * 9 + [_run(False)]          # Ironclad: 9/10
                + [_run(True, character="Silent")]         # others: 1/10
                + [_run(False, character="Silent")] * 9)
        evaluate_hypotheses(hyps, runs)
        h = hyps["h1"]
        assert h["runs_tested"] == 20
        assert h["runs_matching"] == 10 and h["wins_matching"] == 9
        assert h["runs_not_matching"] == 10 and h["wins_not_matching"] == 1
        assert h["verdict"] == "supported"
        assert h["prob_effect"] > 0.95
        assert h["effect_size"] > 0.5

    def test_no_signal_is_inconclusive(self):
        hyps = {"h1": _hyp()}
        runs = ([_run(True), _run(False)] * 3
                + [_run(True, character="Silent"), _run(False, character="Silent")] * 3)
        evaluate_hypotheses(hyps, runs)
        assert hyps["h1"]["verdict"] == "inconclusive"

    def test_insufficient_arm_stays_undecided(self):
        hyps = {"h1": _hyp()}
        evaluate_hypotheses(hyps, [_run(True)] * 5)  # zero non-matching runs
        assert hyps["h1"]["verdict"] == "insufficient_data"
        assert "prob_effect" not in hyps["h1"]

    def test_reevaluation_is_idempotent(self):
        hyps = {"h1": _hyp()}
        runs = [_run(True)] * 4 + [_run(False, character="Silent")] * 4
        evaluate_hypotheses(hyps, runs)
        first = dict(hyps["h1"])
        evaluate_hypotheses(hyps, runs)
        assert hyps["h1"] == first

    def test_stale_prior_field_is_dropped(self):
        h = _hyp()
        h["prior"] = 0.5  # written by the old pseudo-posterior
        hyps = {"h1": h}
        evaluate_hypotheses(hyps, [])
        assert "prior" not in hyps["h1"]

    def test_register_does_not_write_a_prior(self, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        hyp = register_hypothesis("abc123", "text", "elite_skip", {})
        assert "prior" not in hyp


class TestHypothesisPage:
    async def test_get_is_read_only(self, client, tmp_path, monkeypatch):
        """One GET must perform zero writes to the hypotheses file."""
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        register_hypothesis("h1", "elite skipping wins", "elite_skip", {})
        path = tmp_path / "hypotheses.json"
        before = path.read_text(encoding="utf-8")
        before_mtime = path.stat().st_mtime_ns

        writes = []
        from sts2 import persist
        real = persist.write_text_atomic
        monkeypatch.setattr(persist, "write_text_atomic",
                            lambda *a, **k: writes.append(a) or real(*a, **k))

        runs = [_run(True, elites=0)] * 4 + [_run(False, elites=2)] * 4
        with patch("sts2.app._get_runs", new=AsyncMock(return_value=runs)):
            resp = await client.get("/hypothesis")
        assert resp.status_code == 200
        assert writes == []
        assert path.read_text(encoding="utf-8") == before
        assert path.stat().st_mtime_ns == before_mtime

    async def test_page_renders_posterior_stats(self, client, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        register_hypothesis("h1", "Ironclad is my best", "character",
                            {"character": "Ironclad"})
        runs = ([_run(True)] * 9 + [_run(False)]
                + [_run(False, character="Silent")] * 9
                + [_run(True, character="Silent")])
        with patch("sts2.app._get_runs", new=AsyncMock(return_value=runs)):
            resp = await client.get("/hypothesis")
        assert resp.status_code == 200
        assert "P(better)" in resp.text
        assert "supported" in resp.text

    async def test_delete_form_asks_for_confirmation(self, client, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        register_hypothesis("h1", "t", "elite_skip", {})
        with patch("sts2.app._get_runs", new=AsyncMock(return_value=[])):
            resp = await client.get("/hypothesis")
        assert 'class="mt-sm js-confirm"' in resp.text
        assert "data-confirm=" in resp.text
