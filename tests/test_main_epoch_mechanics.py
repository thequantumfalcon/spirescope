"""Main timeline facts distinguish obtained epochs, rewards and future placeholders."""
import hashlib
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import apply_epoch_profile, read_profiles
from sts2.models import Epoch, PlayerProgress

ROOT = Path(__file__).parents[1]


def test_main_epoch_profile_matches_independently_registered_ids():
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-epoch-mechanics.json").read_text(encoding="utf-8"))
    raw = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    assert set(raw["epochs"]) == set(proof["registered_ids"])
    assert len(raw["epochs"]) == 57 and not proof["complete"]
    kb = KnowledgeBase(game_version="v0.107.1")
    assert kb.mechanics_status()["reviewed_epochs"] == 57
    for identifier, record in raw["epochs"].items():
        digest = hashlib.sha256(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]
        epoch = kb.get_epoch_by_id(identifier)
        assert epoch.requirement and epoch.unlocks and epoch.mechanics_version == "v0.107.1"


def test_daily_and_ascension_requirements_follow_native_conditions():
    kb = KnowledgeBase(game_version="v0.107.1")
    daily = kb.get_epoch_by_id("DAILY_RUN_EPOCH")
    assert daily.requirement == "Win a Standard run after playing all five characters."
    assert "win with each character is not required" in daily.mechanics_note
    assert "exactly Ascension 1" in kb.get_epoch_by_id("IRONCLAD7_EPOCH").requirement
    assert "Reveal the Neow epoch" in kb.get_epoch_by_id("SILENT1_EPOCH").requirement
    assert "15 bosses in total" in kb.get_epoch_by_id("DEFECT6_EPOCH").requirement
    assert KnowledgeBase(game_version="v0.111.0").get_epoch_by_id(daily.id).mechanics_version == ""


def test_score_sequence_and_previously_blank_rewards():
    kb = KnowledgeBase(game_version="v0.107.1")
    colorless = kb.get_epoch_by_id("COLORLESS4_EPOCH")
    assert colorless.unlocks == ["Alchemize", "Nostalgia", "Scrawl"]
    assert "12 of 18 (2,100 points for this step)" in colorless.requirement
    assert "at most one unlock per completed run" in colorless.mechanics_note
    assert kb.get_epoch_by_id("RELIC5_EPOCH").unlocks == ["Tiny Mailbox", "Joss Paper", "Beating Remnant"]
    assert kb.get_epoch_by_id("EVENT3_EPOCH").unlocks == ["Colorful Philosophers"]
    for identifier in ("ACT2_B_EPOCH", "ACT3_B_EPOCH"):
        epoch = kb.get_epoch_by_id(identifier)
        assert epoch.status == "placeholder" and epoch.unlock_type == "placeholder"
        assert "no playable alternate Act" in epoch.unlocks[0]


def test_main_profile_does_not_override_mod_or_unknown_epochs():
    profile = read_profiles(ROOT / "sts2/data/mechanics.json")["v0.107.1"]
    mod = Epoch(id="DAILY_RUN_EPOCH", name="Mod rules", source="mod")
    unknown = Epoch(id="FUTURE_EPOCH", name="Future")
    assert apply_epoch_profile(mod, profile) is mod
    assert apply_epoch_profile(unknown, profile) is unknown
    assert apply_epoch_profile(mod, None) is mod


@pytest.mark.asyncio
async def test_epoch_catalog_is_available_without_save_and_does_not_invent_progress(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    with patch("sts2.app.kb", kb), patch("sts2.app._get_progress", new=AsyncMock(return_value=None)):
        response = await client.get("/epochs")
    assert response.status_code == 200
    assert "No save data found" in response.text and "Slumber" in response.text
    assert "2,100 points for this step" in response.text
    assert "Placeholder reward" in response.text
    assert "Requirements and rewards checked for v0.107.1" in response.text
    assert "collection-bar-label" not in response.text


@pytest.mark.asyncio
async def test_revealed_placeholder_keeps_actual_timeline_progress(client):
    kb = KnowledgeBase(game_version="v0.107.1")
    progress = PlayerProgress(epochs=[{"id": "ACT3_B_EPOCH", "state": "revealed", "obtain_date": 0}])
    with patch("sts2.app.kb", kb), patch("sts2.app._get_progress", new=AsyncMock(return_value=progress)):
        response = await client.get("/epochs?category=act")
    assert response.status_code == 200 and "1/3" in response.text
    assert "no playable alternate Act 3 in v0.107.1" in response.text
