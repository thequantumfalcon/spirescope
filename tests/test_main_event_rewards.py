"""Regression cases for event options whose reference rewards were incorrect."""
import pytest

from sts2.knowledge import KnowledgeBase


@pytest.fixture(scope="module")
def events():
    return {event.id: event for event in KnowledgeBase(game_version="v0.107.1").events}


def test_random_gold_cost_and_reward_bounds_are_exclusive_at_native_upper_limit(events):
    sphere = events["EVENT.CRYSTAL_SPHERE"]
    assert "51–99 Gold" in sphere.choices[0].outcome
    assert "not future map encounters" in sphere.notes
    vegetation = events["EVENT.DENSE_VEGETATION"]
    assert "8 unblockable damage" in vegetation.choices[0].outcome
    assert "61–99 Gold" in vegetation.choices[0].outcome
    assert "does not remove a card" in vegetation.notes


def test_drowning_beacon_cost_is_max_hp_and_rewards_are_named(events):
    beacon = events["EVENT.DROWNING_BEACON"]
    assert "Glowwater Potion" in beacon.choices[0].outcome
    assert beacon.choices[1].outcome == "Lose 13 Max HP and obtain Fresnel Lens."


def test_colossal_flower_costs_are_cumulative_and_prizes_are_alternatives(events):
    flower = events["EVENT.COLOSSAL_FLOWER"]
    assert "11 unblockable damage in total" in flower.choices[2].outcome
    assert "135 Gold" in flower.choices[2].outcome
    assert "18 total damage" in flower.choices[3].outcome
    assert "not cumulative rewards" in flower.notes


def test_conveyor_preserves_conditional_free_dish_and_observe_timing(events):
    conveyor = events["EVENT.ENDLESS_CONVEYOR"]
    choices = {c.option: c.outcome for c in conveyor.choices}
    assert "before buying" in choices["Observe the Chef"]
    assert "40 Gold" in choices["Caviar"]
    assert "does not charge" in choices["Golden Fysh"]
    assert "at least 40 Gold even for Golden Fysh" in conveyor.notes
    assert "fifth offered dish" in conveyor.notes


def test_philosophers_offers_three_separate_rarity_rewards(events):
    outcome = events["EVENT.COLORFUL_PHILOSOPHERS"].choices[0].outcome
    assert "one Common, one Uncommon and one Rare card reward" in outcome
    assert "each with 3 choices" in outcome
