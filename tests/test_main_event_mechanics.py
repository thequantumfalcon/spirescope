"""Reviewed event handlers replace speculative reference options for main only."""
import hashlib
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import apply_event_profile, read_profiles
from sts2.models import Event

ROOT = Path(__file__).parents[1]


def test_event_review_accounts_for_every_expected_id_without_claiming_completion():
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-event-mechanics.json").read_text(encoding="utf-8"))
    baseline = json.loads((ROOT / "docs/game-baselines/v0.107.1.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    reviewed, unreviewed = set(proof["reviewed_ids"]), set(proof["unreviewed_ids"])
    assert reviewed == set(raw["events"]) and not reviewed & unreviewed
    assert reviewed | unreviewed == set(baseline["expected_catalog_ids"]["events"])
    assert not proof["complete"]
    for identifier, record in raw["events"].items():
        digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]


def test_main_event_options_include_repetition_and_actual_rewards():
    kb = KnowledgeBase(game_version="v0.107.1")
    events = {event.id: event for event in kb.events}
    baths = events["EVENT.ABYSSAL_BATHS"]
    assert [c.option for c in baths.choices] == ["Abstain", "Immerse", "Linger", "Exit Baths"]
    assert "4 damage" in baths.choices[2].outcome and "1 more damage" in baths.choices[2].outcome
    assert "can kill you" in baths.notes
    bugslayer = events["EVENT.BUGSLAYER"]
    assert [c.outcome for c in bugslayer.choices] == ["Add Exterminate to your deck.", "Add Squash to your deck."]
    assert "do not start a combat" in bugslayer.notes
    leech = events["EVENT.BRAIN_LEECH"]
    assert "3 choices" in leech.choices[1].outcome
    assert "cannot be canceled" in leech.choices[0].outcome
    assert all(not c.recommendation for event in events.values()
               if event.mechanics_version for c in event.choices)


def test_event_eligibility_and_coop_costs_are_not_guessed():
    kb = KnowledgeBase(game_version="v0.107.1")
    events = {event.id: event for event in kb.events}
    dummy = events["EVENT.BATTLEWORN_DUMMY"]
    assert dummy.is_shared and "HP scales in multiplayer" in dummy.notes
    assert "up to 2 random upgradeable" in dummy.choices[1].outcome
    assert "more than 5 current HP" in events["EVENT.TRASH_HEAP"].availability_note
    assert "still costs 8" in events["EVENT.TRASH_HEAP"].availability_note
    assert "removable Basic" in events["EVENT.AMALGAMATOR"].availability_note
    assert "Byrdonis Egg" in events["EVENT.BYRDONIS_NEST"].availability_note


def test_event_profile_preserves_reference_and_mod_records():
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    reference = next(e for e in KnowledgeBase(game_version="v0.111.0").events if e.id == "EVENT.BUGSLAYER")
    assert reference.mechanics_version == ""
    assert "Combat encounter" in reference.choices[0].outcome
    main = apply_event_profile(reference, profile)
    assert main is not reference and main.mechanics_version == "v0.107.1"
    mod = reference.model_copy(update={"source": "mod"})
    assert apply_event_profile(mod, profile) is mod
    unknown = Event(id="EVENT.UNKNOWN", name="Unknown")
    assert apply_event_profile(unknown, profile) is unknown


@pytest.mark.asyncio
async def test_events_page_shows_reviewed_choices_and_labels_reference_rows(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    with patch("sts2.app.kb", kb):
        response = await client.get("/events")
    assert response.status_code == 200
    assert "Options checked for v0.107.1" in response.text
    assert "Add Exterminate to your deck" in response.text
    assert "The first Linger deals 4 damage" in response.text
    assert "Reference options; not verified" in response.text
    assert "Immerse is usually better" not in response.text
