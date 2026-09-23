"""The audit must distinguish evidence from apparent catalog completeness."""
import importlib.util
import json
import struct
from pathlib import Path

import pytest

from tests.test_localize import _build_pck

spec = importlib.util.spec_from_file_location(
    "audit_game_content", Path(__file__).parents[1] / "scripts/audit_game_content.py")
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def test_nested_options_are_not_events_and_relic_variants_remain_distinct():
    assert audit.native_ids({
        "ROOM.title": "Room", "ROOM.pages.ALL.options.LEAVE.title": "Leave",
        "ROOM.DISHES.FOOD.title": "Food",
    }, "title") == {"ROOM": "Room"}
    assert set(audit.native_ids({
        "SEA_GLASS.DEFECT.title": "Glass", "SEA_GLASS.SILENT.title": "Glass",
    }, "title", variants=True)) == {"SEA_GLASS.DEFECT", "SEA_GLASS.SILENT"}


def test_aliases_are_unverified_and_helpers_do_not_inflate_counts():
    result = audit.compare({
        "cards": {"CLASH.title": "Clash", "BASH.title": "Bash",
                  "MOCK_SKILL.title": "Test", "FUTURE.title": "TODO"},
    }, {"cards": [{"id": "CARD.CLASH_EVENT"}, {"id": "CARD.BASH"}]})["cards"]
    assert result["candidate_entries"] == 2
    assert result["exact_id_matches"] == 1
    assert result["unmatched_native_ids"] == ["CLASH"]
    assert result["possible_aliases_needing_runtime_verification"] == {"CLASH": ["CLASH_EVENT"]}
    assert len(result["excluded_entries"]) == 2


def test_monsters_and_encounters_are_separate_and_badge_tiers_are_one_id():
    results = audit.compare({
        "monsters": {"EYE.name": "Eye"}, "encounters": {"EYE.title": "Eye"},
        "badges": {"ELITE.bronzeTitle": "One", "ELITE.goldTitle": "Three", "PERFECT.title": "Perfect"},
    }, {"enemies": [{"id": "MONSTER.EYE"}], "badges": [{"id": "BADGE.ELITE"}]})
    assert results["monsters"]["exact_id_matches"] == 1
    assert results["encounters"]["exact_id_matches"] == 0
    assert results["badges"]["candidate_entries"] == 2
    assert results["badges"]["unmatched_native_ids"] == ["PERFECT"]
    assert not results["epochs"]["table_present"]


@pytest.mark.parametrize("relative", [False, True])
def test_archive_audit_is_read_only_and_does_not_export_game_text(tmp_path, relative):
    game = _build_pck(tmp_path, {
        "localization/eng/cards.json": json.dumps({"BASH.title": "Private title"}).encode(),
        "localization/ind/cards.json": b'{}',
    }, rel_base=relative)
    (game / "release_info.json").write_text('{"version":"v0.111.0","branch":"beta"}')
    data = tmp_path / "data"
    data.mkdir()
    for name in audit.FIELDS:
        (data / f"{name}.json").write_text('[{"id":"CARD.BASH"}]' if name == "cards" else '[]')
    before = {p: p.read_bytes() for p in tmp_path.rglob('*') if p.is_file()}
    report = audit.audit(game, data)
    assert report["game_release"]["version"] == "v0.111.0"
    assert report["native_languages"] == ["eng", "ind"]
    assert report["families"]["cards"]["exact_id_matches"] == 1
    assert report["complete"] is False
    assert "Private title" not in json.dumps(report)
    assert {p: p.read_bytes() for p in before} == before


def test_archive_rejects_out_of_bounds_tables(tmp_path):
    game = _build_pck(tmp_path, {"localization/eng/cards.json": b'{}'})
    pack = game / "SlayTheSpire2.pck"
    raw = bytearray(pack.read_bytes())
    directory, = struct.unpack_from('<Q', raw, 32)
    length, = struct.unpack_from('<I', raw, directory + 4)
    struct.pack_into('<Q', raw, directory + 8 + length, len(raw) + 100)
    pack.write_bytes(raw)
    with pytest.raises(ValueError, match='outside pack'):
        audit.read_pack(pack)


def test_archive_rejects_oversized_table_before_reading(tmp_path, monkeypatch):
    game = _build_pck(tmp_path, {"localization/eng/cards.json": b'{"BASH.title":"Bash"}'})
    monkeypatch.setattr(audit, 'MAX_TABLE_BYTES', 2)
    with pytest.raises(ValueError, match='size limit'):
        audit.read_pack(game / 'SlayTheSpire2.pck')


def test_cli_refuses_to_write_into_game_or_catalog(tmp_path, monkeypatch):
    monkeypatch.setattr('sys.argv', ["audit", "--game-dir", str(tmp_path),
        "--data-dir", str(tmp_path / "data"), "--output", str(tmp_path / "release_info.json")])
    with pytest.raises(SystemExit) as exc:
        audit.main()
    assert exc.value.code == 1
    assert not (tmp_path / "release_info.json").exists()
