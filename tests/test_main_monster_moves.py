"""Act 1 monster move sets are build-qualified and scoped to the run's version."""
import hashlib
import json
from pathlib import Path

import pytest

from sts2.knowledge import KnowledgeBase
from sts2.mechanics import MonsterMove, MonsterMoves, read_profiles, render_monster_moves

ROOT = Path(__file__).parents[1]


def test_act1_monster_moves_match_stats_registry_and_record_hashes():
    proof = json.loads((ROOT / "docs/game-baselines/v0.107.1-monster-moves.json").read_text(encoding="utf-8"))
    registry = json.loads((ROOT / "docs/game-baselines/v0.107.1-model-registry.json").read_text(encoding="utf-8"))
    profile = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))["profiles"][0]
    hashes = {rec["model_id"]: rec["definition_sha256"] for rec in registry["records"].values()
              if rec["family"] == "Monsters" and rec.get("model_id")}
    assert set(profile["monster_moves"]) == set(proof["reviewed_ids"])
    assert len(profile["monster_moves"]) == 77
    assert len(proof["acts"]["ACT1"]) == 51 and len(proof["acts"]["ACT2"]) == 26
    assert set(profile["monster_moves"]) <= set(profile["monster_stats"])
    assert not proof["complete"]
    for identifier, record in profile["monster_moves"].items():
        assert record["definition_sha256"] == hashes[identifier]
        digest = hashlib.sha256(json.dumps(record, sort_keys=True, ensure_ascii=False,
                                          separators=(",", ":")).encode()).hexdigest()
        assert digest == proof["records"][identifier]["mechanics_record_sha256"]
        assert record["moves"] and record["pattern"]
        for move in record["moves"]:
            assert move["title"] and move["intent"] and move["effect"].endswith(".")


def test_enemy_moves_are_version_scoped():
    kb = KnowledgeBase(game_version="v0.107.1")
    nibbit = kb.get_enemy_by_id("MONSTER.NIBBIT")
    assert nibbit.mechanics_version == "v0.107.1"
    assert nibbit.patterns[0] == "Butt (Attack): 12 (13 at Ascension 9+) damage."
    assert any(line.startswith("Pattern: ") for line in nibbit.patterns)
    assert kb.mechanics_status()["reviewed_monster_moves"] == 77
    demon = kb.get_enemy_by_id("MONSTER.KNOWLEDGE_DEMON")
    assert demon.mechanics_version == "v0.107.1" and any("Ponder" in line for line in demon.patterns)
    other = KnowledgeBase(game_version="v0.111.0")
    assert other.get_enemy_by_id("MONSTER.NIBBIT").mechanics_version == ""
    assert other.mechanics_status()["reviewed_monster_moves"] == 0
    # Encounters keep their roster view; moves belong to monsters only.
    assert kb.get_enemy_by_id("ENCOUNTER.NIBBITS_NORMAL").roster_version == "v0.107.1"


def test_render_lists_moves_then_pattern_then_entry():
    facts = MonsterMoves(moves=[MonsterMove(state="A_MOVE", title="A", intent="Attack", effect="1 damage.")],
                         pattern="A every turn.", entry_effects="Gains X 1.",
                         definition_sha256="0" * 64, verification="native-review")
    assert render_monster_moves(facts) == ["A (Attack): 1 damage.", "Pattern: A every turn.", "On entering combat: Gains X 1."]


def test_profile_rejects_moves_without_reviewed_stats(tmp_path):
    catalog = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))
    profile = catalog["profiles"][0]
    profile["monster_moves"] = {"MONSTER.NOT_REVIEWED": profile["monster_moves"]["MONSTER.NIBBIT"]}
    broken = tmp_path / "mechanics.json"
    broken.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError, match="reviewed monster stats"):
        read_profiles(broken)


@pytest.mark.asyncio
async def test_enemy_page_shows_reviewed_moves(client, monkeypatch):
    from sts2 import app

    monkeypatch.setattr(app, "kb", KnowledgeBase(game_version="v0.107.1"))
    response = await client.get("/enemies/MONSTER.NIBBIT")
    assert response.status_code == 200
    assert "Patterns checked for v0.107.1" in response.text
    assert "8+ and 9+ are the Tough Enemies and Deadly Enemies levels" in response.text
    assert "Pattern: Alone it opens with Butt." in response.text
    assert "Reference patterns and strategy" not in response.text
