"""Live tracking: ghost wiring, telemetry fields, shared danger, caches.

Ghost data used to be computed and discarded (no template or JS consumer),
always for ascension 0 (CurrentRun had no ascension field), the log
telemetry was silently dropped by pydantic, /live and /overlay disagreed on
danger thresholds, and cold caches could be computed twice concurrently or
repopulated with stale data after a refresh.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from sts2.models import CurrentRun, RunFloor, RunHistory


def _live_run(**overrides) -> CurrentRun:
    fields = dict(active=True, character="Ironclad", ascension=10,
                  current_hp=40, max_hp=80, gold=120, act=2, floor=20,
                  deck=["CARD.STRIKE"] * 12, relics=["RELIC.VAJRA"],
                  floors=[RunFloor(floor=19, type="monster", current_hp=45,
                                   gold=100),
                          RunFloor(floor=20, type="monster", current_hp=40,
                                   gold=120)])
    fields.update(overrides)
    return CurrentRun(**fields)


def _win(ascension: int, run_time: int = 3600) -> RunHistory:
    floors = [RunFloor(floor=f, type="monster", current_hp=70 - f, gold=f * 10)
              for f in (19, 20, 21)]
    return RunHistory(id=f"win-a{ascension}", character="Ironclad", win=True,
                      ascension=ascension, run_time=run_time, floors=floors)


class TestCurrentRunFields:
    def test_ascension_and_telemetry_are_declared(self):
        run = CurrentRun(active=True, ascension=15,
                         cards_played=["STRIKE"], extra_turns=2,
                         elites_defeated=3)
        dump = run.model_dump()
        assert dump["ascension"] == 15
        assert dump["cards_played"] == ["STRIKE"]
        assert dump["extra_turns"] == 2
        assert dump["elites_defeated"] == 3

    def test_merged_live_run_carries_log_telemetry(self, monkeypatch):
        """Save+log merge must keep the fields only the log can see."""
        import sts2.app as app_module
        import sts2.routes as routes

        save_run = _live_run()
        monkeypatch.setattr(routes, "get_current_run",
                            lambda player_index=None: save_run)
        monkeypatch.setattr(app_module, "_log_run_state",
                            {"active": True, "act": 1, "encounters_won": [],
                             "cards_played": ["BASH"], "extra_turns": 1,
                             "elites_defeated": 2})

        async def noop():
            return None

        monkeypatch.setattr(app_module, "_poll_game_log_once", noop)
        merged = asyncio.run(routes._compute_live_run(0))
        assert merged.cards_played == ["BASH"]
        assert merged.extra_turns == 1
        assert merged.elites_defeated == 2


class TestGhostWiring:
    async def test_live_page_renders_ghost_for_matching_ascension(self, client):
        """An A10 player with A0 and A10 wins must be compared to the A10
        ghost — the missing ascension field used to force the A0 window."""
        runs = [_win(0), _win(10)]
        with patch("sts2.routes._get_live_run",
                   new=AsyncMock(return_value=_live_run(ascension=10))), \
             patch("sts2.app._get_runs", new=AsyncMock(return_value=runs)):
            resp = await client.get("/live")
        assert resp.status_code == 200
        assert "Ghost Run Comparison" in resp.text
        assert "ghost-splits" in resp.text

    def test_payload_builder_selects_ascension_matched_ghost(self):
        from sts2.ghost import find_ghost_run
        ghost = find_ghost_run("Ironclad", 10, [_win(0), _win(10)])
        assert ghost is not None and ghost.ascension == 10

    async def test_sse_payload_includes_danger_and_ghost(self, monkeypatch):
        import sys

        from sts2.routes import _build_live_payload
        # Pin the HP-threshold fallback: on a dev machine the private risk
        # module may be installed and would drive the level instead.
        monkeypatch.setitem(sys.modules, "sts2.risk", None)
        payload = _build_live_payload(_live_run(ascension=10),
                                      [_win(10)])
        assert payload["danger"]["level"] == "warning"   # 50% HP
        assert payload["danger"]["hp_pct"] == 50
        assert payload["ghost"]["info"] is not None
        assert payload["ghost"]["splits"]
        json.dumps(payload)  # payload must be JSON-serializable

    async def test_inactive_run_payload_has_no_enrichment(self):
        from sts2.routes import _build_live_payload
        payload = _build_live_payload(CurrentRun(active=False), [])
        assert "danger" not in payload
        assert "ghost" not in payload


class TestDangerUnification:
    def test_thresholds_shared_between_pages(self):
        from sts2.routes import _hp_danger
        assert _hp_danger(_live_run(current_hp=20, max_hp=80))[0] == "critical"
        assert _hp_danger(_live_run(current_hp=40, max_hp=80))[0] == "warning"
        assert _hp_danger(_live_run(current_hp=41, max_hp=80))[0] is None
        assert _hp_danger(_live_run(current_hp=10, max_hp=0)) == (None, 0)

    async def test_overlay_renders_computed_hints(self, client):
        """Overlay counter/synergy sections used to be hardwired empty, and
        the synergy line rendered dict reprs when fed real hint objects."""
        run = _live_run(floors=[RunFloor(floor=20, type="monster",
                                         card_picked="CARD.STRIKE")])
        with patch("sts2.routes._get_live_run", new=AsyncMock(return_value=run)):
            resp = await client.get("/overlay")
        assert resp.status_code == 200
        assert "{'card_name'" not in resp.text
        assert "&#39;card_name&#39;" not in resp.text


class TestLogTailerBounds:
    def test_env_override_wins(self, tmp_path, monkeypatch):
        from sts2.logparser import LogTailer
        override = tmp_path / "elsewhere.log"
        monkeypatch.setenv("STS2_LOG_FILE", str(override))
        assert LogTailer().path == override

    def test_initial_parse_reads_only_the_tail(self, tmp_path, monkeypatch):
        import sts2.logparser as lp
        monkeypatch.setattr(lp, "_INIT_TAIL_BYTES", 4096)
        log_file = tmp_path / "godot.log"
        filler = "[INFO] irrelevant line of considerable length\n" * 2000
        log_file.write_text(
            filler
            + "[INFO] [StartRunLobby] Local player 0 is ready\n"
            + "[INFO] Obtained CARD.BASH from card reward\n",
            encoding="utf-8")
        tailer = lp.LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is not None and result["active"] is True
        assert "CARD.BASH" in result["deck"]

    def test_pathological_backlog_reanchors_instead_of_reading_all(
            self, tmp_path, monkeypatch):
        import sts2.logparser as lp
        monkeypatch.setattr(lp, "_MAX_POLL_BYTES", 1024)
        monkeypatch.setattr(lp, "_INIT_TAIL_BYTES", 2048)
        log_file = tmp_path / "godot.log"
        log_file.write_text("[INFO] boot\n", encoding="utf-8")
        tailer = lp.LogTailer(log_path=log_file)
        tailer.poll()
        with open(log_file, "a", encoding="utf-8") as fh:
            fh.write("[INFO] filler line\n" * 500)
            fh.write("[INFO] [StartRunLobby] Local player 0 is ready\n")
        result = tailer.poll()
        assert result is not None and result["active"] is True


class TestLiveMemo:
    async def test_concurrent_calls_share_one_computation(self, monkeypatch):
        import sts2.routes as routes
        routes._live_memo.clear()
        calls = 0

        async def fake_compute(player=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0)
            return CurrentRun(active=False)

        monkeypatch.setattr(routes, "_compute_live_run", fake_compute)
        await routes._get_live_run(0)
        await routes._get_live_run(0)
        assert calls == 1
        routes._live_memo.clear()


class TestCacheRaces:
    async def test_cold_analytics_is_computed_once(self, monkeypatch):
        import sts2.app as app_module
        app_module._analytics_cache = {}
        app_module._analytics_cache_time = {}
        calls = 0

        def fake_compute(runs, card_stats, kb):
            nonlocal calls
            calls += 1
            return {"n": calls}

        monkeypatch.setattr(app_module, "compute_analytics", fake_compute)
        monkeypatch.setattr(app_module, "_get_runs",
                            AsyncMock(return_value=[]))
        monkeypatch.setattr(app_module, "_get_progress",
                            AsyncMock(return_value=None))
        results = await asyncio.gather(app_module._get_analytics(),
                                       app_module._get_analytics())
        assert calls == 1
        assert results[0] == results[1]
        app_module._analytics_cache = {}
        app_module._analytics_cache_time = {}

    async def test_refresh_generation_blocks_stale_repopulation(self, monkeypatch):
        """A computation that started before a refresh must not be cached
        after it."""
        import sts2.app as app_module
        app_module._analytics_cache = {}
        app_module._analytics_cache_time = {}
        started = asyncio.Event()
        release = asyncio.Event()

        async def slow_get_runs():
            started.set()
            await release.wait()
            return []

        monkeypatch.setattr(app_module, "_get_runs", slow_get_runs)
        monkeypatch.setattr(app_module, "_get_progress",
                            AsyncMock(return_value=None))
        monkeypatch.setattr(app_module, "compute_analytics",
                            lambda runs, card_stats, kb: {"stale": True})

        task = asyncio.create_task(app_module._get_analytics())
        await started.wait()
        app_module._data_generation += 1  # what _refresh_data does first
        release.set()
        result = await task
        assert result == {"stale": True}          # caller still gets an answer
        assert app_module._analytics_cache == {}  # but nothing stale is cached
        app_module._analytics_cache = {}
        app_module._analytics_cache_time = {}


class TestCacheGenerationOnReload:
    """Clearing a cache is not enough on its own.

    Both the admin reload and the language change cleared the analytics
    cache without bumping the refresh generation, so a computation that
    started beforehand could finish afterwards and write its stale result
    into the cache that was just emptied.
    """

    async def test_reload_bumps_the_generation(self, client):
        import sts2.app as app_module
        before = app_module._data_generation
        resp = await client.post("/api/reload",
                                 headers={"X-Admin-Token": app_module._ADMIN_TOKEN})
        assert resp.status_code == 200
        assert app_module._data_generation > before

    async def test_language_change_bumps_the_generation(self, client, monkeypatch):
        import sts2.app as app_module
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", __import__("pathlib").Path(
            __import__("tempfile").mkdtemp()))
        before = app_module._data_generation
        from sts2.app import generate_csrf_token
        # Must differ from the active language, or the route correctly skips
        # the rebuild (and with it the cache clear) entirely.
        resp = await client.post("/settings/language",
                                 data={"language": "de",
                                       "csrf_token": generate_csrf_token()},
                                 follow_redirects=False)
        assert resp.status_code == 303
        assert app_module._data_generation > before


class TestLiveMemoIsSingleFlight:
    async def test_concurrent_cold_callers_compute_once(self, monkeypatch):
        """The memo only ever helped callers that arrived after someone else
        had finished; concurrent cold callers each did the disk work."""
        import sts2.routes as routes
        routes._live_memo.clear()
        routes._live_memo_locks.clear()
        calls = 0

        async def slow_compute(player=None):
            nonlocal calls
            calls += 1
            await asyncio.sleep(0.05)
            return CurrentRun(active=False)

        monkeypatch.setattr(routes, "_compute_live_run", slow_compute)
        await asyncio.gather(*(routes._get_live_run(0) for _ in range(5)))
        assert calls == 1
        routes._live_memo.clear()
        routes._live_memo_locks.clear()


class TestReadinessDepth:
    async def test_missing_family_is_not_ready(self, client, monkeypatch):
        """Cards alone was too shallow: a dataset with cards but no relics or
        enemies reported ready while most of the app was broken."""
        from unittest.mock import MagicMock

        import sts2.app as app_module
        stub = MagicMock(cards=[1], relics=[], enemies=[1], potions=[1], events=[1])
        monkeypatch.setattr(app_module, "kb", stub)
        resp = await client.get("/ready")
        assert resp.status_code == 503
        assert "relics" in resp.json()["reason"]
