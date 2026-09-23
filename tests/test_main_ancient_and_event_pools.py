"""Native main offer restrictions must survive catalog application and act filtering."""
from unittest.mock import patch

import pytest

from sts2.knowledge import KnowledgeBase


@pytest.fixture(scope="module")
def events():
    return {event.id: event for event in KnowledgeBase(game_version="v0.107.1").events}


def test_ancient_pools_preserve_conditional_and_weighted_offers(events):
    pael = events["EVENT.PAEL"]
    assert "at least 3 Goopy-eligible" in pael.choices[1].outcome
    assert "at least 5 removable" in pael.choices[1].outcome
    assert "no event pet" in pael.choices[2].outcome
    assert "twice the selection weight of Growth" in pael.notes
    orobas = events["EVENT.OROBAS"]
    assert "this offer is locked" in orobas.choices[2].outcome
    assert "first eligible card in deck order" in orobas.notes
    assert "upgrade and enchantment are carried across" in orobas.notes


def test_neow_separates_normal_offers_and_modifier_runs(events):
    neow = events["EVENT.NEOW"]
    assert "two positive-pool offers and one tradeoff-pool offer" in neow.description
    assert "one at a time" in neow.choices[2].outcome
    assert "Massive Scroll is multiplayer only" in neow.notes
    assert "Silver Crucible are solo only" in neow.notes
    assert "80% of Max HP at Ascension 2+" in neow.notes
    assert "requires all character card pools unlocked" in neow.notes


def test_ancient_hp_loss_and_enchantment_thresholds_are_explicit(events):
    assert "loses 9 Max HP and adds 3 Apparitions" in events["EVENT.VAKUU"].choices[1].outcome
    assert "at least 4 cards" in events["EVENT.NONUPEIPE"].choices[1].outcome
    assert "at least 3 cards" in events["EVENT.TANX"].choices[1].outcome
    assert "Basic-rarity Strike-tagged" in events["EVENT.TEZCATARA"].choices[0].outcome


def test_darv_does_not_mix_act_specific_candidates(events):
    darv = events["EVENT.DARV"]
    assert darv.kind == "ancient"
    assert darv.act == ["Act 2", "Act 3"]
    assert "Ectoplasm and Sozu" in darv.choices[1].outcome
    assert "Philosopher's Stone and Velvet Choker" in darv.choices[2].outcome
    assert "clears the starting deck" in darv.notes
    assert "appearance is not guaranteed" in darv.availability_note


def test_wongo_leaving_and_points_are_not_treated_as_harmless_or_score_unlocks(events):
    wongo = events["EVENT.WELCOME_TO_WONGOS"]
    assert "Downgrade one random upgraded card" in wongo.choices[3].outcome
    assert "32 Wongo Points" in wongo.choices[0].outcome
    assert "16 Wongo Points" in wongo.choices[1].outcome
    assert "8 Wongo Points" in wongo.choices[2].outcome
    assert "3 relic rewards after 5 completed combats, once" in wongo.choices[2].outcome
    assert "separate from the end-of-run score" in wongo.notes


def test_fake_merchant_shared_flag_does_not_imply_multiplayer_availability(events):
    merchant = events["EVENT.FAKE_MERCHANT"]
    assert merchant.is_shared and merchant.sp_only
    assert merchant.act == ["Act 2", "Act 3"]
    assert "100 Gold or hold Foul Potion" in merchant.availability_note
    assert "displayed shop price" in merchant.choices[0].outcome
    assert "still stocked" in merchant.choices[1].outcome
    assert "shop price variation and modifiers" in merchant.notes


def test_act_one_variants_and_forced_event_are_distinct(events):
    assert events["EVENT.ABYSSAL_BATHS"].locations == ["Underdocks"]
    assert events["EVENT.JUNGLE_MAZE_ADVENTURE"].locations == ["Overgrowth"]
    assert events["EVENT.SUNKEN_STATUE"].locations == ["Overgrowth", "Underdocks"]
    assert events["EVENT.AMALGAMATOR"].act == ["Act 2"]
    assert events["EVENT.ROUND_TEA_PARTY"].act == ["Act 3"]
    assert events["EVENT.WAR_HISTORIAN_REPY"].act == ["Act 3"]
    assert events["EVENT.STONE_OF_ALL_TIME"].act == ["Act 2"]
    assert events["EVENT.ROOM_FULL_OF_CHEESE"].act == ["Act 1", "Act 2"]


def test_ordinary_event_combat_and_damage_costs_remain_distinct(events):
    party = events["EVENT.ROUND_TEA_PARTY"]
    assert "11 unblockable damage" in party.choices[1].outcome
    assert "does not start a combat" in party.notes
    punch = events["EVENT.PUNCH_OFF"]
    assert "Add Injury" in punch.choices[0].outcome
    assert "1 relic and 1 potion" in punch.choices[1].outcome
    assert "6 onward" in punch.availability_note


@pytest.mark.asyncio
async def test_act_filter_uses_reviewed_main_membership(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    with patch("sts2.app.kb", kb):
        response = await client.get("/events?act=Act%202")
    assert response.status_code == 200
    assert "Combine Defends" in response.text
    assert "Wongo Points" in response.text
    assert "Choose a positive-pool offer" not in response.text
    assert "<h1>Events &amp; Ancients" in response.text


@pytest.mark.asyncio
async def test_solo_merchant_does_not_render_a_multiplayer_label(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    kb.events = [e for e in kb.events if e.id == "EVENT.FAKE_MERCHANT"]
    with patch("sts2.app.kb", kb):
        response = await client.get("/events")
    assert response.status_code == 200
    assert "Solo only" in response.text
    assert "Shared event in multiplayer" not in response.text


def test_foreign_versions_do_not_inherit_main_event_pools():
    kb = KnowledgeBase(game_version="v0.111.0")
    merchant = next(e for e in kb.events if e.id == "EVENT.FAKE_MERCHANT")
    assert merchant.mechanics_version == ""
    assert merchant.kind == "" and not merchant.locations
