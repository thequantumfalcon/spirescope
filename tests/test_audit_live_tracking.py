"""Live tracking audit fixes: log player ids, per-player fallback (F15),
save/log run identity (F16), and the SSE content revision (F17).

The log lines here follow the format of a real v0.10x godot.log: in solo
every play is "Player 1 playing card STRIKE_IRONCLAD (targeting ...)" -- the
number is the save's player id ("1"), not seat index 0, and the card id has
no CARD. prefix. The earlier synthetic "Player 0 ... CARD.BASH" fixtures
matched neither, which is how solo live "cards played" stayed empty.
"""
import asyncio
import json
from unittest.mock import AsyncMock, patch

from sts2.logparser import LogTailer
from sts2.models import CurrentRun, RunFloor

SOLO_LOG = [
    "[INFO] [StartRunLobby (1)] CHARACTER.IRONCLAD ascension set to preferred: 1",
    "[INFO] [StartRunLobby (1)] Local player 1 is ready",
    "[INFO] Embarking on a singleplayer IRONCLAD run. Ascension: 1 Seed: TESTSEED01",
    "[INFO] Creating NCombatRoom with mode=ActiveCombat encounter=NIBBITS_WEAK",
    "[INFO] Player 1 playing card BASH (targeting Nibbit (index 1))",
    "[INFO] Player 1 playing card STRIKE_IRONCLAD (targeting Nibbit (index 1))",
    "[INFO] Player 1 playing card DEFEND_IRONCLAD (no target)",
    "[INFO] CHARACTER.IRONCLAD has won against encounter ENCOUNTER.NIBBITS_WEAK. That's 3 wins",
]


def _tail(tmp_path, lines) -> LogTailer:
    log_file = tmp_path / "godot.log"
    log_file.write_text("".join(line + "\n" for line in lines), encoding="utf-8")
    tailer = LogTailer(log_path=log_file)
    tailer.poll()
    return tailer


def _save_run(**overrides) -> CurrentRun:
    fields = dict(active=True, character="Ironclad", ascension=1,
                  current_hp=70, max_hp=80, gold=99, act=1, floor=2,
                  deck=["CARD.BASH", "CARD.STRIKE_IRONCLAD"],
                  relics=["RELIC.BURNING_BLOOD"], player_index=0,
                  total_players=1, player_id="1", seed="TESTSEED01")
    fields.update(overrides)
    return CurrentRun(**fields)


def _merge(monkeypatch, save_run: CurrentRun, log_state: dict | None,
           player: int | None = None) -> CurrentRun:
    import sts2.app as app_module
    import sts2.routes as routes

    monkeypatch.setattr(routes, "get_current_run",
                        lambda player_index=None: save_run)
    monkeypatch.setattr(app_module, "_log_run_state", log_state)

    async def noop():
        return None

    monkeypatch.setattr(app_module, "_poll_game_log_once", noop)
    return asyncio.run(routes._compute_live_run(player))


def _coop_log(**overrides) -> dict:
    state = {"active": True, "character": "Silent", "act": 1,
             "encounters_won": [], "elites_defeated": 0,
             "cards_played": [], "extra_turns": 0,
             "cards_played_by_player": {111: ["CARD.BASH"]},
             "extra_turns_by_player": {111: 2},
             "seed": "TESTSEED01", "log_ascension": None}
    state.update(overrides)
    return state


class TestSoloLogFormat:
    def test_real_solo_lines_are_attributed_to_player_one(self, tmp_path):
        t = _tail(tmp_path, SOLO_LOG)
        assert t.state.local_player == 1
        assert t.state.cards_played_by_player == {
            1: ["CARD.BASH", "CARD.STRIKE_IRONCLAD", "CARD.DEFEND_IRONCLAD"]}
        # Defaults to the local player, not seat 0.
        assert t.state.to_dict()["cards_played"] == [
            "CARD.BASH", "CARD.STRIKE_IRONCLAD", "CARD.DEFEND_IRONCLAD"]

    def test_card_ids_are_normalized_once(self, tmp_path):
        t = _tail(tmp_path, ["[INFO] [StartRunLobby (1)] Local player 1 is ready",
                             "[INFO] Player 1 playing card BASH (no target)",
                             "[INFO] Player 1 playing card CARD.BASH"])
        assert t.state.cards_played_by_player[1] == ["CARD.BASH", "CARD.BASH"]

    def test_embark_line_gives_run_identity(self, tmp_path):
        d = _tail(tmp_path, SOLO_LOG).state.to_dict()
        assert d["seed"] == "TESTSEED01"
        assert d["ascension"] == 1 and d["log_ascension"] == 1
        assert d["character"] == "Ironclad"

    def test_identity_unknown_without_embark_line(self, tmp_path):
        d = _tail(tmp_path, ["[INFO] [StartRunLobby (1)] Local player 1 is ready",
                             "[INFO] Player 1 playing card BASH (no target)"]
                  ).state.to_dict()
        assert d["seed"] == ""
        assert d["log_ascension"] is None
        CurrentRun(**d)  # log-only path must still validate

    def test_sole_logged_player_is_default_without_lobby_line(self):
        from sts2.logparser import LogRunState
        state = LogRunState()
        state.cards_played_by_player = {7: ["CARD.BASH"]}
        assert state.to_dict()["cards_played"] == ["CARD.BASH"]
        state.cards_played_by_player[8] = ["CARD.ZAP"]
        assert state.to_dict()["cards_played"] == []  # ambiguous: not guessed

    def test_save_exposes_player_id_and_seed(self, tmp_path):
        from sts2.saves import get_current_run
        (tmp_path / "current_run.save").write_text(json.dumps({
            "seed": "TESTSEED01", "current_act_index": 0, "ascension": 1,
            "players": [{"id": 1, "character_id": "CHARACTER.IRONCLAD",
                         "current_hp": 70, "max_hp": 80, "gold": 99,
                         "deck": [{"id": "CARD.BASH"}], "relics": [],
                         "potions": []}]}), encoding="utf-8")
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
        assert run.player_id == "1"
        assert run.seed == "TESTSEED01"

    def test_solo_merge_reports_cards_played(self, tmp_path, monkeypatch):
        """End to end: real-format solo log + solo save (player id 1)."""
        log_state = _tail(tmp_path, SOLO_LOG).state.to_dict()
        merged = _merge(monkeypatch, _save_run(), log_state)
        assert merged.cards_played == [
            "CARD.BASH", "CARD.STRIKE_IRONCLAD", "CARD.DEFEND_IRONCLAD"]
        assert merged.encounters_won == ["ENCOUNTER.NIBBITS_WEAK"]

    def test_solo_merge_without_save_id_uses_sole_player(self, tmp_path, monkeypatch):
        log_state = _tail(tmp_path, SOLO_LOG).state.to_dict()
        merged = _merge(monkeypatch, _save_run(player_id=""), log_state)
        assert len(merged.cards_played) == 3


class TestPerPlayerFallback:
    """F15: with a per-player map present, a player with no entry played
    nothing -- another player's plays must never stand in for theirs."""

    def test_player_without_entries_gets_zero(self, monkeypatch):
        save = _save_run(total_players=2, player_index=1, player_id="222",
                         seed="", character="Ironclad")
        merged = _merge(monkeypatch, save, _coop_log(
            cards_played=["CARD.BASH"], extra_turns=2))
        assert merged.cards_played == []
        assert merged.extra_turns == 0

    def test_switching_player_selects_their_own_entries(self, monkeypatch):
        save = _save_run(total_players=2, player_index=0, player_id="111", seed="TESTSEED01")
        merged = _merge(monkeypatch, save, _coop_log())
        assert merged.cards_played == ["CARD.BASH"]
        assert merged.extra_turns == 2

    def test_legacy_log_without_maps_uses_flat_totals(self, monkeypatch):
        legacy = {"active": True, "act": 1, "encounters_won": [],
                  "cards_played": ["CARD.BASH"], "extra_turns": 1,
                  "elites_defeated": 2, "seed": "TESTSEED01"}
        merged = _merge(monkeypatch, _save_run(), legacy)
        assert merged.cards_played == ["CARD.BASH"]
        assert merged.extra_turns == 1
        assert merged.elites_defeated == 2

    def test_coop_save_without_id_does_not_guess(self, monkeypatch):
        save = _save_run(total_players=2, player_id="", seed="")
        merged = _merge(monkeypatch, save, _coop_log())
        assert merged.cards_played == []


class TestRunIdentity:
    """F16: a log is merged only when it describes the same run."""

    def test_different_seed_uses_save_alone(self, monkeypatch):
        save = _save_run()
        log_state = _coop_log(seed="OTHERSEED", act=3, character="Ironclad",
                              encounters_won=["ENCOUNTER.OLD"],
                              elites_defeated=4,
                              cards_played_by_player={1: ["CARD.ZAP"]})
        merged = _merge(monkeypatch, save, log_state)
        assert merged.deck == save.deck
        assert merged.telemetry_status == "mismatched"
        assert merged.act == 1 and merged.encounters_won == []
        assert merged.cards_played == [] and merged.elites_defeated == 0

    def test_same_seed_merges(self, monkeypatch):
        log_state = _coop_log(seed="TESTSEED01", act=2, character="Ironclad",
                              encounters_won=["ENCOUNTER.NIBBITS_WEAK"],
                              elites_defeated=1,
                              cards_played_by_player={1: ["CARD.BASH"]},
                              extra_turns_by_player={})
        merged = _merge(monkeypatch, _save_run(), log_state)
        assert merged.act == 2
        assert merged.encounters_won == ["ENCOUNTER.NIBBITS_WEAK"]
        assert merged.elites_defeated == 1
        assert merged.cards_played == ["CARD.BASH"]

    def test_solo_character_mismatch_without_seed_is_rejected(self, monkeypatch):
        """The audit's reproduction: Ironclad save, Defect log at Act 3."""
        save = _save_run(seed="")
        log_state = _coop_log(character="Defect", act=3,
                              encounters_won=["ENCOUNTER.OLD"])
        merged = _merge(monkeypatch, save, log_state)
        assert merged.act == 1
        assert merged.encounters_won == []

    def test_ascension_mismatch_without_seed_is_rejected(self, monkeypatch):
        save = _save_run(seed="")
        log_state = _coop_log(character="Ironclad", log_ascension=5, act=3)
        assert _merge(monkeypatch, save, log_state).act == 1

    def test_unknown_identity_uses_save_alone(self, monkeypatch):
        """Absence of contradiction is not evidence of a shared run."""
        save = _save_run(seed="")
        log_state = _coop_log(character="", act=2, seed="")
        assert _merge(monkeypatch, save, log_state).act == 1

    def test_coop_character_is_not_compared(self, monkeypatch):
        """In co-op the log's character line can name the teammate."""
        save = _save_run(total_players=2, player_id="111")
        merged = _merge(monkeypatch, save, _coop_log(character="Silent", act=2))
        assert merged.act == 2

    def test_log_never_lowers_act_or_replaces_save_encounters(self, monkeypatch):
        save = _save_run(act=3, encounters_won=["ENCOUNTER.FROM_SAVE"])
        log_state = _coop_log(seed="TESTSEED01", act=2,
                              encounters_won=["ENCOUNTER.FROM_LOG"])
        merged = _merge(monkeypatch, save, log_state)
        assert merged.act == 3
        assert merged.encounters_won == ["ENCOUNTER.FROM_SAVE"]


class TestContentRevision:
    """F17: same-floor list changes must be visible to the SSE client."""

    @staticmethod
    def _rev(run):
        from sts2.routes import _live_content_revision
        return _live_content_revision(run)

    def test_revision_tracks_rendered_lists(self):
        base = _save_run(potions=["POTION.FIRE_POTION"])
        rev = self._rev(base)
        changed = [
            base.model_copy(update={"deck": base.deck + ["CARD.ANGER"]}),
            base.model_copy(update={"deck_upgrades": [True, False]}),
            base.model_copy(update={"deck_enchantments": ["ENCHANTMENT.X", ""]}),
            base.model_copy(update={"relics": ["RELIC.VAJRA"]}),
            base.model_copy(update={"potions": []}),
        ]
        revs = {self._rev(r) for r in changed}
        assert rev not in revs
        assert len(revs) == len(changed)

    def test_revision_ignores_counters(self):
        base = _save_run()
        same = base.model_copy(update={"current_hp": 1, "gold": 999,
                                       "floor": base.floor, "run_time": 50})
        assert self._rev(same) == self._rev(base)

    def test_payload_carries_revision(self):
        from sts2.routes import _build_live_payload
        run = _save_run()
        payload = _build_live_payload(run, [])
        assert payload["revision"] == self._rev(run)
        assert len(payload["revision"]) == 12
        json.dumps(payload)
        assert "revision" in _build_live_payload(CurrentRun(active=False), [])

    async def test_page_renders_the_same_revision(self, client):
        run = _save_run(floors=[RunFloor(floor=2, type="monster")])
        with patch("sts2.routes._get_live_run", new=AsyncMock(return_value=run)), \
             patch("sts2.app._get_runs", new=AsyncMock(return_value=[])):
            resp = await client.get("/live")
        assert resp.status_code == 200
        assert f'data-revision="{self._rev(run)}"' in resp.text
