"""Encounter rosters must remain distinct from monsters and starting lineups."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import EncounterRoster, apply_enemy_profile, read_profiles
from sts2.models import Enemy

ROOT = Path(__file__).parents[1]


def test_rosters_match_independent_encounter_pool_and_resolve_all_monsters():
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-encounter-rosters.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    expected = {i for i in baseline["expected_catalog_ids"]["enemies"] if i.startswith("ENCOUNTER.")}
    assert set(raw["encounter_rosters"]) == expected == set(proof["reviewed_ids"])
    assert len(expected) == 85 and not proof["complete"]
    kb = KnowledgeBase(game_version="v0.107.1")
    for identifier, record in raw["encounter_rosters"].items():
        digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["roster_record_sha256"]
        enemy = kb.get_enemy_by_id(identifier)
        assert enemy.roster_version == "v0.107.1"
        assert enemy.hp_range == ""
        assert all(kb.get_enemy_by_id(i).stats_version == "v0.107.1" for i in enemy.monster_ids)
    assert kb.mechanics_status()["reviewed_encounters"] == 85


def test_rosters_preserve_variants_spawns_and_version_boundaries():
    kb = KnowledgeBase(game_version="v0.107.1")
    dummy = kb.get_enemy_by_id("ENCOUNTER.BATTLEWORN_DUMMY_EVENT_ENCOUNTER")
    assert dummy.monster_ids == ["MONSTER.BATTLE_FRIEND_V1", "MONSTER.BATTLE_FRIEND_V2", "MONSTER.BATTLE_FRIEND_V3"]
    fabricator = kb.get_enemy_by_id("ENCOUNTER.FABRICATOR_NORMAL")
    assert set(fabricator.monster_ids) == {
        "MONSTER.FABRICATOR", "MONSTER.GUARDBOT", "MONSTER.NOISEBOT", "MONSTER.STABBOT", "MONSTER.ZAPBOT"}
    assert fabricator.type == "normal"
    assert kb.get_enemy_by_id("ENCOUNTER.AEONGLASS_BOSS").type == "boss"
    assert "MONSTER.BOWLBUG_SILK" not in kb.get_enemy_by_id("ENCOUNTER.BOWLBUGS_WEAK").monster_ids
    assert "MONSTER.BOWLBUG_SILK" in kb.get_enemy_by_id("ENCOUNTER.BOWLBUGS_NORMAL").monster_ids
    assert not kb.enemy_for_version(dummy.id, "v0.111.0").roster_version
    assert kb.get_enemy_by_id(dummy.id) is dummy
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    mod = Enemy(id=dummy.id, name="Mod encounter", source="mod", hp_range="123")
    assert apply_enemy_profile(mod, profile) is mod


@pytest.mark.parametrize("ids", [[], ["CARD.STRIKE"], ["BOSS.AEONGLASS"], ["MONSTER.AEONGLASS"] * 2])
def test_bad_roster_identifiers_are_rejected(ids):
    with pytest.raises(ValidationError):
        EncounterRoster(monster_ids=ids, room_type="normal", definition_sha256="a" * 64)


@pytest.mark.asyncio
async def test_encounter_page_links_versioned_hp_without_claiming_a_starting_lineup(client):
    response = await client.get("/enemies/ENCOUNTER.BATTLEWORN_DUMMY_EVENT_ENCOUNTER?game_version=v0.107.1")
    assert response.status_code == 200
    assert "Possible Monsters" in response.text and "They do not all appear together" in response.text
    assert "/enemies/MONSTER.BATTLE_FRIEND_V2?game_version=v0.107.1" in response.text
    assert "Initial HP: 150" in response.text
    later = await client.get("/enemies/ENCOUNTER.BATTLEWORN_DUMMY_EVENT_ENCOUNTER?game_version=v0.111.0")
    assert "Roster and room type checked for v0.107.1" not in later.text
