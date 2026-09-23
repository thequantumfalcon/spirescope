"""Companions and the Architect ending are classified, never treated as enemies or combats."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from sts2.analytics import _is_combat, analyze_run
from sts2.fetcher import _discover_enemies_from_saves
from sts2.identities import is_companion_monster, is_ending_model
from sts2.models import RunFloor, RunHistory


@pytest.mark.parametrize("identifier", ["MONSTER.OSTY", "OSTY", "BYRDPIP", "MONSTER.PAELS_LEGION"])
def test_companion_ids_with_or_without_prefix(identifier):
    assert is_companion_monster(identifier)
    assert not is_ending_model(identifier)


@pytest.mark.parametrize("identifier", ["EVENT.THE_ARCHITECT", "ENCOUNTER.THE_ARCHITECT_EVENT_ENCOUNTER",
                                        "MONSTER.ARCHITECT", "ARCHITECT"])
def test_ending_ids_with_or_without_prefix(identifier):
    assert is_ending_model(identifier)
    assert not is_companion_monster(identifier)


def test_ordinary_monsters_are_neither():
    assert not is_companion_monster("MONSTER.CULTIST")
    assert not is_ending_model("ENCOUNTER.CULTIST")


def test_save_discovery_skips_companions_and_ending(tmp_path):
    save_dir = tmp_path / "saves"
    save_dir.mkdir()
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "enemies.json").write_text("[]")
    progress = {"encounter_stats": [
        {"encounter_id": "ENCOUNTER.THE_ARCHITECT_EVENT_ENCOUNTER", "fight_stats": []},
        {"encounter_id": "BOSS.HEXAGHOST", "fight_stats": []},
    ]}
    (save_dir / "progress.save").write_text(json.dumps(progress))
    history = save_dir / "history"
    history.mkdir()
    run = {
        "players": [{"id": 1}],
        "map_point_history": [[
            {"map_point_type": "monster",
             "rooms": [{"monster_ids": ["CULTIST", "OSTY", "MONSTER.BYRDPIP", "PAELS_LEGION"],
                        "room_type": "monster"}],
             "player_stats": []},
            {"map_point_type": "event",
             "rooms": [{"model_id": "ENCOUNTER.THE_ARCHITECT_EVENT_ENCOUNTER",
                        "monster_ids": ["ARCHITECT"], "room_type": "monster"}],
             "player_stats": []},
        ]],
    }
    (history / "run_001.run").write_text(json.dumps(run))

    with patch("sts2.fetcher.DATA_DIR", data_dir), patch("sts2.config.SAVE_DIR", save_dir):
        discovered = sorted(e["id"] for e in _discover_enemies_from_saves())

    assert discovered == ["BOSS.HEXAGHOST", "MONSTER.CULTIST"]


def test_architect_ending_is_not_a_combat():
    ending = RunFloor(floor=52, type="monster", encounter="ENCOUNTER.THE_ARCHITECT_EVENT_ENCOUNTER",
                      monsters=["ARCHITECT"], turns=1)
    assert not _is_combat(ending)
    assert not _is_combat(RunFloor(floor=52, type="event", encounter="EVENT.THE_ARCHITECT"))
    assert _is_combat(RunFloor(floor=51, type="boss", encounter="ENCOUNTER.HEXAGHOST"))

    run = RunHistory(id="r", character="Ironclad", win=True, run_time=3000,
                     floors=[RunFloor(floor=51, type="boss", encounter="ENCOUNTER.HEXAGHOST", damage_taken=12),
                             ending])
    texts = [i["text"] for i in analyze_run(run)["insights"]]
    assert "12 damage taken across 1 combat." in texts


@pytest.mark.asyncio
async def test_run_page_labels_companions(client):
    run = RunHistory(id="pets", character="Necrobinder", win=False, floors=[
        RunFloor(floor=3, type="monster", encounter="ENCOUNTER.CULTIST", monsters=["MONSTER.CULTIST", "MONSTER.OSTY"]),
    ])
    with patch("sts2.app._get_run_by_id", new_callable=AsyncMock, return_value=run):
        response = await client.get("/runs/pets")
    assert response.status_code == 200
    assert "Osty (companion)" in response.text
    assert "Cultist (companion)" not in response.text
