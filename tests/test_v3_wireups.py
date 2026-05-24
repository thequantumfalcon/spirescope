"""Smoke tests for v3 wired analytics modules.

Each test confirms a previously untested module is invoked by the route layer
and that the page renders without crashing on empty or minimal data.
Modules covered:
  - sts2.integrity        (Merkle hash on /runs/{id})
  - sts2.rivalry          (Seed-Match Diff on /runs/compare)
  - sts2.cascade          (Cascade Map on /runs/{id})
  - sts2.drift            (Archetype Drift on /runs/{id})
  - sts2.spectral         (Deck Health Score on POST /deck/analyze)
  - sts2.prophecy         (GET /prophecy)
  - sts2.behavior         (tilt + anti-patterns on /analytics)
  - sts2.hypothesis       (GET / POST /hypothesis CRUD)
"""
import json
from unittest.mock import AsyncMock, patch

from sts2.app import generate_csrf_token
from sts2.models import RunFloor, RunHistory


# ---------------------------------------------------------------------------
# sts2.integrity — Merkle hash on run detail
# ---------------------------------------------------------------------------

async def test_integrity_hash_rendered_on_run_detail(client):
    """A SHA-256 Merkle hash section must appear when a run exists."""
    run = RunHistory(
        id="integrity-run", character="Ironclad", win=True, ascension=5,
        seed="SEED-ABC", deck=["CARD.BASH"],
        floors=[RunFloor(floor=1, type="monster", current_hp=70, max_hp=80,
                         damage_taken=10, gold=25)],
    )
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)), \
         patch("sts2.app._get_runs", new=AsyncMock(return_value=[run])):
        resp = await client.get("/runs/integrity-run")
    assert resp.status_code == 200
    assert "Run Integrity" in resp.text
    assert "run-integrity-hash" in resp.text
    # Real SHA-256 hex digest is 64 chars; the route should embed one.
    from sts2.integrity import compute_merkle_root
    assert compute_merkle_root(run) in resp.text


# ---------------------------------------------------------------------------
# sts2.rivalry — Seed-Match Diff on compare page
# ---------------------------------------------------------------------------

async def test_rivalry_seed_match_diff_when_seeds_match(client):
    """Two runs with the same seed should surface the Seed-Match Diff section."""
    run_a = RunHistory(id="rival-a", character="Ironclad", win=True,
                       seed="SEED-XYZ", deck=["CARD.BASH"],
                       floors=[RunFloor(floor=1, current_hp=70, max_hp=80,
                                        card_picked="CARD.BASH")])
    run_b = RunHistory(id="rival-b", character="Ironclad", win=False,
                       seed="SEED-XYZ", deck=["CARD.STRIKE"],
                       floors=[RunFloor(floor=1, current_hp=50, max_hp=80,
                                        card_picked="CARD.STRIKE")])

    async def fake_get(rid):
        return run_a if rid == "rival-a" else run_b

    with patch("sts2.app._get_run_by_id", new=AsyncMock(side_effect=fake_get)):
        resp = await client.get("/runs/compare?a=rival-a&b=rival-b")
    assert resp.status_code == 200
    assert "Seed-Match Diff" in resp.text
    assert "SEED-XYZ" in resp.text


# ---------------------------------------------------------------------------
# sts2.cascade — Cascade Map on run detail
# ---------------------------------------------------------------------------

async def test_cascade_section_renders_without_error(client):
    """Run detail must render successfully even when cascade is empty."""
    run = RunHistory(
        id="cascade-run", character="Ironclad", win=True,
        deck=["CARD.BASH"],
        floors=[
            RunFloor(floor=1, type="monster", current_hp=70, max_hp=80,
                     damage_taken=10, turns=3),
            RunFloor(floor=2, type="monster", current_hp=60, max_hp=80,
                     damage_taken=10, turns=2, card_picked="CARD.BASH"),
            RunFloor(floor=3, type="monster", current_hp=55, max_hp=80,
                     damage_taken=5, turns=2),
        ],
    )
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)), \
         patch("sts2.app._get_runs", new=AsyncMock(return_value=[run])), \
         patch("sts2.cascade.trace_all_picks") as mock_trace:
        mock_trace.return_value = []
        resp = await client.get("/runs/cascade-run")
    assert resp.status_code == 200
    # Module must have been invoked by the route.
    assert mock_trace.called


# ---------------------------------------------------------------------------
# sts2.drift — Archetype Drift on run detail
# ---------------------------------------------------------------------------

async def test_drift_module_invoked_on_run_detail(client):
    """compute_archetype_drift must be invoked when rendering a run."""
    run = RunHistory(
        id="drift-run", character="Ironclad", win=False,
        deck=["CARD.BASH"],
        floors=[RunFloor(floor=1, current_hp=50, max_hp=80, damage_taken=30)],
    )
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)), \
         patch("sts2.app._get_runs", new=AsyncMock(return_value=[run])), \
         patch("sts2.drift.compute_archetype_drift") as mock_drift, \
         patch("sts2.drift.detect_drift_alert", return_value=None):
        mock_drift.return_value = []
        resp = await client.get("/runs/drift-run")
    assert resp.status_code == 200
    assert mock_drift.called


# ---------------------------------------------------------------------------
# sts2.spectral — Deck Health Score on POST /deck/analyze
# ---------------------------------------------------------------------------

async def test_spectral_deck_health_rendered(client):
    """POST /deck/analyze with cards must surface the Deck Health Score section."""
    resp = await client.post("/deck/analyze", data={
        "csrf_token": generate_csrf_token(),
        "card_ids": ["CARD.BASH", "CARD.AGGRESSION", "CARD.ANGER"],
    })
    assert resp.status_code == 200
    # Section header lives in the template behind {% if spectral_health %}.
    # The route always supplies a dict from sts2.spectral, so the section
    # should render even for a tiny deck (deck_spectral_health returns a stub
    # health_score for n<3 but the dict itself is truthy).
    assert "Deck Health Score" in resp.text


# ---------------------------------------------------------------------------
# sts2.prophecy — GET /prophecy
# ---------------------------------------------------------------------------

async def test_prophecy_route_with_and_without_character(client):
    """GET /prophecy?character=Ironclad invokes the module; empty character has no panel."""
    # Empty character — page renders, no result panel shown.
    resp_empty = await client.get("/prophecy")
    assert resp_empty.status_code == 200
    assert "Prophecy Engine" in resp_empty.text
    assert "Win Probability" not in resp_empty.text
    assert "Danger Zone" not in resp_empty.text

    # With character — module is invoked and its result rendered.
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=[])), \
         patch("sts2.prophecy.generate_prophecy") as mock_gen:
        mock_gen.return_value = {"available": False, "reason": "Need more runs"}
        resp_char = await client.get("/prophecy?character=Ironclad&ascension=0")
    assert resp_char.status_code == 200
    assert mock_gen.called
    assert "Need more runs" in resp_char.text


# ---------------------------------------------------------------------------
# sts2.behavior — tilt + anti-pattern detection on /analytics
# ---------------------------------------------------------------------------

async def test_behavior_invoked_on_analytics_empty_runs(client):
    """/analytics must succeed and call behavior helpers on empty run history."""
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=[])), \
         patch("sts2.app._get_progress", new=AsyncMock(return_value=None)), \
         patch("sts2.app._analytics_cache", {}), \
         patch("sts2.app._analytics_cache_time", {}), \
         patch("sts2.behavior.detect_tilt") as mock_tilt, \
         patch("sts2.behavior.detect_anti_patterns") as mock_anti:
        mock_tilt.return_value = {"tilting": False, "momentum": 0, "message": ""}
        mock_anti.return_value = []
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert mock_tilt.called
    assert mock_anti.called


# ---------------------------------------------------------------------------
# sts2.hypothesis — CRUD against /hypothesis routes
# ---------------------------------------------------------------------------

async def test_hypothesis_crud(client, tmp_path):
    """GET /hypothesis renders; POST create registers; POST delete removes."""
    hyp_file = tmp_path / "hypotheses.json"
    with patch("sts2.hypothesis.HYPOTHESES_FILE", hyp_file), \
         patch("sts2.app._get_runs", new=AsyncMock(return_value=[])):
        # GET — list page renders.
        resp = await client.get("/hypothesis")
        assert resp.status_code == 200
        assert "Hypothesis Lab" in resp.text
        assert "Register New Hypothesis" in resp.text

        # POST /create — registers a hypothesis on disk.
        resp = await client.post("/hypothesis/create", data={
            "csrf_token": generate_csrf_token(),
            "text": "Skipping elites helps me win",
            "condition_type": "elite_skip",
            "param_value": "",
        }, follow_redirects=False)
        assert resp.status_code == 303
        assert hyp_file.exists()
        stored = json.loads(hyp_file.read_text(encoding="utf-8"))
        assert len(stored) == 1
        hyp_id = next(iter(stored))
        assert stored[hyp_id]["condition_type"] == "elite_skip"

        # POST /delete — removes the stored hypothesis.
        resp = await client.post(f"/hypothesis/delete/{hyp_id}", data={
            "csrf_token": generate_csrf_token(),
        }, follow_redirects=False)
        assert resp.status_code == 303
        stored_after = json.loads(hyp_file.read_text(encoding="utf-8"))
        assert hyp_id not in stored_after
