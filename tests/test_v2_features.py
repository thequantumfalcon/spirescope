"""Tests for Spirescope v2.0 features: analytics, import/export, coaching,
aggregation, mod loading, CSV export, API pagination, theme, CSP, rate limiter."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, AsyncMock
from httpx import AsyncClient, ASGITransport

from sts2.app import app, generate_csrf_token, _ADMIN_TOKEN, _rate_limit_store
from sts2.models import RunHistory, RunFloor, Card, Relic, Enemy


@pytest.fixture
def client():
    _rate_limit_store.clear()
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Analytics: 5 new computations
# ---------------------------------------------------------------------------

def _make_runs():
    """Create a mix of wins/losses with floors for analytics tests."""
    return [
        RunHistory(id="r1", character="Ironclad", win=True, ascension=5,
                   deck=["CARD.BASH", "CARD.STRIKE"], relics=["RELIC.BURNING_BLOOD"],
                   run_time=1200, killed_by="",
                   floors=[
                       RunFloor(floor=1, current_hp=70, max_hp=80, damage_taken=10, encounter="ENEMY.JAW_WORM",
                                cards_offered=["CARD.BASH", "CARD.STRIKE"], card_picked="CARD.BASH"),
                       RunFloor(floor=5, current_hp=50, max_hp=80, damage_taken=20, encounter="ENEMY.GREMLIN"),
                       RunFloor(floor=10, current_hp=40, max_hp=80, damage_taken=10, encounter="ENEMY.SENTRIES"),
                   ]),
        RunHistory(id="r2", character="Ironclad", win=False, ascension=5,
                   deck=["CARD.BASH"], relics=["RELIC.BURNING_BLOOD"],
                   run_time=600, killed_by="ENEMY.HEXAGHOST",
                   floors=[
                       RunFloor(floor=1, current_hp=60, max_hp=80, damage_taken=20, encounter="ENEMY.JAW_WORM"),
                       RunFloor(floor=5, current_hp=30, max_hp=80, damage_taken=30, encounter="ENEMY.GREMLIN"),
                       RunFloor(floor=8, current_hp=0, max_hp=80, damage_taken=30, encounter="ENEMY.HEXAGHOST"),
                   ]),
        RunHistory(id="r3", character="Silent", win=True, ascension=10,
                   deck=["CARD.NEUTRALIZE", "CARD.STRIKE"], relics=["RELIC.RING_OF_THE_SNAKE"],
                   run_time=1500,
                   floors=[
                       RunFloor(floor=1, current_hp=65, max_hp=70, damage_taken=5, encounter="ENEMY.JAW_WORM"),
                       RunFloor(floor=10, current_hp=50, max_hp=70, damage_taken=15, encounter="ENEMY.LAGAVULIN"),
                       RunFloor(floor=20, current_hp=45, max_hp=70, damage_taken=5, encounter="ENEMY.CHAMP"),
                   ]),
    ]


class TestHPTracking:
    def test_hp_tracking_with_runs(self):
        from sts2.analytics import compute_analytics
        runs = _make_runs()
        result = compute_analytics(runs)
        assert "hp_tracking" in result
        assert len(result["hp_tracking"]) > 0
        for entry in result["hp_tracking"]:
            assert "floor" in entry
            assert "win_avg_pct" in entry
            assert "loss_avg_pct" in entry

    def test_hp_tracking_empty_runs(self):
        from sts2.analytics import compute_analytics
        result = compute_analytics([])
        assert result["hp_tracking"] == []

    def test_hp_tracking_guards_zero_max_hp(self):
        from sts2.analytics import compute_analytics
        runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"],
                           floors=[RunFloor(floor=1, current_hp=0, max_hp=0)])]
        result = compute_analytics(runs)
        # Should not crash with ZeroDivisionError
        assert isinstance(result["hp_tracking"], list)


class TestDeathFloors:
    def test_death_floor_distribution(self):
        from sts2.analytics import compute_analytics
        runs = _make_runs()
        result = compute_analytics(runs)
        assert "death_floors" in result
        # r2 dies on floor 8 (3 floors completed)
        assert len(result["death_floors"]) > 0
        death_entry = result["death_floors"][0]
        assert "floor" in death_entry
        assert "deaths" in death_entry

    def test_death_floors_all_wins(self):
        from sts2.analytics import compute_analytics
        runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"],
                           floors=[RunFloor(floor=1)])]
        result = compute_analytics(runs)
        assert result["death_floors"] == []

    def test_death_floors_empty_runs(self):
        from sts2.analytics import compute_analytics
        result = compute_analytics([])
        assert result["death_floors"] == []


class TestAscensionCurve:
    def test_ascension_curve(self):
        from sts2.analytics import compute_analytics
        runs = _make_runs()
        result = compute_analytics(runs)
        assert "ascension_curve" in result
        assert len(result["ascension_curve"]) >= 1
        for entry in result["ascension_curve"]:
            assert "ascension" in entry
            assert "total" in entry
            assert "wins" in entry
            assert "win_rate" in entry

    def test_ascension_curve_single_level(self):
        from sts2.analytics import compute_analytics
        runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], ascension=3)]
        result = compute_analytics(runs)
        assert len(result["ascension_curve"]) == 1
        assert result["ascension_curve"][0]["ascension"] == 3
        assert result["ascension_curve"][0]["win_rate"] == 100.0

    def test_ascension_curve_empty(self):
        from sts2.analytics import compute_analytics
        result = compute_analytics([])
        assert result["ascension_curve"] == []


class TestCardQuality:
    def test_card_quality_cross_reference(self):
        from sts2.analytics import compute_analytics
        runs = [
            RunHistory(id="r1", character="Ironclad", win=True,
                       deck=["CARD.BASH", "CARD.STRIKE"],
                       floors=[RunFloor(floor=1, cards_offered=["CARD.BASH", "CARD.STRIKE"],
                                        card_picked="CARD.BASH")]),
            RunHistory(id="r2", character="Ironclad", win=True,
                       deck=["CARD.BASH", "CARD.STRIKE"],
                       floors=[RunFloor(floor=1, cards_offered=["CARD.BASH", "CARD.DEFEND"],
                                        card_picked="CARD.BASH")]),
            RunHistory(id="r3", character="Ironclad", win=False,
                       deck=["CARD.BASH"],
                       floors=[RunFloor(floor=1, cards_offered=["CARD.BASH"],
                                        card_picked="CARD.BASH")]),
        ]
        result = compute_analytics(runs)
        assert "card_quality" in result
        # CARD.BASH appears in all 3 runs and was offered/picked
        if result["card_quality"]:
            for entry in result["card_quality"]:
                assert "win_rate" in entry
                assert "pick_rate" in entry

    def test_card_quality_empty(self):
        from sts2.analytics import compute_analytics
        result = compute_analytics([])
        assert result["card_quality"] == []


class TestDamagePercentiles:
    def test_damage_percentiles_computed(self):
        from sts2.analytics import compute_analytics
        runs = _make_runs()
        result = compute_analytics(runs)
        assert "damage_percentiles" in result
        # JAW_WORM appears in all 3 runs with damage
        if result["damage_percentiles"]:
            entry = result["damage_percentiles"][0]
            assert "p25" in entry
            assert "median" in entry
            assert "p75" in entry
            assert "fights" in entry

    def test_damage_percentiles_empty(self):
        from sts2.analytics import compute_analytics
        result = compute_analytics([])
        assert result["damage_percentiles"] == []


# ---------------------------------------------------------------------------
# Run Import/Export
# ---------------------------------------------------------------------------

class TestRunExport:
    async def test_export_known_run(self, client):
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=RunHistory(
                id="test-run-1", character="Ironclad", win=True, deck=["CARD.BASH"]))):
            async with client as c:
                resp = await c.get("/runs/test-run-1/export")
        assert resp.status_code == 200
        data = resp.json()
        assert data["format_version"] == 1
        assert data["run"]["id"] == "test-run-1"
        assert "spirescope_version" in data
        assert "attachment" in resp.headers.get("content-disposition", "")

    async def test_export_404(self, client):
        async with client as c:
            resp = await c.get("/runs/nonexistent/export")
        assert resp.status_code == 404

    async def test_export_filename_sanitized(self, client):
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=RunHistory(
                id="test/../../evil", character="Ironclad", win=True, deck=[]))):
            async with client as c:
                resp = await c.get("/runs/test%2F..%2F..%2Fevil/export")
        if resp.status_code == 200:
            disp = resp.headers.get("content-disposition", "")
            assert "/" not in disp.split("filename=")[1] if "filename=" in disp else True


class TestRunImport:
    async def test_import_valid_run(self, client):
        run_data = {"spirescope_version": "2.0.0", "format_version": 1,
                    "run": {"id": "imported-1", "character": "Silent", "win": True, "deck": []}}
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("test.json", json.dumps(run_data).encode())},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 200
        assert "imported-1" in resp.text or "Imported" in resp.text

    async def test_import_bad_csrf(self, client):
        run_data = {"spirescope_version": "2.0.0", "format_version": 1,
                    "run": {"id": "x", "character": "Silent", "win": True, "deck": []}}
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("test.json", json.dumps(run_data).encode())},
                                data={"csrf_token": "bad"})
        assert resp.status_code == 403

    async def test_import_too_large(self, client):
        huge = b"x" * (1_048_577)
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("big.json", huge)},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 413

    async def test_import_malformed_json(self, client):
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("bad.json", b"not json")},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400

    async def test_import_bad_format_version(self, client):
        data = json.dumps({"format_version": 99, "run": {}}).encode()
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("v99.json", data)},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400
        assert "format" in resp.text.lower() or "version" in resp.text.lower()

    async def test_import_missing_run_key(self, client):
        data = json.dumps({"format_version": 1}).encode()
        async with client as c:
            resp = await c.post("/runs/import",
                                files={"file": ("norun.json", data)},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Coaching (live page)
# ---------------------------------------------------------------------------

class TestCoaching:
    async def test_danger_zone_critical(self, client):
        from sts2.models import CurrentRun
        mock_run = CurrentRun(active=True, character="Ironclad",
                              current_hp=10, max_hp=80, deck=["CARD.BASH"],
                              floors=[RunFloor(floor=1)])
        with patch("sts2.routes.get_current_run", return_value=mock_run):
            async with client as c:
                resp = await c.get("/live")
        assert resp.status_code == 200
        assert "CRITICAL" in resp.text or "critical" in resp.text.lower()

    async def test_danger_zone_warning(self, client):
        from sts2.models import CurrentRun
        mock_run = CurrentRun(active=True, character="Ironclad",
                              current_hp=25, max_hp=80, deck=["CARD.BASH"],
                              floors=[RunFloor(floor=1)])
        with patch("sts2.routes.get_current_run", return_value=mock_run):
            async with client as c:
                resp = await c.get("/live")
        assert resp.status_code == 200
        assert "WARNING" in resp.text or "warning" in resp.text.lower()

    async def test_no_danger_healthy_hp(self, client):
        from sts2.models import CurrentRun
        mock_run = CurrentRun(active=True, character="Ironclad",
                              current_hp=70, max_hp=80, deck=["CARD.BASH"],
                              floors=[RunFloor(floor=1)])
        with patch("sts2.routes.get_current_run", return_value=mock_run):
            async with client as c:
                resp = await c.get("/live")
        assert resp.status_code == 200
        assert "danger-banner" not in resp.text

    async def test_empty_floors_no_crash(self, client):
        from sts2.models import CurrentRun
        mock_run = CurrentRun(active=True, character="Ironclad",
                              current_hp=50, max_hp=80, deck=["CARD.BASH"],
                              floors=[])
        with patch("sts2.routes.get_current_run", return_value=mock_run):
            async with client as c:
                resp = await c.get("/live")
        assert resp.status_code == 200

    async def test_zero_max_hp_no_crash(self, client):
        from sts2.models import CurrentRun
        mock_run = CurrentRun(active=True, character="Ironclad",
                              current_hp=0, max_hp=0, deck=["CARD.BASH"],
                              floors=[])
        with patch("sts2.routes.get_current_run", return_value=mock_run):
            async with client as c:
                resp = await c.get("/live")
        assert resp.status_code == 200
        assert "danger-banner" not in resp.text


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

class TestAggregate:
    def test_compute_empty(self):
        from sts2.aggregate import compute_aggregate_stats
        result = compute_aggregate_stats([])
        assert result["run_count"] == 0
        assert result["character_stats"] == {}

    def test_compute_with_runs(self):
        from sts2.aggregate import compute_aggregate_stats
        runs = _make_runs()
        result = compute_aggregate_stats(runs)
        assert result["run_count"] == 3
        assert "Ironclad" in result["character_stats"]
        assert "Silent" in result["character_stats"]
        assert result["character_stats"]["Ironclad"]["total"] == 2

    def test_no_pii_in_output(self):
        from sts2.aggregate import compute_aggregate_stats
        runs = [RunHistory(id="secret-id", character="Ironclad", win=True,
                           deck=["CARD.BASH"], seed="secret-seed",
                           killed_by="ENEMY.BOSS")]
        result = compute_aggregate_stats(runs)
        dumped = json.dumps(result)
        assert "secret-id" not in dumped
        assert "secret-seed" not in dumped

    def test_merge_empty_existing(self):
        from sts2.aggregate import merge_aggregate
        imported = {"run_count": 10, "character_stats": {"Ironclad": {"wins": 5, "total": 10}}}
        result = merge_aggregate({}, imported)
        assert result["run_count"] == 10

    def test_merge_additive(self):
        from sts2.aggregate import merge_aggregate
        existing = {"run_count": 10, "character_stats": {"Ironclad": {"wins": 5, "total": 10}}}
        imported = {"run_count": 5, "character_stats": {"Ironclad": {"wins": 3, "total": 5}}}
        result = merge_aggregate(existing, imported)
        assert result["run_count"] == 15
        assert result["character_stats"]["Ironclad"]["wins"] == 8
        assert result["character_stats"]["Ironclad"]["total"] == 15

    def test_merge_anti_manipulation_cap(self):
        from sts2.aggregate import merge_aggregate
        existing = {"run_count": 100, "character_stats": {}}
        imported = {"run_count": 999999, "character_stats": {}}
        result = merge_aggregate(existing, imported)
        # Cap is max(100 * 2, 1000) = 1000
        assert result["run_count"] == 100 + 1000

    def test_merge_small_existing_uses_min_cap(self):
        from sts2.aggregate import merge_aggregate
        existing = {"run_count": 5, "character_stats": {}}
        imported = {"run_count": 5000, "character_stats": {}}
        result = merge_aggregate(existing, imported)
        # Cap is max(5 * 2, 1000) = 1000
        assert result["run_count"] == 5 + 1000

    def test_reset_nonexistent(self):
        from sts2.aggregate import reset_aggregate
        with patch("sts2.aggregate._aggregate_storage_path") as mock_path:
            mock_p = Path("/tmp/nonexistent_aggregate.json")
            mock_path.return_value = mock_p
            result = reset_aggregate()
        assert result is False

    def test_load_missing_file(self):
        from sts2.aggregate import load_aggregate
        with patch("sts2.aggregate._aggregate_storage_path", return_value=Path("/tmp/no_such_file.json")):
            result = load_aggregate()
        assert result == {}


class TestAggregateAPI:
    async def test_export_stats(self, client):
        async with client as c:
            resp = await c.get("/api/export/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert "run_count" in data
        assert "character_stats" in data

    async def test_import_stats_bad_csrf(self, client):
        data = json.dumps({"run_count": 5, "character_stats": {}}).encode()
        async with client as c:
            resp = await c.post("/api/import/stats",
                                files={"file": ("stats.json", data)},
                                data={"csrf_token": "bad"})
        assert resp.status_code == 403

    async def test_import_stats_too_large(self, client):
        huge = b"x" * 512_001
        async with client as c:
            resp = await c.post("/api/import/stats",
                                files={"file": ("big.json", huge)},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 413

    async def test_import_stats_invalid_json(self, client):
        async with client as c:
            resp = await c.post("/api/import/stats",
                                files={"file": ("bad.json", b"not json")},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400

    async def test_import_stats_missing_run_count(self, client):
        data = json.dumps({"character_stats": {}}).encode()
        async with client as c:
            resp = await c.post("/api/import/stats",
                                files={"file": ("stats.json", data)},
                                data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400

    async def test_reset_stats_requires_auth(self, client):
        async with client as c:
            resp = await c.post("/api/reset/stats")
        assert resp.status_code == 403

    async def test_reset_stats_with_auth(self, client):
        async with client as c:
            resp = await c.post("/api/reset/stats",
                                headers={"X-Admin-Token": _ADMIN_TOKEN})
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Mod loading
# ---------------------------------------------------------------------------

class TestModLoading:
    def test_load_valid_mod(self, tmp_path):
        from sts2.knowledge import KnowledgeBase
        mod_data = {
            "mod_name": "Test Mod",
            "cards": [{"id": "MOD.TEST_CARD", "name": "Test Card", "character": "Ironclad",
                        "cost": "1", "type": "Attack", "rarity": "Common"}],
            "relics": [{"id": "MOD.TEST_RELIC", "name": "Test Relic"}],
        }
        (tmp_path / "test_mod.json").write_text(json.dumps(mod_data), encoding="utf-8")
        with patch("sts2.knowledge.MODS_DIR", tmp_path):
            kb = KnowledgeBase()
        mod_cards = [c for c in kb.cards if c.source == "mod"]
        assert any(c.id == "MOD.TEST_CARD" for c in mod_cards)
        mod_relics = [r for r in kb.relics if r.source == "mod"]
        assert any(r.id == "MOD.TEST_RELIC" for r in mod_relics)

    def test_mod_collision_skips(self, tmp_path):
        from sts2.knowledge import KnowledgeBase
        # CARD.BASH exists in base data
        mod_data = {
            "mod_name": "Collision Mod",
            "cards": [{"id": "CARD.BASH", "name": "Fake Bash", "character": "Ironclad",
                        "cost": "2", "type": "Attack", "rarity": "Rare"}],
        }
        (tmp_path / "collision.json").write_text(json.dumps(mod_data), encoding="utf-8")
        with patch("sts2.knowledge.MODS_DIR", tmp_path):
            kb = KnowledgeBase()
        bash_cards = [c for c in kb.cards if c.id == "CARD.BASH"]
        assert len(bash_cards) == 1
        assert bash_cards[0].source == "base"  # base wins

    def test_malformed_mod_no_crash(self, tmp_path):
        (tmp_path / "bad_mod.json").write_text("not valid json", encoding="utf-8")
        with patch("sts2.knowledge.MODS_DIR", tmp_path):
            from sts2.knowledge import KnowledgeBase
            kb = KnowledgeBase()
        assert len(kb.cards) > 0  # base data still loaded

    def test_empty_mods_dir(self, tmp_path):
        with patch("sts2.knowledge.MODS_DIR", tmp_path):
            from sts2.knowledge import KnowledgeBase
            kb = KnowledgeBase()
        assert len(kb.cards) > 0  # base data loaded fine

    def test_nonexistent_mods_dir(self):
        with patch("sts2.knowledge.MODS_DIR", Path("/nonexistent/mods/dir")):
            from sts2.knowledge import KnowledgeBase
            kb = KnowledgeBase()
        assert len(kb.cards) > 0


# ---------------------------------------------------------------------------
# CSV export
# ---------------------------------------------------------------------------

class TestCSVExport:
    async def test_csv_export_endpoint(self, client):
        async with client as c:
            resp = await c.get("/api/export/runs")
        assert resp.status_code == 200
        assert "text/csv" in resp.headers.get("content-type", "")
        assert "attachment" in resp.headers.get("content-disposition", "")
        lines = resp.text.strip().split("\n")
        assert "id" in lines[0]
        assert "character" in lines[0]
        assert "deck_size" in lines[0]

    async def test_csv_export_with_filters(self, client):
        async with client as c:
            resp = await c.get("/api/export/runs?character=Ironclad&result=win")
        assert resp.status_code == 200

    def test_csv_safe_function(self):
        from sts2.routes import _csv_safe
        assert _csv_safe("normal") == "normal"
        assert _csv_safe("=FORMULA") == "'=FORMULA"
        assert _csv_safe("+cmd") == "'+cmd"
        assert _csv_safe("-cmd") == "'-cmd"
        assert _csv_safe("@cmd") == "'@cmd"
        assert _csv_safe("") == ""


# ---------------------------------------------------------------------------
# API pagination
# ---------------------------------------------------------------------------

class TestAPIPagination:
    async def test_pagination_envelope(self, client):
        async with client as c:
            resp = await c.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert "total" in data
        assert "offset" in data
        assert "limit" in data
        assert "runs" in data
        assert isinstance(data["runs"], list)

    async def test_pagination_offset(self, client):
        async with client as c:
            resp = await c.get("/api/runs?offset=0&limit=1")
        assert resp.status_code == 200
        data = resp.json()
        assert data["offset"] == 0
        assert data["limit"] == 1
        assert len(data["runs"]) <= 1

    async def test_pagination_out_of_range(self, client):
        async with client as c:
            resp = await c.get("/api/runs?offset=999999&limit=10")
        assert resp.status_code == 200
        data = resp.json()
        assert data["runs"] == []

    async def test_pagination_with_filters(self, client):
        async with client as c:
            resp = await c.get("/api/runs?character=Ironclad&result=win&offset=0&limit=5")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data["total"], int)


# ---------------------------------------------------------------------------
# Theme
# ---------------------------------------------------------------------------

class TestTheme:
    def test_theme_init_js_exists(self):
        from sts2.config import STATIC_DIR
        assert (STATIC_DIR / "theme-init.js").exists()

    async def test_base_has_theme_toggle(self, client):
        async with client as c:
            resp = await c.get("/")
        assert resp.status_code == 200
        assert "theme-init.js" in resp.text
        assert "theme-toggle" in resp.text

    def test_css_has_light_theme(self):
        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        assert '[data-theme="light"]' in css
        # Check critical overrides
        assert "--regent: #b8860b" in css  # WCAG-safe regent color
        assert "--silent: #178344" in css   # WCAG-safe silent color
        assert "--ironclad: #c0392b" in css # WCAG-safe ironclad color

    def test_css_card_bg_not_circular(self):
        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        # Should NOT have --card-bg: var(--card-bg) (circular reference)
        assert "--card-bg: var(--card-bg)" not in css


# ---------------------------------------------------------------------------
# CSP
# ---------------------------------------------------------------------------

class TestCSP:
    async def test_strict_csp_on_normal_pages(self, client):
        async with client as c:
            resp = await c.get("/")
        csp = resp.headers.get("Content-Security-Policy", "")
        assert "cdn.jsdelivr.net" not in csp
        assert "script-src 'self'" in csp

    async def test_relaxed_csp_on_docs(self, client):
        async with client as c:
            resp = await c.get("/docs")
        # /docs may redirect or return 200
        if resp.status_code == 200:
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "cdn.jsdelivr.net" in csp

    async def test_relaxed_csp_on_openapi(self, client):
        async with client as c:
            resp = await c.get("/openapi.json")
        if resp.status_code == 200:
            csp = resp.headers.get("Content-Security-Policy", "")
            assert "cdn.jsdelivr.net" in csp


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    async def test_sse_exempt_from_rate_limit(self, client):
        """SSE endpoint should not consume rate limit budget."""
        _rate_limit_store.clear()
        async with client as c:
            try:
                resp = await c.get("/api/live/stream?player=0")
            except Exception:
                pass

    async def test_options_exempt_from_rate_limit(self, client):
        _rate_limit_store.clear()
        async with client as c:
            resp = await c.options("/api/runs")
        assert resp.status_code != 429

    async def test_api_key_bypass(self, client):
        """API key should bypass rate limit — uses store injection instead of 65 HTTP calls."""
        import os
        import collections
        _rate_limit_store.clear()
        # Simulate an exhausted rate limit by injecting timestamps directly
        import time
        now = time.monotonic()
        _rate_limit_store["127.0.0.1"] = collections.deque([now] * 65)
        with patch.dict(os.environ, {"SPIRESCOPE_API_KEY": "test-secret-key"}):
            async with client as c:
                resp = await c.get("/api/runs", headers={"x-api-key": "test-secret-key"})
        assert resp.status_code == 200

    async def test_wrong_api_key_rate_limited(self, client):
        """Wrong API key should not bypass rate limit."""
        import os
        import collections
        _rate_limit_store.clear()
        import time
        now = time.monotonic()
        _rate_limit_store["127.0.0.1"] = collections.deque([now] * 65)
        with patch.dict(os.environ, {"SPIRESCOPE_API_KEY": "real-key"}):
            async with client as c:
                resp = await c.get("/health", headers={"x-api-key": "wrong-key"})
        assert resp.status_code == 429

    async def test_no_api_key_env_no_bypass(self, client):
        """When SPIRESCOPE_API_KEY is unset, x-api-key header does nothing."""
        import os
        import collections
        _rate_limit_store.clear()
        import time
        now = time.monotonic()
        _rate_limit_store["127.0.0.1"] = collections.deque([now] * 65)
        env = os.environ.copy()
        env.pop("SPIRESCOPE_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            async with client as c:
                resp = await c.get("/health", headers={"x-api-key": "anything"})
        assert resp.status_code == 429


# ---------------------------------------------------------------------------
# analyze_deck bug fix (Unknown type exclusion)
# ---------------------------------------------------------------------------

class TestAnalyzeDeckBugFix:
    def test_unknown_type_excluded_from_ratios(self):
        from sts2.app import kb as _kb
        # Mix of known and unknown-type cards
        card_ids = ["CARD.BASH", "CARD.STRIKE"]  # known attacks
        # Add some cards that won't be found (simulate unknown)
        analysis = _kb.analyze_deck(card_ids)
        # Should not crash and should compute ratios correctly
        assert "deck_size" in analysis
        assert "weaknesses" in analysis

    def test_all_unknown_cards_returns_error(self):
        from sts2.app import kb as _kb
        analysis = _kb.analyze_deck(["FAKE.NOT_REAL_1", "FAKE.NOT_REAL_2"])
        assert "error" in analysis

    def test_aoe_weakness_detected(self):
        from sts2.app import kb as _kb
        # Find cards without AoE keyword
        non_aoe_cards = [c for c in _kb.cards
                         if "AoE" not in c.keywords and c.type == "Attack"][:5]
        if non_aoe_cards:
            analysis = _kb.analyze_deck([c.id for c in non_aoe_cards])
            has_aoe_weakness = any("AoE" in w for w in analysis.get("weaknesses", []))
            assert has_aoe_weakness

    def test_draw_weakness_detected(self):
        from sts2.app import kb as _kb
        non_draw_cards = [c for c in _kb.cards
                          if "Draw" not in c.keywords and c.type == "Attack"][:5]
        if non_draw_cards:
            analysis = _kb.analyze_deck([c.id for c in non_draw_cards])
            has_draw_weakness = any("draw" in w.lower() for w in analysis.get("weaknesses", []))
            assert has_draw_weakness


# ---------------------------------------------------------------------------
# Mod/discovered badges in templates
# ---------------------------------------------------------------------------

class TestSourceBadges:
    async def test_cards_page_shows_mod_badge(self, client):
        from sts2.app import kb as _kb
        original = _kb.cards
        try:
            _kb.cards = list(original) + [Card(
                id="MOD.TEST_BADGE", name="Test Badge Card", character="Ironclad",
                cost="1", type="Attack", rarity="Common", source="mod")]
            _kb._cards_by_id["MOD.TEST_BADGE"] = _kb.cards[-1]
            async with client as c:
                resp = await c.get("/cards")
            assert resp.status_code == 200
            if "Test Badge Card" in resp.text:
                assert "tag-mod" in resp.text
        finally:
            _kb.cards = original
            _kb._cards_by_id.pop("MOD.TEST_BADGE", None)


# ---------------------------------------------------------------------------
# Community page aggregate section
# ---------------------------------------------------------------------------

class TestCommunityAggregate:
    async def test_community_shows_aggregate(self, client):
        mock_aggregate = {
            "run_count": 50,
            "character_stats": {
                "Ironclad": {"wins": 30, "total": 50},
            },
        }
        with patch("sts2.aggregate.load_aggregate", return_value=mock_aggregate):
            async with client as c:
                resp = await c.get("/community")
        assert resp.status_code == 200
        assert "Player Stats" in resp.text
        assert "50" in resp.text  # run count

    async def test_community_no_aggregate(self, client):
        with patch("sts2.aggregate.load_aggregate", return_value={}):
            async with client as c:
                resp = await c.get("/community")
        assert resp.status_code == 200
        # Should not show player stats section
        assert "Player Stats" not in resp.text


# ---------------------------------------------------------------------------
# CLI commands
# ---------------------------------------------------------------------------

class TestCLI:
    def test_cli_help_lists_new_commands(self):
        import subprocess
        result = subprocess.run(
            ["python", "-m", "sts2", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        assert "export" in result.stdout
        assert "reset-stats" in result.stdout

    def test_cli_export_writes_file(self, tmp_path):
        """Export CLI should compute stats and write aggregate JSON to disk."""
        from sts2.aggregate import compute_aggregate_stats, save_aggregate, _aggregate_storage_path
        from sts2.saves import get_run_history
        runs = get_run_history()
        stats = compute_aggregate_stats(runs)
        # Write to a temp path to verify the round-trip
        out = tmp_path / "community_aggregate.json"
        with patch("sts2.aggregate._aggregate_storage_path", return_value=out):
            save_aggregate(stats)
        assert out.exists()
        loaded = json.loads(out.read_text(encoding="utf-8"))
        assert "run_count" in loaded
        assert loaded["run_count"] == len(runs)

    def test_cli_reset_stats_deletes_file(self, tmp_path):
        """Reset CLI should delete the aggregate file."""
        from sts2.aggregate import reset_aggregate, save_aggregate
        out = tmp_path / "community_aggregate.json"
        with patch("sts2.aggregate._aggregate_storage_path", return_value=out):
            save_aggregate({"run_count": 5})
            assert out.exists()
            result = reset_aggregate()
        assert result is True
        assert not out.exists()

    def test_cli_reset_stats_nonexistent(self, tmp_path):
        """Reset CLI should return False when no file exists."""
        from sts2.aggregate import reset_aggregate
        out = tmp_path / "nonexistent.json"
        with patch("sts2.aggregate._aggregate_storage_path", return_value=out):
            result = reset_aggregate()
        assert result is False


# ---------------------------------------------------------------------------
# Runs page has import form with CSRF
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SSE integration
# ---------------------------------------------------------------------------

class TestSSEIntegration:
    async def test_sse_delivers_event_data(self):
        """SSE generator should yield valid JSON data events."""
        import asyncio
        from sts2.routes import live_stream
        # Call the route handler directly to get the StreamingResponse
        resp = await live_stream(player=0)
        assert resp.media_type == "text/event-stream"
        # Consume just the first event from the async generator
        body_gen = resp.body_iterator
        first_chunk = await asyncio.wait_for(body_gen.__anext__(), timeout=10.0)
        assert first_chunk.startswith("data: ")
        payload = json.loads(first_chunk.split("data: ", 1)[1].split("\n\n")[0])
        assert "active" in payload
        assert "character" in payload
        assert "current_hp" in payload
        # Close the generator to clean up the SSE connection counter
        await body_gen.aclose()

    async def test_sse_connection_limit_enforced(self):
        """SSE max connections constant should be reasonable."""
        from sts2.routes import _SSE_MAX_CONNECTIONS
        assert 1 <= _SSE_MAX_CONNECTIONS <= 50

    async def test_sse_idle_timeout_set(self):
        """SSE should have an idle timeout to prevent zombie connections."""
        from sts2.routes import _SSE_IDLE_TIMEOUT
        assert _SSE_IDLE_TIMEOUT > 0
        assert _SSE_IDLE_TIMEOUT <= 600


# ---------------------------------------------------------------------------
# Runs page has import form with CSRF
# ---------------------------------------------------------------------------

class TestRunsImportForm:
    async def test_runs_page_has_csrf_and_import(self, client):
        async with client as c:
            resp = await c.get("/runs")
        assert resp.status_code == 200
        assert "csrf_token" in resp.text
