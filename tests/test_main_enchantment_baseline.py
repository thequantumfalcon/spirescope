"""Enchantment rules are build-qualified per version and never inferred from names."""
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import read_profiles
from sts2.models import RunHistory

ROOT = Path(__file__).parents[1]


def test_main_enchantment_profile_matches_registry_and_record_hashes():
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-enchantment-mechanics.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "docs/game-baselines/v0.107.1-model-registry.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    reviewed = {record["model_id"]: record for record in registry["records"].values()
                if record["family"] == "Enchantments" and record["status"] == "reviewed_catalog_scope"}
    assert set(profile["enchantments"]) == set(proof["reviewed_ids"]) == set(reviewed)
    assert len(profile["enchantments"]) == 22
    assert registry["family_counts"]["Enchantments"] == {
        "reviewed_catalog_scope": 22, "deprecated_placeholder": 1, "mock": 1}
    assert not proof["complete"]
    for identifier, record in profile["enchantments"].items():
        assert record["definition_sha256"] == reviewed[identifier]["definition_sha256"]
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]
        assert "{" not in record["description"].replace("{Amount}", "")


def test_enchantment_lookup_is_version_scoped():
    kb = KnowledgeBase(game_version="v0.107.1")
    ember = kb.enchantment_for_version("ENCHANTMENT.TEZCATARAS_EMBER")
    assert ember.title == "Tezcatara's Ember"
    assert "deals 3 additional damage" in ember.description
    assert kb.id_to_name("ENCHANTMENT.TEZCATARAS_EMBER") == "Tezcatara's Ember"
    assert kb.enchantment_for_version("ENCHANTMENT.CORRUPTED").eligibility == "Attacks only."
    assert kb.mechanics_status()["reviewed_enchantments"] == 22
    assert kb.enchantment_for_version("ENCHANTMENT.SOWN", "v0.111.0") is None
    assert kb.enchantment_for_version("ENCHANTMENT.SOWN", "") is None
    other = KnowledgeBase(game_version="v0.111.0")
    assert other.mechanics_status()["reviewed_enchantments"] == 0
    assert other.id_to_name("ENCHANTMENT.TEZCATARAS_EMBER") == "Tezcataras Ember"


def test_profile_rejects_non_canonical_enchantment_ids(tmp_path):
    catalog = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))
    profile = catalog["profiles"][0]
    profile["enchantments"] = {"SOWN": profile["enchantments"]["ENCHANTMENT.SOWN"]}
    broken = tmp_path / "mechanics.json"
    broken.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="canonical enchantment identifiers"):
        read_profiles(broken)


@pytest.mark.asyncio
async def test_run_page_scopes_enchantment_rules_to_the_run_version(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    reviewed = RunHistory(id="ench", character="Ironclad", win=False, build_id="v0.107.1",
                          deck=["CARD.STRIKE_IRONCLAD"], deck_enchantments=["ENCHANTMENT.SOWN"])
    unrecorded = reviewed.model_copy(update={"id": "ench2", "build_id": ""})
    with patch("sts2.app.kb", kb), \
         patch("sts2.app._get_run_by_id", new_callable=AsyncMock, return_value=reviewed):
        page = await client.get("/runs/ench")
    assert page.status_code == 200
    assert "Sown (v0.107.1): The first time you play this card each combat, gain {Amount} Energy." in page.text
    with patch("sts2.app.kb", kb), \
         patch("sts2.app._get_run_by_id", new_callable=AsyncMock, return_value=unrecorded):
        page = await client.get("/runs/ench2")
    assert page.status_code == 200
    assert "&#10022; Sown" in page.text
    assert "(v0.107.1)" not in page.text
