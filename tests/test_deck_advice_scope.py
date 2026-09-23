"""Composition statistics must not masquerade as a combat or resource model."""
from unittest.mock import AsyncMock, patch

import pytest

from sts2.app import generate_csrf_token
from sts2.knowledge import KnowledgeBase
from sts2.models import CurrentRun


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(game_version="v0.107.1")


@pytest.mark.parametrize("size", [6, 20, 35])
def test_size_and_duplicate_count_do_not_grade_deck_quality(kb, size):
    analysis = kb.analyze_deck(["CARD.STRIKE_IRONCLAD"] * size)
    assert analysis["weaknesses"] == [
        "No Block generation detected in card text.",
        "No AoE detected in card text.",
        "No card draw detected in card text.",
    ]
    assert analysis["strengths"] == []


def test_energy_estimate_uses_unrounded_mean(kb):
    analysis = kb.analyze_deck(["CARD.BASH", "CARD.STRIKE_IRONCLAD", "CARD.STRIKE_IRONCLAD"])
    assert analysis["avg_cost"] == 1.3
    assert analysis["energy_per_hand"] == 6.7
    assert analysis["numeric_cost_cards"] == 3


def test_unresolved_cards_remain_in_cost_curve_as_unknown(kb):
    analysis = kb.analyze_deck(["CARD.BASH", "CARD.NOT_A_REAL_CARD"])
    assert analysis["deck_size"] == 2
    assert analysis["numeric_cost_cards"] == 1
    assert analysis["cost_curve"] == {"2": 1, "Unknown": 1}
    assert analysis["cost_curve_by_type"]["Unknown"] == {"Unknown": 1}


def test_x_cost_is_not_evidence_of_a_free_hand(kb):
    analysis = kb.analyze_deck(["CARD.WHIRLWIND"] * 5)
    assert analysis["numeric_cost_cards"] == 0
    assert analysis["cost_curve"] == {"X": 5}
    assert not any("0-cost" in text for text in analysis["weaknesses"])


def test_effect_presence_does_not_claim_balanced_offense_or_defense(kb):
    analysis = kb.analyze_deck(["CARD.DEFEND_IRONCLAD", "CARD.INFLAME"])
    assert analysis["strengths"] == ["Block generation detected in card text."]


@pytest.mark.asyncio
async def test_deck_page_describes_cost_sample_and_no_fifteen_energy_budget(client, kb):
    with patch("sts2.app.kb", kb):
        response = await client.post("/deck/analyze", data={
            "csrf_token": generate_csrf_token(), "card_ids": ["CARD.BASH", "CARD.STRIKE_IRONCLAD"],
            "game_version": "v0.107.1",
        })
    assert response.status_code == 200
    assert "Five-card Energy estimate" in response.text
    assert "Based on 2 of 2 cards" in response.text
    assert "Stars are separate" in response.text
    assert "Energy/Hand:" not in response.text
    assert "</strong> / 15" not in response.text
    assert "play most of your hand every turn" not in response.text


@pytest.mark.asyncio
async def test_deck_page_shows_unknown_when_all_costs_are_variable(client, kb):
    with patch("sts2.app.kb", kb):
        response = await client.post("/deck/analyze", data={
            "csrf_token": generate_csrf_token(), "card_ids": "CARD.WHIRLWIND",
            "game_version": "v0.107.1",
        })
    assert response.status_code == 200
    assert "Five-card Energy estimate: <strong>Unknown</strong>" in response.text
    assert "Based on 0 of 1 cards" in response.text


@pytest.mark.asyncio
async def test_live_does_not_invent_boss_distance_or_duplicate_penalties(client, kb):
    run = CurrentRun(active=True, character="Ironclad", act=1, floor=13,
                     deck=["CARD.BLUDGEON"] * 4, current_hp=50, max_hp=80)
    with patch("sts2.app.kb", kb), \
         patch("sts2.routes._get_live_run", AsyncMock(return_value=run)), \
         patch("sts2.app._get_runs", AsyncMock(return_value=[])), \
         patch("sts2.app._get_analytics", AsyncMock(return_value={})):
        response = await client.get("/live")
    assert response.status_code == 200
    assert "No Block generation detected in card text" in response.text
    for unsupported in ("Boss in ~", "diminishing returns", "Add 0-cost cards",
                        "No defensive cards by floor", "may cycle too fast"):
        assert unsupported not in response.text
