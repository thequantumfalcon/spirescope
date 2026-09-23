"""Native main HP is qualified separately from reference enemy behavior."""
import hashlib
import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import MonsterStats, apply_monster_stats, read_profiles
from sts2.models import Enemy

ROOT = Path(__file__).parents[1]


def test_hp_profile_matches_independent_monster_pool():
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-monster-stats.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    expected = {i for i in baseline["expected_catalog_ids"]["enemies"] if i.startswith("MONSTER.")}
    assert set(raw["monster_stats"]) == expected == set(proof["reviewed_ids"])
    assert len(expected) == 107 and not proof["complete"]
    for identifier, record in raw["monster_stats"].items():
        digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["stats_record_sha256"]


def test_main_hp_thresholds_do_not_certify_unreviewed_patterns():
    kb = KnowledgeBase(game_version="v0.107.1")
    cultist = kb.get_enemy_by_id("MONSTER.CALCIFIED_CULTIST")
    assert cultist.hp_range == "38–41 (Ascension 8+: 39–42)"
    assert cultist.stats_version == "v0.107.1"
    # Act 1 moves are reviewed; HP review alone still certifies nothing about patterns.
    assert cultist.mechanics_version == "v0.107.1"
    aeonglass = kb.get_enemy_by_id("MONSTER.AEONGLASS")
    assert aeonglass.hp_range == "512 (Ascension 8+: 535)"
    assert aeonglass.stats_version == "v0.107.1" and aeonglass.mechanics_version == ""
    assert kb.get_counter_cards(aeonglass) == []
    assert kb.get_enemy_by_id("MONSTER.BATTLE_FRIEND_V1").hp_range == "75"
    later = kb.enemy_for_version(cultist.id, "v0.111.0")
    assert later.stats_version == "" and kb.get_enemy_by_id(cultist.id) is cultist
    assert kb.mechanics_status()["reviewed_monster_stats"] == 107
    assert kb.mechanics_status("v0.111.0")["reviewed_monster_stats"] == 0
    assert kb.enemy_for_version("MONSTER.UNKNOWN", "v0.111.0") is None


def test_counter_advice_uses_only_matching_patterns_and_card_mechanics():
    kb = KnowledgeBase(game_version="v0.107.1")
    enemy = Enemy(id="MONSTER.EXAMPLE", name="Example", patterns=["Multiple high damage hits."],
                  mechanics_version="v0.107.1")
    cards = kb.get_counter_cards(enemy)
    assert cards
    assert all(c.mechanics_version == "v0.107.1" and not c.instance_rule for c in cards)
    assert kb.get_counter_cards(enemy, game_version="v0.111.0") == []
    assert kb.get_counter_cards(enemy.model_copy(update={"mechanics_version": ""})) == []
    # The installed build must not supply mechanics to an explicitly historical view.
    reference = KnowledgeBase(game_version="")
    assert all(c.mechanics_version == "v0.107.1"
               for c in reference.get_counter_cards(enemy, game_version="v0.107.1"))


def test_mod_and_encounter_hp_are_not_replaced_by_monster_ranges():
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    mod = Enemy(id="MONSTER.CALCIFIED_CULTIST", name="Modified", hp_range="900", source="mod")
    encounter = Enemy(id="ENCOUNTER.CALCIFIED_CULTISTS", name="Encounter")
    assert apply_monster_stats(mod, profile) is mod
    assert apply_monster_stats(encounter, profile) is encounter
    assert apply_monster_stats(mod, None) is mod


@pytest.mark.parametrize("hp", [[42, 39], [0, 1], [-1, 5], [1, 1_000_001], [1], [True, 2], ["1", 2]])
def test_invalid_hp_ranges_reject_the_profile(hp):
    with pytest.raises(ValidationError):
        MonsterStats(hp_base=hp, hp_ascension_8=[1, 2], definition_sha256="a" * 64)


@pytest.mark.asyncio
async def test_enemy_page_distinguishes_hp_patterns_and_selected_version(client):
    main = await client.get("/enemies/MONSTER.CALCIFIED_CULTIST?game_version=v0.107.1")
    later = await client.get("/enemies/MONSTER.CALCIFIED_CULTIST?game_version=v0.111.0")
    assert main.status_code == later.status_code == 200
    assert "Initial HP checked for v0.107.1" in main.text
    assert "Ascension 8+: 39–42" in main.text
    assert "Patterns checked for v0.107.1" in main.text
    unreviewed = await client.get("/enemies/MONSTER.AEONGLASS?game_version=v0.107.1")
    assert unreviewed.status_code == 200
    assert "Counter Cards" not in unreviewed.text
    assert "Patterns checked for" not in unreviewed.text
    assert "Initial HP checked for v0.107.1" not in later.text
