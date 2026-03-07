"""Tests for the scraper module."""
import pytest
from sts2.scraper import (
    _clean_description,
    _extract_json_objects,
    _extract_keywords,
    _wiki_id_to_game_id,
    _merge_with_existing,
)


class TestCleanDescription:
    def test_strip_gold_tags(self):
        assert _clean_description("[gold]Block[/gold]") == "Block"

    def test_strip_blue_tags(self):
        assert _clean_description("Gain [blue]5[/blue] Block") == "Gain 5 Block"

    def test_strip_energy_tags(self):
        assert _clean_description("[energy:1] Deal 10 damage") == "Deal 10 damage"

    def test_strip_star_tags(self):
        assert _clean_description("[star:1] Draw 2") == "Draw 2"

    def test_strip_multiple_tags(self):
        text = "Gain [gold]3[/gold] [blue]Strength[/blue]"
        assert _clean_description(text) == "Gain 3 Strength"

    def test_no_tags(self):
        assert _clean_description("Plain text") == "Plain text"


class TestExtractJsonObjects:
    def test_extract_card(self):
        html = 'some stuff {"id":"bash","category":"CARD","name":"Bash"} more stuff'
        result = _extract_json_objects(html, "CARD")
        assert len(result) == 1
        assert result[0]["name"] == "Bash"

    def test_extract_relic(self):
        html = '{"id":"akabeko","category":"RELIC","name":"Akabeko"}'
        result = _extract_json_objects(html, "RELIC")
        assert len(result) == 1

    def test_no_match(self):
        html = '{"id":"x","category":"RELIC","name":"Y"}'
        result = _extract_json_objects(html, "CARD")
        assert len(result) == 0

    def test_invalid_json_skipped(self):
        html = '{"id":"x","category":"CARD" broken json {"id":"y","category":"CARD","name":"Y"}'
        result = _extract_json_objects(html, "CARD")
        assert len(result) == 1
        assert result[0]["name"] == "Y"


class TestWikiIdToGameId:
    def test_card_id(self):
        assert _wiki_id_to_game_id("bash-ironclad", "CARD") == "CARD.BASH"

    def test_multi_word_id(self):
        assert _wiki_id_to_game_id("iron-wave-ironclad", "CARD") == "CARD.IRON_WAVE"

    def test_no_character_suffix(self):
        assert _wiki_id_to_game_id("finesse", "CARD") == "CARD.FINESSE"


class TestExtractKeywords:
    def test_block(self):
        assert "Block" in _extract_keywords("Gain 5 Block.")

    def test_multiple(self):
        kws = _extract_keywords("Apply 3 Vulnerable. Draw 1 card.")
        assert "Vulnerable" in kws
        assert "Draw" in kws

    def test_none(self):
        assert _extract_keywords("Do something unique.") == []


class TestMergeWithExisting:
    def test_merge_new_over_old(self, tmp_path):
        import json
        from unittest.mock import patch

        existing = [{"id": "A", "val": 1}, {"id": "B", "val": 2}]
        new = [{"id": "A", "val": 10}, {"id": "C", "val": 3}]

        data_dir = tmp_path
        (data_dir / "test.json").write_text(json.dumps(existing))

        with patch("sts2.scraper.DATA_DIR", data_dir):
            merged = _merge_with_existing("test.json", new)

        merged_by_id = {m["id"]: m for m in merged}
        assert merged_by_id["A"]["val"] == 10  # updated
        assert merged_by_id["B"]["val"] == 2   # preserved
        assert merged_by_id["C"]["val"] == 3   # new

    def test_merge_no_existing_file(self, tmp_path):
        from unittest.mock import patch
        new = [{"id": "A", "val": 1}]
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            result = _merge_with_existing("missing.json", new)
        assert result == new
