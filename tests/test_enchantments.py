"""P5 enchantment visibility: parsing from run history and current-run saves."""
import json
from unittest.mock import patch

from sts2.saves import get_current_run, get_run_history

ENCHANTED_DECK = [
    {"id": "CARD.STRIKE_NECROBINDER", "floor_added_to_deck": 1,
     "enchantment": {"amount": 1, "id": "ENCHANTMENT.TEZCATARAS_EMBER"}},
    {"id": "CARD.DEFEND_NECROBINDER", "upgrade_count": 1},
    {"id": "CARD.REAP"},
]

RUN_JSON = {
    "win": True,
    "ascension": 2,
    "seed": "ABCDEF123456",
    "build_id": "v0.109.0",
    "players": [{"character": "CHAR.NECROBINDER", "deck": ENCHANTED_DECK,
                 "relics": []}],
    "map_point_history": [],
}

CURRENT_RUN_JSON = {
    "players": [{"character_id": "CHARACTER.NECROBINDER",
                 "current_hp": 50, "max_hp": 70, "gold": 100,
                 "deck": ENCHANTED_DECK, "relics": [], "potions": []}],
    "current_act_index": 0,
    "run_time": 300,
}


def test_run_history_parses_enchantments(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "1000.run").write_text(json.dumps(RUN_JSON))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert runs[0].enchantments == {
        "CARD.STRIKE_NECROBINDER": "ENCHANTMENT.TEZCATARAS_EMBER"
    }


def test_run_history_no_enchantments_is_empty_dict(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    plain = dict(RUN_JSON)
    plain["players"] = [{"character": "CHAR.IRONCLAD",
                         "deck": [{"id": "CARD.BASH"}], "relics": []}]
    (history / "1000.run").write_text(json.dumps(plain))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert runs[0].enchantments == {}


def test_current_run_parses_deck_enchantments(tmp_path):
    (tmp_path / "current_run.save").write_text(json.dumps(CURRENT_RUN_JSON))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        run = get_current_run()
    assert run.active
    assert run.deck == ["CARD.STRIKE_NECROBINDER", "CARD.DEFEND_NECROBINDER",
                        "CARD.REAP"]
    assert run.deck_enchantments == ["ENCHANTMENT.TEZCATARAS_EMBER", "", ""]
    assert run.deck_upgrades == [False, True, False]
