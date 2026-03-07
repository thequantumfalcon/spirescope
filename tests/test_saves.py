"""Tests for the save file parser."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch

from sts2.saves import get_current_run, get_progress, get_run_history
from sts2.models import CurrentRun, PlayerProgress, RunHistory


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

    def test_empty_players(self, tmp_path):
        save_file = tmp_path / "current_run.save"
        save_file.write_text(json.dumps({"players": []}))

        with patch("sts2.saves.SAVE_DIR", tmp_path):
            run = get_current_run()
            assert run.active is True
            assert run.character == "Unknown"


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
