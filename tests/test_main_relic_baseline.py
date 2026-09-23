"""Main relic rules remain separate from later reference and history views."""
import hashlib
import json
from pathlib import Path

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import apply_relic_profile, read_profiles
from sts2.models import Relic

ROOT = Path(__file__).parents[1]


def test_main_relic_profile_matches_independent_pool_and_record_hashes():
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-relic-mechanics.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    assert set(profile["relics"]) == set(baseline["expected_catalog_ids"]["relics"]) == set(proof["reviewed_ids"])
    assert len(profile["relics"]) == 296
    assert not proof["complete"]
    for identifier, record in profile["relics"].items():
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]


def test_relic_reworks_and_implementation_disagreement_use_main_rules():
    kb = KnowledgeBase(game_version="v0.107.1")
    regalite = kb.get_relic_by_id("RELIC.REGALITE")
    assert regalite.description == "Whenever you create a card in combat, gain 2 Block."
    assert "Draw Pile" in kb.get_relic_by_id("RELIC.TOASTY_MITTENS").description
    assert "half attack damage" in kb.get_relic_by_id("RELIC.DIAMOND_DIADEM").description
    assert "opening turn" in kb.get_relic_by_id("RELIC.JEWELED_MASK").mechanics_note
    assert "upgraded Ancient card" in kb.get_relic_by_id("RELIC.DUSTY_TOME").description
    later = kb.relic_for_version(regalite.id, "v0.111.0")
    assert "4 Block" in later.description and later.mechanics_version == ""
    assert kb.get_relic_by_id(regalite.id) is regalite
    assert kb.mechanics_status()["reviewed_relics"] == 296
    assert kb.mechanics_status("v0.111.0")["reviewed_relics"] == 0
    assert kb.relic_for_version("RELIC.UNKNOWN", "v0.111.0") is None


def test_mod_relic_is_not_replaced_by_main_profile():
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    relic = Relic(id="RELIC.REGALITE", name="Modified Regalite", description="Mod behavior", source="mod")
    assert apply_relic_profile(relic, profile) is relic
    unknown = Relic(id="RELIC.UNKNOWN", name="Unknown")
    assert apply_relic_profile(unknown, profile) is unknown


@pytest.mark.asyncio
async def test_history_relic_page_selects_recorded_game_version(client):
    main = await client.get("/relics/RELIC.REGALITE?game_version=v0.107.1")
    later = await client.get("/relics/RELIC.REGALITE?game_version=v0.111.0")
    assert main.status_code == later.status_code == 200
    assert "gain 2 Block" in main.text and "General rules checked for v0.107.1" in main.text
    assert "gain 4 Block" in later.text and "not verified for v0.111.0" in later.text
    listed = await client.get("/relics")
    assert 'href="/relics?rarity=Ancient' in listed.text
