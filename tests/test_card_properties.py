"""Native per-copy values survive parsing, editing and versioned analysis."""
import json

import pytest

from sts2.card_properties import CardProperties, card_copy, read_card_properties
from sts2.deck_instances import DeckInstance, instances_from_run
from sts2.knowledge import KnowledgeBase


def native(**values):
    return {"ints": [{"name": name, "value": value} for name, value in values.items()]}


@pytest.mark.parametrize("raw", [[], {"ints": "bad"}, {"ints": [1]},
    native(CurrentBlock=True), native(CurrentBlock=-1), native(CurrentBlock=2147483648),
    {"ints": [{"name": "CurrentBlock", "value": 1}] * 2}, {"ints": [{}]}])
def test_bad_saved_properties_do_not_become_trusted_values(raw):
    assert read_card_properties(raw) is None


def test_unsupported_properties_are_flagged_without_retaining_private_strings():
    parsed = read_card_properties({**native(CurrentBlock=4, IncreasedBlock=3),
                                   "strings": [{"name": "Anything", "value": "private"}]})
    assert parsed.unmodeled
    assert "private" not in parsed.model_dump_json()
    with pytest.raises(ValueError):
        CardProperties(ints={"Anything": 1})


def test_two_permanently_growing_copies_keep_distinct_values_and_upgrade_increments():
    kb = KnowledgeBase(game_version="v0.107.1")
    values = [read_card_properties(native(CurrentBlock=10, IncreasedBlock=9)),
              read_card_properties(native(CurrentBlock=17, IncreasedBlock=16)),
              read_card_properties(native(CurrentDamage=25, IncreasedDamage=12))]
    result = kb.analyze_deck(["CARD.GENETIC_ALGORITHM"] * 2 + ["CARD.THE_SCYTHE"],
                             [False, True, True], properties=values)
    texts = [copy["description"] for copy in result["copy_details"]]
    assert texts == [
        "Gain 10 Block. Permanently increase this card's Block by 3. Exhaust.",
        "Gain 17 Block. Permanently increase this card's Block by 4. Exhaust.",
        "Deal 25 damage. Permanently increase this card's damage by 5. Exhaust.",
    ]
    assert result["unmodeled_copies"] == result["unknown_mechanics"] == 0
    assert not any("No Block" in warning for warning in result["weaknesses"])
    assert kb.get_card_by_id("CARD.GENETIC_ALGORITHM").description.startswith("Starts at 1")


@pytest.mark.parametrize("kind,rider,type_name,expected", [
    (1, 1, "Attack", "Apply 2 Weak and 2 Vulnerable"),
    (1, 2, "Attack", "Deal 12 damage 3 times"),
    (1, 3, "Attack", "subsequent card"),
    (2, 4, "Skill", "Gain 2 Energy"),
    (2, 5, "Skill", "Draw 3 cards"),
    (2, 6, "Skill", "free this turn"),
    (3, 7, "Power", "Gain 2 Strength and 2 Dexterity"),
    (3, 8, "Power", "cost 1 less Energy"),
    (3, 9, "Power", "At the end of combat"),
])
def test_all_nine_tinker_time_choices(kind, rider, type_name, expected):
    kb = KnowledgeBase(game_version="v0.107.1")
    properties = read_card_properties(native(TinkerTimeType=kind, TinkerTimeRider=rider))
    result = kb.analyze_deck(["CARD.MAD_SCIENCE"], [True], properties=[properties])
    copy = result["copy_details"][0]
    assert copy["type"] == type_name
    assert copy["description"].startswith("Innate.")
    assert expected in copy["description"]
    assert result["unmodeled_copies"] == 0
    assert result[{"Attack": "attacks", "Skill": "skills", "Power": "powers"}[type_name]] == 1


def test_missing_conflicting_and_foreign_build_values_are_not_guessed():
    kb = KnowledgeBase(game_version="v0.107.1")
    missing = kb.analyze_deck(["CARD.MAD_SCIENCE", "CARD.GENETIC_ALGORITHM"])
    assert missing["unmodeled_copies"] == 2
    assert missing["unknown_mechanics"] == 2
    assert any(text.startswith("Block generation unknown") for text in missing["weaknesses"])
    conflict = read_card_properties(native(CurrentBlock=99, IncreasedBlock=3))
    card = kb.get_card_by_id("CARD.GENETIC_ALGORITHM")
    assert card_copy(card, conflict).description == ""
    valid = read_card_properties(native(CurrentBlock=4, IncreasedBlock=3))
    assert card_copy(card.model_copy(update={"mechanics_version": "v0.111.0"}), valid).description == ""
    invalid_choice = read_card_properties(native(TinkerTimeType=1, TinkerTimeRider=7))
    assert card_copy(kb.get_card_by_id("CARD.MAD_SCIENCE"), invalid_choice).description == ""


def test_native_save_properties_survive_editor_round_trip(tmp_path, monkeypatch):
    from sts2 import saves

    payload = {"schema_version": 16, "rng": {"seed": "SYNTHETIC"},
               "players": [{"id": 1, "character_id": "CHARACTER.DEFECT", "deck": [
                   {"id": "CARD.GENETIC_ALGORITHM", "props": native(CurrentBlock=7, IncreasedBlock=6)},
                   {"id": "CARD.GENETIC_ALGORITHM", "current_upgrade_level": 1,
                    "props": native(CurrentBlock=9, IncreasedBlock=8)}]}]}
    (tmp_path / "current_run.save").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(saves, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(saves, "SAVE_DIRS", [tmp_path])
    run = saves.get_current_run()
    copies = [DeckInstance.model_validate(item) for item in instances_from_run(run)]
    assert [copy.properties.ints["CurrentBlock"] for copy in copies] == [7, 9]
    assert [copy.upgrade_level for copy in copies] == [0, 1]


def test_upgrades_use_their_own_keyword_mentions():
    kb = KnowledgeBase(game_version="v0.107.1")
    base = dict(kb.analyze_deck(["CARD.SCARE"], [False])["top_keywords"])
    upgraded = dict(kb.analyze_deck(["CARD.SCARE"], [True])["top_keywords"])
    assert "Exhaust" in base and "Exhaust" not in upgraded
    assert "Weak" in base and "Weak" in upgraded


@pytest.mark.asyncio
async def test_editor_displays_saved_values_and_preserves_properties(client):
    from sts2 import app

    instances = [DeckInstance(card_id="CARD.MAD_SCIENCE", upgrade_level=1,
                  properties=CardProperties(ints={"TinkerTimeType": 2, "TinkerTimeRider": 5})).model_dump()]
    response = await client.post("/deck/analyze", data={"csrf_token": app.generate_csrf_token(),
        "game_version": "v0.107.1", "instances": json.dumps(instances)})
    assert response.status_code == 200
    assert "Innate. Gain 8 Block. Draw 3 cards." in response.text
    assert "TinkerTimeRider" in response.text
