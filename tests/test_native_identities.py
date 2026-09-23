"""Native IDs must join catalog, history, overlays and old public identifiers."""
import json

import pytest

from sts2.aggregate import compute_aggregate_stats
from sts2.analytics import compute_analytics, compute_era_split
from sts2.identities import (
    LEGACY_TO_NATIVE,
    canonical_id,
    canonical_records,
    canonical_run,
    identity_index,
)
from sts2.knowledge import KnowledgeBase
from sts2.models import RunFloor, RunHistory


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(language="en")


@pytest.mark.parametrize("legacy,native", LEGACY_TO_NATIVE.items())
def test_old_links_and_native_ids_resolve_to_one_catalog_record(kb, legacy, native):
    lookup = {"CARD": kb.get_card_by_id, "RELIC": kb.get_relic_by_id,
              "POTION": kb._potions_by_id.get, "MONSTER": kb.get_enemy_by_id}[native.split('.')[0]]
    current = lookup(native)
    assert current is not None
    assert current.id == native
    assert lookup(legacy) is current
    family = {"CARD":"cards", "RELIC":"relics", "POTION":"potions", "MONSTER":"enemies"}[native.split('.')[0]]
    assert sum(row.id in (legacy, native) for row in getattr(kb, family)) == 1


def test_identity_mapping_never_guesses_suffixes_or_rewrites_mod_ids():
    for identifier in ('CARD.APOTHEOSIS_EVENT', 'CARD.SOME_NEW_EVENT',
                       'mod:custom:CARD.CALTROPS_EVENT', 'ENCOUNTER.AEONGLASS_BOSS'):
        assert canonical_id(identifier) == identifier
    assert identity_index({'CARD.CALTROPS_EVENT': 'old'})['CARD.CALTROPS'] == 'old'
    both = identity_index({'CARD.CALTROPS_EVENT': 'old', 'CARD.CALTROPS': 'native'})
    assert both['CARD.CALTROPS_EVENT'] == both['CARD.CALTROPS'] == 'native'


def run(identifier, build='v0.107.1'):
    return RunHistory(id=identifier, character='Silent', win=True, build_id=build,
                      deck=[identifier], deck_upgrades=[1], deck_enchantments=['ENCHANTMENT.SWIFT'],
                      relics=['RELIC.ANCHOR_FAKE'],
                      floors=[RunFloor(floor=1, cards_offered=[identifier], cards_picked=[identifier])])


def test_statistics_join_old_and_native_ids_without_mutating_history():
    old, native = run('CARD.CALTROPS_EVENT'), run('CARD.CALTROPS')
    original = [r.model_dump() for r in (old, native)]
    stats = compute_analytics([old, native])
    ranked = next(r for r in stats['card_rankings'] if r['id'] == 'CARD.CALTROPS')
    assert ranked['appearances'] == 2
    assert not any(r['id'] == 'CARD.CALTROPS_EVENT' for r in stats['card_rankings'])
    aggregate = compute_aggregate_stats([old, native])
    assert aggregate['card_win_rates'] == {'CARD.CALTROPS': {'wins':2, 'total':2}}
    assert aggregate['card_pick_rates'] == {'CARD.CALTROPS': {'picked':2, 'offered':2}}
    projected = canonical_run(old)
    assert projected.deck_upgrades == old.deck_upgrades
    assert projected.deck_enchantments == old.deck_enchantments
    assert projected.floors[0].card_picked == 'CARD.CALTROPS'
    assert [r.model_dump() for r in (old, native)] == original


def test_era_comparison_uses_aliases_before_partitioning(monkeypatch):
    from sts2 import patches
    monkeypatch.setattr(patches, 'era_of', lambda version: version)
    monkeypatch.setattr(patches, 'era_index', lambda version: {'before':0, 'after':1}.get(version, -1))
    runs = [run('CARD.CALTROPS_EVENT', 'before') for _ in range(10)]
    runs += [run('CARD.CALTROPS', 'after') for _ in range(10)]
    result = compute_era_split(runs, 'CARD.CALTROPS_EVENT', 'after')
    assert result['before']['n'] == result['after']['n'] == 10
    assert result['before']['pick_rate'] == result['after']['pick_rate'] == 100


def test_same_entity_in_two_spellings_counts_once_per_deck():
    item = run('CARD.CALTROPS')
    item.deck.append('CARD.CALTROPS_EVENT')
    assert compute_aggregate_stats([item])['card_win_rates']['CARD.CALTROPS']['total'] == 1


def test_refresh_merges_old_installed_id_with_native_source(tmp_path, monkeypatch):
    from sts2 import fetcher
    monkeypatch.setattr(fetcher, 'DATA_DIR', tmp_path)
    (tmp_path/'cards.json').write_text(json.dumps([
        {'id':'CARD.CALTROPS_EVENT', 'name':'Caltrops', 'character':'Event', 'cost':'1'}]))
    result = fetcher._merge_with_existing('cards.json', [
        {'id':'CARD.CALTROPS', 'name':'Caltrops', 'cost':'1', 'description':'Gain 3 Thorns.'}])
    assert len(result) == 1
    assert result[0]['id'] == 'CARD.CALTROPS'
    assert result[0]['character'] == 'Event'


def test_conflicting_alias_records_require_review():
    with pytest.raises(ValueError, match='Conflicting records'):
        canonical_records([{'id':'POTION.CLARITY', 'rarity':'Rare'},
                           {'id':'POTION.CLARITY_EXTRACT', 'rarity':'Common'}])


def test_old_content_overlay_can_address_corrected_native_id(monkeypatch):
    from sts2 import i18n
    monkeypatch.setattr(i18n, 'load_content_overlay', lambda code: {
        'cards': {'CARD.CALTROPS_EVENT': {'name':'Translated Caltrops', 'description':'Translated effect'}}})
    loaded = KnowledgeBase(language='de')
    card = loaded.get_card_by_id('CARD.CALTROPS')
    assert card.name == 'Translated Caltrops'
    assert loaded.card_text_en(card) != 'Translated effect'


def test_discovery_does_not_add_an_empty_alias_duplicate(monkeypatch):
    from sts2 import saves
    from sts2.models import PlayerProgress
    monkeypatch.setattr(saves, 'get_progress', lambda: PlayerProgress(
        discovered_cards=['CARD.CALTROPS_EVENT', 'CARD.CALTROPS']))
    loaded = KnowledgeBase(language='en')
    matches = [c for c in loaded.cards if canonical_id(c.id) == 'CARD.CALTROPS']
    assert len(matches) == 1
    assert matches[0].description


def test_native_event_monsters_are_distinct_and_observed_ids_resolve(kb):
    versions = [kb.get_enemy_by_id(f"MONSTER.BATTLE_FRIEND_V{v}") for v in (1, 2, 3)]
    assert [enemy.hp_range for enemy in versions] == ['75', '150', '300']
    assert all(enemy.type == 'event' and enemy.mechanics_version == 'v0.107.1'
               for enemy in versions)
    knight = kb.get_enemy_by_id('MONSTER.MYSTERIOUS_KNIGHT')
    assert knight and knight.id != kb.get_enemy_by_id('MONSTER.FLAIL_KNIGHT').id
    assert knight.type == 'event'
    assert kb.get_enemy_by_id('ENCOUNTER.MYSTERIOUS_KNIGHT_EVENT_ENCOUNTER') is not knight


def test_legacy_killer_id_joins_death_statistics_without_mutating_run():
    item = run('CARD.CALTROPS')
    item.killed_by = 'BOSS.AEONGLASS'
    projected = canonical_run(item)
    assert projected.killed_by == 'MONSTER.AEONGLASS'
    assert item.killed_by == 'BOSS.AEONGLASS'


def test_badges_use_actual_serialized_ids_and_catalog_names(kb):
    assert kb.get_badge_by_id('BADGE.CCCCOMBO').name == 'C-C-C-Combo'
    assert kb.id_to_name('BADGE.ILIKESHINY') == 'I Like Shiny'
    assert kb.get_badge_by_id('BADGE.TABLET').requires_win
    assert kb.get_badge_by_id('BADGE.HEALER').mp_only
    assert all(badge.requirement and badge.mechanics_version for badge in kb.badges)
    # These class/localization names are not the serialized badge identities.
    assert kb.get_badge_by_id('BADGE.CCC_COMBO_MODEL') is None
    assert kb.get_badge_by_id('BADGE.WHOMPER') is None


def test_custom_card_does_not_promise_one_variant_to_every_deck(kb):
    card = kb.get_card_by_id('CARD.MAD_SCIENCE')
    assert card.type == 'Variable'
    assert 'depend on your choices' in card.description
    assert 'Powers cost 1 Energy less' not in card.description
