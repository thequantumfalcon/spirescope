"""Independent main-build identities must resolve without discovery placeholders.

The fixture comes from reviewed native pool/registry declarations, not from the
catalog under test. It deliberately does not certify mechanics or all game modes.
"""
import json
from pathlib import Path

import pytest

from sts2.config import DATA_DIR
from sts2.knowledge import KnowledgeBase

BASELINE = json.loads((Path(__file__).parents[1]/'docs/game-baselines/v0.107.1.json')
                      .read_text(encoding='utf-8'))


@pytest.mark.parametrize('family', BASELINE['expected_catalog_ids'])
def test_reviewed_main_identities_are_present_in_bundled_catalog(family):
    records = json.loads((DATA_DIR/f'{family}.json').read_text(encoding='utf-8'))
    ids = [row['id'] for row in records]
    expected = BASELINE['expected_catalog_ids'][family]
    assert expected and len(expected) == len(set(expected))
    assert len(ids) == len(set(ids)), 'Catalog IDs must be unique'
    assert not set(expected)-set(ids), f'Missing {family}: {sorted(set(expected)-set(ids))}'


def test_native_monsters_and_encounters_have_separate_runtime_entries():
    kb = KnowledgeBase(language='en')
    for identifier in BASELINE['expected_catalog_ids']['enemies']:
        enemy = kb.get_enemy_by_id(identifier)
        assert enemy is not None and enemy.id == identifier
    monster = kb.get_enemy_by_id('MONSTER.AEONGLASS')
    encounter = kb.get_enemy_by_id('ENCOUNTER.AEONGLASS_BOSS')
    assert monster is not encounter


def test_registered_badges_have_reviewed_requirements_and_native_ids():
    kb = KnowledgeBase(language='en')
    for identifier in BASELINE['expected_catalog_ids']['badges']:
        badge = kb.get_badge_by_id(identifier)
        assert badge and badge.requirement and badge.mechanics_version == 'v0.107.1'
    assert kb.get_badge_by_id('BADGE.CCCCOMBO')
    assert kb.get_badge_by_id('BADGE.CCC_COMBO_MODEL') is None
    assert BASELINE['complete'] is False
