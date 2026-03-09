"""Tests for the STS2 log parser (LogRunState + LogTailer)."""
import os
import tempfile
from pathlib import Path

import pytest

from sts2.logparser import LogRunState, LogTailer


# ── LogRunState ──────────────────────────────────────────────────────────

class TestLogRunState:
    def test_initial_state(self):
        state = LogRunState()
        assert not state.active
        assert state.character == ""
        assert state.deck == []
        assert state.potions == []
        assert state.gold == 0
        assert state.act == 1
        assert state.floor == 0
        assert state.total_players == 1

    def test_reset(self):
        state = LogRunState()
        state.active = True
        state.character = "Ironclad"
        state.deck = ["CARD.BASH"]
        state.gold = 100
        state.act = 3
        state.floor = 15
        state.reset()
        assert not state.active
        assert state.character == ""
        assert state.deck == []
        assert state.gold == 0
        assert state.act == 1
        assert state.floor == 0

    def test_to_dict(self):
        state = LogRunState()
        state.active = True
        state.character = "Ironclad"
        state.deck = ["CARD.BASH", "CARD.STRIKE"]
        state.gold = 50
        state.act = 2
        state.floor = 8
        state.potions = ["POTION.FIRE"]
        state.events_seen = ["EVENT.NEOW"]
        state.total_players = 2

        d = state.to_dict()
        assert d["active"] is True
        assert d["character"] == "Ironclad"
        assert d["gold"] == 50
        assert d["act"] == 2
        assert d["floor"] == 8
        assert d["deck"] == ["CARD.BASH", "CARD.STRIKE"]
        assert d["deck_upgrades"] == [False, False]
        assert d["potions"] == ["POTION.FIRE"]
        assert d["events_seen"] == ["EVENT.NEOW"]
        assert d["total_players"] == 2
        assert d["current_hp"] == 0  # not available from log
        assert d["max_hp"] == 0
        assert d["run_time"] == 0
        assert d["floors"] == []
        assert d["player_index"] == 0


# ── LogTailer._process_line ──────────────────────────────────────────────

class TestProcessLine:
    def setup_method(self):
        self.tailer = LogTailer(log_path=Path("/dev/null"))
        self.state = self.tailer.state

    def test_empty_line(self):
        assert self.tailer._process_line("") is False

    def test_local_ready_starts_run(self):
        line = "[INFO] [StartRunLobby] Local player 0 is ready"
        assert self.tailer._process_line(line) is True
        assert self.state.active is True
        assert self.state.run_started is True

    def test_neow_event(self):
        line = "[VERYDEBUG] [EventSynchronizer] Event EVENT.NEOW began for player 0"
        assert self.tailer._process_line(line) is True
        assert self.state.active is True
        assert "EVENT.NEOW" in self.state.events_seen

    def test_character_select(self):
        line = "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.IRONCLAD"
        assert self.tailer._process_line(line) is True
        assert self.state.character == "Ironclad"

    def test_character_select_unknown(self):
        line = "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.NEWCHAR"
        assert self.tailer._process_line(line) is True
        assert self.state.character == "CHARACTER.NEWCHAR"

    def test_client_connect_coop(self):
        line = "[INFO] [StartRunLobby] Client 1 connected"
        assert self.tailer._process_line(line) is True
        assert self.state.total_players == 2

    def test_save_written(self):
        line = r"[INFO] Wrote 1234 bytes to path=C:\AppData\saves\current_run.save "
        assert self.tailer._process_line(line) is True
        assert self.state.active is True

    def test_floor_movement(self):
        line = "[DEBUG] [MapSelectionSynchronizer] Moving to coordinate MapCoord (1, 3)"
        assert self.tailer._process_line(line) is True
        assert self.state.act == 2
        assert self.state.floor == 4

    def test_epoch_act_completion(self):
        line = "[INFO] Epoch obtained for completing Act 2"
        assert self.tailer._process_line(line) is True
        assert self.state.act == 3

    def test_room_preload_no_state_change(self):
        line = "[INFO] Preloading 'CombatRoom' assets"
        assert self.tailer._process_line(line) is False

    def test_combat_start(self):
        line = "[INFO] Creating NCombatRoom with mode=ActiveCombat encounter=JAW_WORM"
        assert self.tailer._process_line(line) is True
        assert self.state.current_encounter == "ENCOUNTER.JAW_WORM"

    def test_won_encounter(self):
        line = "[INFO] CHARACTER.IRONCLAD has won against encounter ENCOUNTER.SENTRIES"
        assert self.tailer._process_line(line) is True
        assert "ENCOUNTER.SENTRIES" in self.state.encounters_won
        assert self.state.character == "Ironclad"

    def test_won_encounter_preserves_existing_character(self):
        self.state.character = "Silent"
        line = "[INFO] CHARACTER.IRONCLAD has won against encounter ENCOUNTER.SENTRIES"
        self.tailer._process_line(line)
        assert self.state.character == "Silent"  # not overwritten

    def test_lost_encounter(self):
        line = "[INFO] CHARACTER.DEFECT fought ENCOUNTER.HEXAGHOST for the first time and LOST"
        assert self.tailer._process_line(line) is True
        assert self.state.character == "Defect"

    def test_lost_encounter_preserves_existing_character(self):
        self.state.character = "Regent"
        line = "[INFO] CHARACTER.DEFECT fought ENCOUNTER.HEXAGHOST for the first time and LOST"
        self.tailer._process_line(line)
        assert self.state.character == "Regent"

    def test_card_obtained(self):
        line = "[INFO] Obtained CARD.INFLAME from card reward"
        assert self.tailer._process_line(line) is True
        assert "CARD.INFLAME" in self.state.deck

    def test_potion_obtained(self):
        line = "[INFO] Obtained POTION.FIRE from potion reward"
        assert self.tailer._process_line(line) is True
        assert "POTION.FIRE" in self.state.potions

    def test_gold_obtained(self):
        line = "[INFO] Obtained 25 gold from reward"
        assert self.tailer._process_line(line) is True
        assert self.state.gold == 25

    def test_gold_accumulates(self):
        self.tailer._process_line("[INFO] Obtained 25 gold from reward")
        self.tailer._process_line("[INFO] Obtained 10 gold from reward")
        assert self.state.gold == 35

    def test_potion_used(self):
        self.state.potions = ["POTION.FIRE"]
        line = "[INFO] Player 0 using potion FIRE"
        assert self.tailer._process_line(line) is True
        assert "POTION.FIRE" not in self.state.potions

    def test_potion_used_not_in_inventory(self):
        line = "[INFO] Player 0 using potion FIRE"
        assert self.tailer._process_line(line) is True
        assert self.state.potions == []  # no crash

    def test_potion_discarded(self):
        self.state.potions = ["POTION.SMOKE"]
        line = "[INFO] Player 0 discarding potion SMOKE"
        assert self.tailer._process_line(line) is True
        assert "POTION.SMOKE" not in self.state.potions

    def test_potion_discarded_not_in_inventory(self):
        line = "[INFO] Player 0 discarding potion SMOKE"
        assert self.tailer._process_line(line) is True

    def test_run_ended_saved_history(self):
        self.state.active = True
        line = "[INFO] Saved run history: 42.run"
        assert self.tailer._process_line(line) is True
        assert self.state.active is False

    def test_lobby_disconnect_quit(self):
        self.state.active = True
        line = "[INFO] [RunLobby] Disconnected. Reason: QuitGameOver"
        assert self.tailer._process_line(line) is True
        assert self.state.active is False

    def test_lobby_disconnect_other_reason(self):
        self.state.active = True
        line = "[INFO] [RunLobby] Disconnected. Reason: NetworkError"
        assert self.tailer._process_line(line) is False
        assert self.state.active is True  # not ended

    def test_unrecognized_line(self):
        assert self.tailer._process_line("[DEBUG] Something unrelated happened") is False


# ── LogTailer.poll ───────────────────────────────────────────────────────

class TestLogTailerPoll:
    def test_poll_nonexistent_file(self):
        tailer = LogTailer(log_path=Path("/nonexistent/path/godot.log"))
        assert tailer.poll() is None

    def test_poll_empty_file(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text("")
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is None

    def test_poll_active_run(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.IRONCLAD\n"
            "[INFO] Obtained CARD.BASH from card reward\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is not None
        assert result["active"] is True
        assert result["character"] == "Ironclad"
        assert "CARD.BASH" in result["deck"]

    def test_poll_ended_run_returns_none(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "[INFO] Saved run history: 1.run\n"
        )
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is None

    def test_poll_quit_gameover_returns_none(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "[INFO] [RunLobby] Disconnected. Reason: QuitGameOver\n"
        )
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is None

    def test_poll_incremental_update(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.SILENT\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        result1 = tailer.poll()
        assert result1 is not None
        assert result1["character"] == "Silent"

        # Append new data
        with open(log_file, "a") as f:
            f.write("[INFO] Obtained CARD.NEUTRALIZE from card reward\n")

        result2 = tailer.poll()
        assert result2 is not None
        assert "CARD.NEUTRALIZE" in result2["deck"]

    def test_poll_no_change(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        tailer.poll()  # initial parse
        result = tailer.poll()  # no changes
        assert result is None

    def test_poll_log_truncated(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        tailer.poll()  # initial parse

        # Truncate log (simulating rotation) — shorter than before
        log_file.write_text("[INFO] New log\n")
        result = tailer.poll()
        # Should re-parse from scratch without crashing
        # (result depends on new content — just verify no exception)
        assert result is None or isinstance(result, dict)

    def test_poll_coop_run(self, tmp_path):
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "[INFO] [StartRunLobby] Client 1 connected\n"
            "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.IRONCLAD\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run_mp.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is not None
        assert result["total_players"] == 2

    def test_poll_full_run_lifecycle(self, tmp_path):
        """Simulate a complete run: start, play, end."""
        log_file = tmp_path / "godot.log"
        log_file.write_text(
            "[INFO] [StartRunLobby] Local player 0 is ready\n"
            "Received LobbyPlayerChangedCharacterMessage for 0 CHARACTER.NECROBINDER\n"
            r"[INFO] Wrote 500 bytes to path=C:\saves\current_run.save " + "\n"
        )
        tailer = LogTailer(log_path=log_file)
        result = tailer.poll()
        assert result is not None
        assert result["active"] is True

        # Add gameplay events
        with open(log_file, "a") as f:
            f.write("[DEBUG] [MapSelectionSynchronizer] Moving to coordinate MapCoord (0, 2)\n")
            f.write("[INFO] Creating NCombatRoom with mode=ActiveCombat encounter=JAW_WORM\n")
            f.write("[INFO] CHARACTER.NECROBINDER has won against encounter ENCOUNTER.JAW_WORM\n")
            f.write("[INFO] Obtained CARD.DARK_PACT from card reward\n")
            f.write("[INFO] Obtained 30 gold from reward\n")

        result = tailer.poll()
        assert result is not None
        assert result["floor"] == 3
        assert result["gold"] == 30
        assert "CARD.DARK_PACT" in result["deck"]

        # End the run
        with open(log_file, "a") as f:
            f.write("[INFO] Saved run history: 42.run\n")

        result = tailer.poll()
        assert result is None  # run ended, no active state
