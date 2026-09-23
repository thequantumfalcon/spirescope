"""Regressions based on the installed game's SerializableRun schema."""
import json

import pytest

from sts2 import saves


@pytest.mark.parametrize("identity,expected", [
    ({"rng": {"seed": "NATIVE"}}, "NATIVE"),
    ({"seed": "LEGACY"}, "LEGACY"),
    ({"rng": {"seed": "SAME"}, "seed": "SAME"}, "SAME"),
    ({"rng": {"seed": "CURRENT"}, "seed": "OLD"}, ""),
    ({"rng": []}, ""),
    ({"rng": {"seed": {"value": "NO"}}}, ""),
    ({"rng": {"seed": 123}}, ""),
    ({"rng": {"seed": "bad\nseed"}}, ""),
    ({"rng": {"seed": "x" * 257}}, ""),
], ids=["native", "legacy", "agreement", "conflict", "malformed-rng", "object", "number", "control", "oversized"])
def test_current_save_seed_uses_native_nesting_without_coercion(tmp_path, monkeypatch, identity, expected):
    payload = {"schema_version": 16, "players": [{"id": 1, "character_id": "CHARACTER.IRONCLAD"}],
               "start_time": 100, **identity}
    (tmp_path / "current_run.save").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(saves, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(saves, "SAVE_DIRS", [tmp_path])
    assert saves.get_current_run().seed == expected


@pytest.mark.asyncio
async def test_native_seed_allows_matching_log_without_overwriting_save(tmp_path, monkeypatch):
    from sts2 import app, routes

    payload = {"schema_version": 16, "rng": {"seed": "NATIVE"}, "ascension": 0,
               "players": [{"id": 1, "character_id": "CHARACTER.IRONCLAD", "current_hp": 63,
                            "max_hp": 80, "gold": 107, "deck": [{"id": "CARD.BASH"}]}]}
    (tmp_path / "current_run.save").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(saves, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(saves, "SAVE_DIRS", [tmp_path])
    monkeypatch.setattr(app, "_log_run_state", {"active": True, "seed": "NATIVE", "character": "Ironclad",
                        "log_ascension": 0, "act": 1, "cards_played_by_player": {1: ["CARD.BASH"]},
                        "extra_turns_by_player": {1: 0}, "encounters_won": []})

    async def poll():
        return None

    monkeypatch.setattr(app, "_poll_game_log_once", poll)
    merged = await routes._compute_live_run(None)
    assert merged.telemetry_status == "matched"
    assert merged.current_hp == 63 and merged.gold == 107
    assert merged.deck == ["CARD.BASH"]
    assert merged.cards_played == ["CARD.BASH"]
    payload["seed"] = "CONFLICT"
    (tmp_path / "current_run.save").write_text(json.dumps(payload), encoding="utf-8")
    rejected = await routes._compute_live_run(None)
    assert rejected.telemetry_status == "unavailable"
    assert rejected.cards_played == []
