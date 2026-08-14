"""Tests for the save file parser."""
import json
from unittest.mock import patch

from sts2.models import CurrentRun, PlayerProgress, RunHistory
from sts2.saves import get_current_run, get_progress, get_run_history

MOCK_CURRENT_RUN = {
    "players": [{
        "id": 1,
        "character_id": "CHARACTER.IRONCLAD",
        "current_hp": 65,
        "max_hp": 80,
        "gold": 150,
        "deck": [
            {"id": "CARD.STRIKE", "upgrade_count": 0},
            {"id": "CARD.DEFEND", "upgrade_count": 1},
            {"id": "CARD.BASH", "upgrade_count": 0},
        ],
        "relics": [{"id": "RELIC.BURNING_BLOOD"}],
        "potions": [{"id": "POTION.FIRE_POTION"}],
    }],
    "current_act_index": 1,
    "run_time": 600,
    "events_seen": ["EVENT.BONFIRE"],
    "map_point_history": [
        [
            {
                "map_point_type": "monster",
                "rooms": [{"room_type": "monster", "model_id": "ENCOUNTER.JAW_WORM", "monster_ids": ["JAW_WORM"], "turns_taken": 4}],
                "player_stats": [{
                    "player_id": 1,
                    "damage_taken": 10,
                    "hp_healed": 0,
                    "current_hp": 70,
                    "max_hp": 80,
                    "current_gold": 120,
                    "card_choices": [
                        {"card": {"id": "CARD.ANGER"}, "was_picked": True},
                        {"card": {"id": "CARD.CLEAVE"}, "was_picked": False},
                    ],
                }],
            },
        ],
    ],
}

MOCK_PROGRESS = {
    "total_playtime": 36000,
    "character_stats": [
        {
            "id": "CHARACTER.IRONCLAD",
            "total_wins": 5,
            "total_losses": 3,
            "playtime": 18000,
            "max_ascension": 10,
            "best_win_streak": 3,
            "current_streak": 2,
            "fastest_win_time": 900,
        },
    ],
    "card_stats": [
        {"id": "CARD.BASH", "times_picked": 10, "times_skipped": 5, "times_won": 7, "times_lost": 3},
    ],
    "encounter_stats": [
        {
            "encounter_id": "BOSS.HEXAGHOST",
            "fight_stats": [
                {"character": "CHARACTER.IRONCLAD", "wins": 3, "losses": 1},
            ],
        },
    ],
    "enemy_stats": [
        {
            "enemy_id": "MONSTER.JAW_WORM",
            "fight_stats": [
                {"character": "CHARACTER.IRONCLAD", "wins": 8, "losses": 0},
            ],
        },
    ],
    "discovered_cards": ["CARD.BASH", "CARD.STRIKE"],
    "discovered_relics": ["RELIC.BURNING_BLOOD"],
    "discovered_potions": ["POTION.FIRE_POTION"],
    "discovered_events": ["EVENT.BONFIRE"],
}

MOCK_RUN_HISTORY = {
    "win": True,
    "ascension": 5,
    "seed": "ABC123",
    "acts": ["Act 1", "Act 2", "Act 3"],
    "killed_by_encounter": "",
    "run_time": 1200,
    "build_id": "v1.0",
    "players": [{
        "id": 1,
        "character": "CHARACTER.IRONCLAD",
        "deck": [{"id": "CARD.BASH"}, {"id": "CARD.STRIKE"}],
        "relics": [{"id": "RELIC.BURNING_BLOOD"}],
    }],
    "map_point_history": [
        [
            {
                "map_point_type": "monster",
                "rooms": [{"room_type": "monster", "model_id": "ENC.JAW_WORM", "monster_ids": ["JAW_WORM"], "turns_taken": 3}],
                "player_stats": [{
                    "player_id": 1,
                    "damage_taken": 5,
                    "hp_healed": 0,
                    "current_hp": 75,
                    "max_hp": 80,
                    "current_gold": 110,
                    "card_choices": [
                        {"card": {"id": "CARD.ANGER"}, "was_picked": True},
                    ],
                    "potion_used": ["POTION.FIRE_POTION"],
                    "potion_choices": [{"choice": "POTION.BLOCK_POTION", "was_picked": True}],
                }],
            },
        ],
    ],
}


class TestGetCurrentRun:
    def test_no_save_file(self, tmp_path):
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
            assert isinstance(run, CurrentRun)
            assert run.active is False

    def test_parse_current_run(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_CURRENT_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()

        assert run.active is True
        assert run.character == "Ironclad"
        assert run.current_hp == 65
        assert run.max_hp == 80
        assert run.gold == 150
        assert run.act == 2  # current_act_index + 1
        assert len(run.deck) == 3
        assert "CARD.STRIKE" in run.deck
        assert run.deck_upgrades[1] is True  # DEFEND is upgraded
        assert len(run.relics) == 1
        assert len(run.potions) == 1

    def test_parse_floor_history(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_CURRENT_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()

        assert len(run.floors) == 1
        floor = run.floors[0]
        assert floor.floor == 1
        assert floor.type == "monster"
        assert floor.damage_taken == 10
        assert floor.card_picked == "CARD.ANGER"

    def test_corrupt_save_file(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text("not json{{{")

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
            assert run.active is False

    def test_oversized_current_run_file_is_skipped(self, tmp_path, caplog):
        """A corrupt/hostile current_run.save must not be loaded unbounded.

        Unlike progress.save and history .run files, current_run.save (and
        current_run_mp.save, and their .backup files) go through the shared
        _read_json() reader with no size guard of their own — the guard
        belongs in the reader itself so every caller benefits.
        """
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_CURRENT_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path), \
             patch("sts2.saves._MAX_SAVE_FILE_SIZE", 10), \
             caplog.at_level("WARNING", logger="sts2.saves"):
            run = get_current_run()

        assert run.active is False
        assert "current_run.save" in caplog.text

    def test_empty_players(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps({"players": []}))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
            assert run.active is True
            assert run.character == "Unknown"

    def test_solo_run_total_players(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_CURRENT_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
            assert run.total_players == 1
            assert run.player_index == 0


MOCK_COOP_RUN = {
    "players": [
        {
            "id": 1,
            "character_id": "CHARACTER.IRONCLAD",
            "current_hp": 65,
            "max_hp": 80,
            "gold": 150,
            "deck": [{"id": "CARD.STRIKE", "upgrade_count": 0}],
            "relics": [{"id": "RELIC.BURNING_BLOOD"}],
            "potions": [],
        },
        {
            "id": 2,
            "character_id": "CHARACTER.SILENT",
            "current_hp": 55,
            "max_hp": 70,
            "gold": 120,
            "deck": [{"id": "CARD.NEUTRALIZE", "upgrade_count": 0}],
            "relics": [{"id": "RELIC.RING_OF_THE_SNAKE"}],
            "potions": [],
        },
    ],
    "current_act_index": 0,
    "run_time": 300,
    "events_seen": [],
    "map_point_history": [],
}


class TestCoopSupport:
    def test_coop_player_0(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_COOP_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run(player_index=0)

        assert run.character == "Ironclad"
        assert run.current_hp == 65
        assert run.total_players == 2
        assert run.player_index == 0

    def test_coop_player_1(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_COOP_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run(player_index=1)

        assert run.character == "Silent"
        assert run.current_hp == 55
        assert run.total_players == 2
        assert run.player_index == 1
        assert "CARD.NEUTRALIZE" in run.deck

    def test_coop_invalid_index_falls_back(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps(MOCK_COOP_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run(player_index=99)

        assert run.character == "Ironclad"  # falls back to player 0

    def test_mp_save_file(self, tmp_path):
        save_file = tmp_path / "current_run_mp.save"
        save_file.write_text(json.dumps(MOCK_COOP_RUN))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run(player_index=1)

        assert run.character == "Silent"
        assert run.total_players == 2


class TestGetProgress:
    def test_no_progress_file(self, tmp_path):
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()
            assert progress is None

    def test_parse_progress(self, tmp_path):
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(MOCK_PROGRESS))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()

        assert isinstance(progress, PlayerProgress)
        assert progress.total_playtime == 36000
        assert "Ironclad" in progress.character_stats
        assert progress.character_stats["Ironclad"]["wins"] == 5
        assert "CARD.BASH" in progress.card_stats
        assert len(progress.discovered_cards) == 2

    def test_encounter_stats(self, tmp_path):
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(MOCK_PROGRESS))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()

        assert "BOSS.HEXAGHOST" in progress.encounter_stats
        assert "Ironclad" in progress.encounter_stats["BOSS.HEXAGHOST"]

    def test_character_stats_enhanced_fields(self, tmp_path):
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(MOCK_PROGRESS))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()

        cs = progress.character_stats["Ironclad"]
        assert cs["current_streak"] == 2
        assert cs["fastest_win"] == 900

    def test_enemy_stats(self, tmp_path):
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(MOCK_PROGRESS))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()

        assert "MONSTER.JAW_WORM" in progress.enemy_stats
        jaw_worm = progress.enemy_stats["MONSTER.JAW_WORM"]
        assert "Ironclad" in jaw_worm
        assert jaw_worm["Ironclad"]["wins"] == 8
        assert jaw_worm["Ironclad"]["losses"] == 0

    def test_oversized_progress_file_is_skipped(self, tmp_path, caplog):
        """A corrupt/hostile progress.save must not be loaded unbounded."""
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(MOCK_PROGRESS))

        with patch("sts2.saves.SAVE_DIR", tmp_path), \
             patch("sts2.saves._MAX_SAVE_FILE_SIZE", 10), \
             caplog.at_level("WARNING", logger="sts2.saves"):
            progress = get_progress()

        assert progress is None
        assert "progress.save" in caplog.text


class TestGetRunHistory:
    def test_no_history_dir(self, tmp_path):
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            runs = get_run_history()
            assert runs == []

    def test_parse_run_history(self, tmp_path):
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        run_file = history_dir / "run_001.run"
        run_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            runs = get_run_history()

        assert len(runs) == 1
        run = runs[0]
        assert isinstance(run, RunHistory)
        assert run.id == "run_001"
        assert run.character == "Ironclad"
        assert run.win is True
        assert run.ascension == 5
        assert len(run.deck) == 2
        assert len(run.relics) == 1

    def test_run_floor_details(self, tmp_path):
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        run_file = history_dir / "run_001.run"
        run_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            runs = get_run_history()

        floor = runs[0].floors[0]
        assert floor.damage_taken == 5
        assert floor.card_picked == "CARD.ANGER"
        assert "POTION.FIRE_POTION" in floor.potions_used
        assert "POTION.BLOCK_POTION" in floor.potions_gained

    def test_corrupt_run_file_skipped(self, tmp_path):
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        (history_dir / "bad.run").write_text("not json")
        good_file = history_dir / "good.run"
        good_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            runs = get_run_history()

        assert len(runs) == 1

    def test_multiple_runs_sorted(self, tmp_path):
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        for i in range(3):
            run_file = history_dir / f"run_{i:03d}.run"
            run_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            runs = get_run_history()

        assert len(runs) == 3
        # Should be reverse sorted by filename
        assert runs[0].id == "run_002"
        assert runs[2].id == "run_000"

    def test_oversized_run_file_is_skipped(self, tmp_path, caplog):
        """A corrupt/hostile .run file must not be loaded unbounded."""
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        run_file = history_dir / "big.run"
        run_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path), \
             patch("sts2.saves._MAX_SAVE_FILE_SIZE", 10), \
             caplog.at_level("WARNING", logger="sts2.saves"):
            runs = get_run_history()

        assert runs == []
        assert "big.run" in caplog.text

    def test_run_history_reads_file_bytes_only_once(self, tmp_path):
        """Regression: run files used to be read twice — once via
        read_bytes() for the sha256 digest, once via _read_json() for the
        JSON body. The JSON parse must now reuse the bytes already read for
        the digest instead of re-opening the file."""
        history_dir = tmp_path / "history"
        history_dir.mkdir()
        run_file = history_dir / "run_001.run"
        run_file.write_text(json.dumps(MOCK_RUN_HISTORY))

        with patch("sts2.saves.SAVE_DIR", tmp_path), \
             patch("sts2.saves._read_json") as mock_read_json:
            runs = get_run_history()

        mock_read_json.assert_not_called()
        assert len(runs) == 1
        assert runs[0].id == "run_001"


class TestProgressEpochs:
    def test_progress_includes_epochs(self, tmp_path):
        """Epochs should be parsed from progress save data."""
        data = {
            **MOCK_PROGRESS,
            "epochs": [
                {"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": 1772861383},
                {"id": "SILENT1_EPOCH", "state": "not_obtained", "obtain_date": 0},
            ],
        }
        save_file = tmp_path / "progress.save"
        save_file.write_text(json.dumps(data))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            progress = get_progress()

        assert len(progress.epochs) == 2
        assert progress.epochs[0]["id"] == "NEOW_EPOCH"
        assert progress.epochs[0]["state"] == "revealed"
        assert progress.epochs[1]["state"] == "not_obtained"


class TestCurrentRunMultiTree:
    """Live tracking follows the freshest tree, and carries ascension."""

    @staticmethod
    def _write_live(save_dir, ascension, hp, save_time):
        import json as _json
        save_dir.mkdir(parents=True, exist_ok=True)
        (save_dir / "current_run.save").write_text(_json.dumps({
            "ascension": ascension,
            "save_time": save_time,
            "players": [{"id": "1", "character_id": "CHARACTER.IRONCLAD",
                         "current_hp": hp, "max_hp": 80,
                         "deck": [], "relics": [], "potions": []}],
            "map_point_history": [],
        }), encoding="utf-8")

    def test_current_run_carries_ascension(self, tmp_path):
        from unittest.mock import patch

        from sts2.saves import get_current_run
        self._write_live(tmp_path, 12, 55, 100)
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
        assert run.active is True
        assert run.ascension == 12

    def test_freshest_tree_wins(self, tmp_path):
        """A newer write in the modded tree must beat a stale vanilla file —
        live tracking used to watch only the startup-selected tree."""
        import os
        from unittest.mock import patch

        from sts2.saves import get_current_run
        vanilla = tmp_path / "vanilla" / "saves"
        modded = tmp_path / "modded" / "saves"
        self._write_live(vanilla, 3, 70, 100)
        self._write_live(modded, 9, 20, 200)
        old = (vanilla / "current_run.save")
        newer = (modded / "current_run.save")
        os.utime(old, (1_000_000, 1_000_000))
        os.utime(newer, (2_000_000, 2_000_000))
        with patch("sts2.saves.SAVE_DIR", vanilla), \
             patch("sts2.saves.SAVE_DIRS", [vanilla, modded]):
            run = get_current_run()
        assert run.ascension == 9
        assert run.current_hp == 20
