"""Live saves key players by net_id; floor stats must still be found."""
import json
from unittest.mock import patch

from sts2.models import CurrentRun, RunFloor
from sts2.saves import get_current_run


def _live_save(players, stats):
    return {"players": players, "map_point_history": [[{
        "map_point_type": "monster", "player_stats": stats,
    }]]}


def test_live_save_matches_floor_stats_by_net_id(tmp_path):
    # current_run.save keys players by net_id, not id; matching only on id
    # left every live floor blank (no cards, HP or gold).
    save = _live_save(
        [{"net_id": 1, "character_id": "CHARACTER.NECROBINDER", "deck": []}],
        [{"player_id": 1, "current_hp": 52, "max_hp": 66, "current_gold": 99,
          "damage_taken": 7,
          "card_choices": [{"card": {"id": "CARD.BLUR"}, "was_picked": True}],
          "potion_choices": [{"choice": "POTION.FIRE", "was_picked": True}],
          "potion_used": ["POTION.BLOCK"]}],
    )
    (tmp_path / "current_run.save").write_text(json.dumps(save), encoding="utf-8")
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        floor = get_current_run().floors[0]
    assert floor.cards_picked == ["CARD.BLUR"]
    assert floor.potions_gained == ["POTION.FIRE"]
    assert floor.potions_used == ["POTION.BLOCK"]
    assert (floor.current_hp, floor.max_hp, floor.gold, floor.damage_taken) == (52, 66, 99, 7)


def test_live_coop_save_keeps_each_players_stats_apart(tmp_path):
    save = _live_save(
        [{"net_id": 1, "deck": []}, {"net_id": 2, "deck": []}],
        [{"player_id": 2, "current_hp": 20}, {"player_id": 1, "current_hp": 52}],
    )
    (tmp_path / "current_run.save").write_text(json.dumps(save), encoding="utf-8")
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        assert get_current_run(0).floors[0].current_hp == 52
        assert get_current_run(1).floors[0].current_hp == 20


def test_live_save_reads_gained_cards_relics_and_upgrades_by_net_id(tmp_path):
    save = _live_save(
        [{"net_id": 1, "deck": []}],
        [{"player_id": 1,
          "relic_choices": [{"choice": "RELIC.LAVA_ROCK", "was_picked": True}],
          "bought_colorless": ["CARD.ETERNAL_ARMOR"],
          "cards_gained": [{"id": "CARD.ETERNAL_ARMOR"}],
          "upgraded_cards": ["CARD.BLUR"]}],
    )
    (tmp_path / "current_run.save").write_text(json.dumps(save), encoding="utf-8")
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        floor = get_current_run().floors[0]
    assert floor.relics_gained == ["RELIC.LAVA_ROCK"]
    assert floor.cards_picked == ["CARD.ETERNAL_ARMOR"]
    assert floor.cards_upgraded == ["CARD.BLUR"]


async def test_live_floor_history_shows_every_card_and_potion(client):
    import sts2.app

    run = CurrentRun(active=True, character="Silent", current_hp=50, max_hp=70,
                     deck=["CARD.BLUR"], floors=[RunFloor(
                         floor=1, type="monster", current_hp=50, max_hp=70,
                         cards_picked=["CARD.BLUR", "CARD.ETERNAL_ARMOR"],
                         cards_upgraded=["CARD.BLUR"],
                         relics_gained=["RELIC.LAVA_ROCK"],
                         relics_removed=["RELIC.ANCHOR"],
                         potions_gained=["POTION.FIRE"],
                         potions_used=["POTION.BLOCK"],
                     )])
    name = sts2.app.kb.id_to_name
    with patch("sts2.routes.get_current_run", return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    history = resp.text.split("Floor History")[1]
    assert f"+ {name('CARD.BLUR')}" in history
    assert f"+ {name('CARD.ETERNAL_ARMOR')}" in history
    assert f"Upgraded: {name('CARD.BLUR')}" in history
    assert f"Relic obtained: {name('RELIC.LAVA_ROCK')}" in history
    assert f"Relic removed: {name('RELIC.ANCHOR')}" in history
    assert f"Found {name('POTION.FIRE')}" in history
    assert f"Used {name('POTION.BLOCK')}" in history
