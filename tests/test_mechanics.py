"""Exact-build mechanics must not leak through history or stale translations."""
import json
from pathlib import Path

import pytest

from sts2 import knowledge, localize
from sts2.mechanics import (
    apply_card_profile,
    mechanics_fingerprint,
    overlay_matches,
    read_profiles,
    select_game_version,
)
from sts2.models import Card

DATA = Path(__file__).parents[1] / "sts2/data"


@pytest.fixture
def profiles():
    return read_profiles(DATA / "mechanics.json")


def test_main_mechanics_are_separate_from_beta_reference_catalog():
    main = knowledge.KnowledgeBase(game_version="v0.107.1")
    reference = knowledge.KnowledgeBase(game_version="")
    main_star = main.get_card_by_id("CARD.GUIDING_STAR")
    beta_star = reference.get_card_by_id("CARD.GUIDING_STAR")
    assert (main_star.star_cost, beta_star.star_cost) == ("2", "1")
    assert "next turn" not in main_star.description.lower()
    assert "next turn" in beta_star.description.lower()
    assert main.get_card_by_id("CARD.OUTBREAK").type == "Power"
    assert main.get_card_by_id("CARD.ALIGNMENT").star_cost == "3"
    assert main.get_card_by_id("CARD.EXPECT_A_FIGHT").cost_upgraded == "1"
    assert main.get_card_by_id("CARD.WELL_LAID_PLANS").sp_only
    assert not main.mechanics_status()["complete"]


def test_history_uses_its_version_without_changing_live_card_objects():
    main = knowledge.KnowledgeBase(game_version="v0.107.1")
    card = main.get_card_by_id("CARD.EXPECT_A_FIGHT")
    original = card.model_dump()
    beta = main.card_for_version(card.id, "v0.111.0")
    assert "Block" in beta.description
    assert beta.mechanics_version == ""
    assert main.get_card_by_id(card.id).model_dump() == original
    assert main.analyze_deck([card.id], game_version="v0.111.0")["unverified_mechanics"] == 1
    assert main.analyze_deck([card.id])["unverified_mechanics"] == 0
    assert main.card_for_version("CARD.UNKNOWN", "v0.111.0") is None


def test_mod_mechanics_are_never_replaced(profiles):
    card = Card(id="CARD.GUIDING_STAR", name="Mod card", character="Regent", cost="0",
                type="Skill", rarity="Rare", source="mod", description="Mod effect")
    assert apply_card_profile(card, profiles["v0.107.1"]) is card


@pytest.mark.parametrize("commit,expected", [("59260271", "v0.107.1"), ("unknown", ""), (None, "")])
def test_auto_selection_checks_installed_commit(tmp_path, profiles, commit, expected):
    release = {"version": "v0.107.1"}
    if commit is not None:
        release["commit"] = commit
    (tmp_path / "release_info.json").write_text(json.dumps(release), encoding="utf-8")
    assert select_game_version(tmp_path, profiles) == expected


def test_unknown_and_absent_installation_stay_unverified(tmp_path, profiles):
    assert select_game_version(tmp_path, profiles) == ""
    (tmp_path / "release_info.json").write_text('{"version":"v0.999.0"}', encoding="utf-8")
    assert select_game_version(tmp_path, profiles) == "v0.999.0"
    assert knowledge.KnowledgeBase(game_version="v0.999.0").mechanics_status()["reviewed_cards"] == 0


def test_invalid_profile_cannot_partially_apply(tmp_path, monkeypatch):
    (tmp_path / "mechanics.json").write_text('{"schema_version":999,"profiles":[]}', encoding="utf-8")
    with pytest.raises(ValueError):
        read_profiles(tmp_path / "mechanics.json")
    monkeypatch.setattr(knowledge, "DATA_DIR", tmp_path)
    loaded = knowledge.KnowledgeBase(game_version="v0.107.1")
    assert loaded.mechanics_profiles == {}
    assert read_profiles(tmp_path / "absent.json") == {}


@pytest.mark.parametrize("change", ["duplicate", "alias", "complete"])
def test_profile_rejects_ambiguous_or_unearned_claims(tmp_path, change):
    data = json.loads((DATA / "mechanics.json").read_text(encoding="utf-8"))
    profile = data["profiles"][0]
    if change == "duplicate":
        data["profiles"].append(profile)
    elif change == "alias":
        profile["cards"]["CARD.CALTROPS_EVENT"] = next(iter(profile["cards"].values()))
    else:
        profile["complete"] = True
    path = tmp_path / "mechanics.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        read_profiles(path)


def test_fingerprint_covers_mechanics_and_ignores_display_names():
    record = {"description": "Draw 2 cards.", "cost": "1"}
    token = mechanics_fingerprint(record)
    assert mechanics_fingerprint({**record, "name": "Localized", "fetched_at": "later"}) == token
    for change in ({"description": "Draw 2 cards next turn."}, {"cost": "0"},
                   {"star_cost": "2"}, {"no_upgrade": True}, {"keywords": ["Exhaust"]}):
        assert mechanics_fingerprint({**record, **change}) != token
    entry = {"_mechanics_fingerprint": token}
    assert overlay_matches(entry, record, {"game_version": "v0.107.1"}, "v0.107.1")
    assert not overlay_matches(entry, record, {"game_version": "v0.111.0"}, "v0.107.1")
    assert not overlay_matches(entry, record, None, "")
    assert not overlay_matches({}, record, {"game_version": ""}, "")


def test_stale_translation_keeps_names_and_current_english_effect(monkeypatch):
    from sts2 import i18n
    main = knowledge.KnowledgeBase(game_version="v0.107.1")
    card = main.get_card_by_id("CARD.GUIDING_STAR")
    token = mechanics_fingerprint(card.model_dump())
    overlay = {"_meta": {"game_version": "v0.107.1"}, "cards": {
        card.id: {"name": "Stern", "description": "Localized main effect",
                  "_mechanics_fingerprint": token}}}
    monkeypatch.setattr(i18n, "load_content_overlay", lambda _: overlay)
    localized = knowledge.KnowledgeBase(language="de", game_version="v0.107.1")
    assert localized.get_card_by_id(card.id).description == "Localized main effect"
    assert localized.card_text_en(localized.get_card_by_id(card.id)) == card.description
    # Same ID, different version/cost/timing: preserve the correct English.
    beta = knowledge.KnowledgeBase(language="de", game_version="v0.111.0")
    assert beta.get_card_by_id(card.id).name == "Stern"
    assert beta.get_card_by_id(card.id).description != "Localized main effect"
    assert beta.overlay_descriptions_skipped == 1
    overlay["_meta"]["game_version"] = "v0.111.0"
    assert knowledge.KnowledgeBase(language="de", game_version="v0.111.0").overlay_descriptions_skipped == 1


@pytest.mark.parametrize("shipped", ["Deal 6 damage to ALL enemies.",
                                     "Deal 6 damage. Lose 3 Focus this turn.",
                                     "Next turn, deal 6 damage."])
def test_strict_alignment_does_not_erase_target_timing_or_extra_effect(shipped):
    assert localize.extract_english("Deal {Damage} damage.", shipped, strict=True) is None
    assert localize.extract_english("Deal {Damage} damage.", "Deal 6 damage", strict=True) is not None


@pytest.mark.asyncio
async def test_compatibility_explanation_is_visible(client):
    response = await client.get("/settings")
    assert response.status_code == 200
    assert 'id="game-compatibility"' in response.text
    assert "Beta compatibility has not been verified" in response.text


def test_foreign_overlay_cannot_replace_version_specific_rename(monkeypatch):
    from sts2 import i18n

    monkeypatch.setattr(i18n, "load_content_overlay", lambda _: {
        "_meta": {"game_version": "v0.111.0"},
        "cards": {"CARD.SCARE": {"name": "Sidestep", "description": "Wrong branch"}}})
    main = knowledge.KnowledgeBase(language="de", game_version="v0.107.1")
    assert main.get_card_by_id("CARD.SCARE").name == "Scare"
    assert main.get_card_by_id("CARD.SCARE").description == "Apply 1 Weak to all enemies. Exhaust."
