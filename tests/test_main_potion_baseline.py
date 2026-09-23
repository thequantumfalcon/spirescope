"""Potion mechanics are build-qualified separately from card identity coverage."""
import hashlib
import json
from pathlib import Path

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import apply_potion_profile, read_profiles
from sts2.models import Potion

ROOT = Path(__file__).parents[1]


def test_main_potion_profile_covers_independent_pool_and_record_hashes():
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-potion-mechanics.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    assert set(profile["potions"]) == set(baseline["expected_catalog_ids"]["potions"]) == set(proof["reviewed_ids"])
    assert len(profile["potions"]) == 63
    assert not proof["complete"]
    for identifier, record in profile["potions"].items():
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]


def test_potion_targeting_automatic_use_and_free_play_are_preserved():
    kb = KnowledgeBase(game_version="v0.107.1")
    potion = kb.get_potion_by_id("POTION.BLOCK_POTION")
    assert potion.target == "AnyPlayer" and potion.usage == "CombatOnly"
    assert potion.mechanics_version == "v0.107.1"
    fairy = kb.get_potion_by_id("POTION.FAIRY_IN_A_BOTTLE")
    assert fairy.usage == "Automatic" and not fairy.can_generate_in_combat
    foul = kb.get_potion_by_id("POTION.FOUL_POTION")
    assert foul.target == "RoomDependent" and "before opening" in foul.usage_note
    assert "all players and enemies" in foul.description
    assert "free to play" in kb.get_potion_by_id("POTION.LIQUID_MEMORIES").description
    assert kb.mechanics_status()["reviewed_potions"] == 63
    assert KnowledgeBase(game_version="v0.111.0").mechanics_status()["reviewed_potions"] == 0
    assert KnowledgeBase(game_version="v0.111.0").get_potion_by_id(potion.id).mechanics_version == ""


def test_potion_profiles_preserve_mods_and_unreviewed_items():
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    potion = Potion(id="POTION.BLOCK_POTION", name="Mod potion", description="Mod effect", source="mod")
    assert apply_potion_profile(potion, profile) is potion
    unknown = Potion(id="POTION.UNKNOWN", name="Unknown")
    assert apply_potion_profile(unknown, profile) is unknown


@pytest.mark.asyncio
async def test_main_potion_page_exposes_usage_and_target(client, monkeypatch):
    from sts2 import app

    monkeypatch.setattr(app, "kb", KnowledgeBase(game_version="v0.107.1"))
    response = await client.get("/potions")
    assert response.status_code == 200
    assert "Rules checked for v0.107.1" in response.text
    assert "choose a player" in response.text
    assert "Automatic use" in response.text
    assert "before opening the shop inventory" in response.text
