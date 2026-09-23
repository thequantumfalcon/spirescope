"""Reviewed native evidence stays pinned independently of refreshable prose."""
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import read_profiles
from sts2.models import RunHistory

ROOT = Path(__file__).parents[1]


def test_main_traits_cover_the_independent_native_pool():
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    assert set(profile.card_traits) == set(baseline["expected_catalog_ids"]["cards"])
    assert profile.card_traits["CARD.MAD_SCIENCE"].type == "Variable"
    assert profile.card_traits["CARD.LANTERN_KEY"].type == "Quest"
    assert profile.card_traits["CARD.WHIRLWIND"].cost == "X"
    assert profile.card_traits["CARD.STARDUST"].star_cost == "X"
    assert profile.card_traits["CARD.BARRICADE"].cost_upgraded == "2"
    assert all(row.cost != "Unknown" for row in profile.card_traits.values())
    for suffix in ("DISINTEGRATION", "MIND_ROT", "SLOTH", "WASTE_AWAY"):
        assert profile.card_traits[f"CARD.{suffix}"].cost == "Choice"
        assert profile.cards[f"CARD.{suffix}"].no_upgrade


def test_profile_retains_reviewed_hashes_and_exposes_every_unreviewed_card():
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-card-mechanics.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    assert set(proof["reviewed_card_ids"]) == set(profile["cards"])
    assert set(proof["unreviewed_card_ids"]) == set(profile["card_traits"]) - set(profile["cards"])
    assert not proof["complete"] and not profile["complete"]
    for identifier, row in profile["cards"].items():
        digest = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["card_records"][identifier]["mechanics_record_sha256"]


def test_all_five_characters_have_complete_starter_upgrades():
    kb = KnowledgeBase(game_version="v0.107.1")
    for character in ("IRONCLAD", "SILENT", "DEFECT", "NECROBINDER", "REGENT"):
        strike = kb.get_card_by_id("CARD.STRIKE_" + character)
        defend = kb.get_card_by_id("CARD.DEFEND_" + character)
        assert strike.description_upgraded == "Deal 9 damage."
        assert defend.description_upgraded == "Gain 8 Block."
        assert strike.mechanics_version == defend.mechanics_version == "v0.107.1"


def test_unverified_build_does_not_turn_missing_classification_into_bad_advice():
    kb = KnowledgeBase(game_version="v0.999.0")
    result = kb.analyze_deck(["CARD.BASH"] * 20)
    assert result["unverified_traits"] == 20
    assert result["cost_curve"] == {"Unknown": 20}
    assert result["cost_curve_by_type"] == {"Unknown": {"Unknown": 20}}
    assert not any(text.startswith(("Low attack", "Few skills", "Deck is very thin"))
                   for text in result["weaknesses"])


@pytest.mark.asyncio
async def test_historical_card_url_selects_scare_without_mutating_beta_reference(client):
    main = await client.get("/cards/CARD.SCARE?game_version=v0.107.1")
    beta = await client.get("/cards/CARD.SCARE?game_version=v0.111.0")
    assert main.status_code == beta.status_code == 200
    assert "<title>Scare</title>" in main.text
    assert "Apply 1 Weak to all enemies. Exhaust." in main.text
    assert "<title>Sidestep</title>" in beta.text
    assert "not verified for v0.111.0" in beta.text


@pytest.mark.asyncio
async def test_history_deck_keeps_its_own_build_through_analysis(client, monkeypatch):
    import sts2.app as app

    run = RunHistory(id="old-run", character="Ironclad", win=True, build_id="v0.107.1",
                     deck=["CARD.EXPECT_A_FIGHT"], deck_upgrades=[0], deck_enchantments=[""])
    monkeypatch.setattr(app, "_get_run_by_id", AsyncMock(return_value=run))
    page = await client.get("/deck?from_run=old-run")
    assert 'name="game_version" value="v0.107.1"' in page.text
    response = await client.post("/deck/analyze", data={
        "csrf_token": app.generate_csrf_token(), "game_version": "v0.107.1",
        "card_ids": "CARD.EXPECT_A_FIGHT",
    })
    assert response.status_code == 200
    assert "No Block generation" in response.text
    assert 'name="game_version" value="v0.107.1"' in response.text
    # Missing historical build is explicitly unknown, never the installed build.
    run.build_id = ""
    unknown = await client.get("/deck?from_run=old-run")
    assert 'name="game_version" value=""' in unknown.text
