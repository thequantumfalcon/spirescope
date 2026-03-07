"""Tests for the scraper module."""
import json
import pytest
from unittest.mock import patch
from sts2.scraper import (
    _clean_description,
    _extract_json_objects,
    _extract_keywords,
    _wiki_id_to_game_id,
    _load_existing_name_index,
    _merge_with_existing,
    _discover_enemies_from_saves,
    _discover_events_from_saves,
    _scrape_cards,
    _scrape_relics,
    _existing_count,
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

    def test_silent_suffix(self):
        assert _wiki_id_to_game_id("after-image-silent", "CARD") == "CARD.AFTER_IMAGE"

    def test_defect_suffix(self):
        assert _wiki_id_to_game_id("ball-lightning-defect", "CARD") == "CARD.BALL_LIGHTNING"

    def test_necrobinder_suffix(self):
        assert _wiki_id_to_game_id("bone-lance-necrobinder", "CARD") == "CARD.BONE_LANCE"

    def test_colorless_suffix(self):
        assert _wiki_id_to_game_id("finesse-colorless", "CARD") == "CARD.FINESSE"

    def test_the_regent_suffix(self):
        assert _wiki_id_to_game_id("royal-decree-the-regent", "CARD") == "CARD.ROYAL_DECREE"

    def test_relic_id(self):
        assert _wiki_id_to_game_id("burning-blood", "RELIC") == "RELIC.BURNING_BLOOD"


class TestLoadExistingNameIndex:
    def test_builds_index(self, tmp_path):
        data = [{"id": "CARD.BASH", "name": "Bash"}, {"id": "CARD.STRIKE", "name": "Strike"}]
        (tmp_path / "cards.json").write_text(json.dumps(data))
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            index = _load_existing_name_index("cards.json", "CARD")
        assert index["bash"] == "CARD.BASH"
        assert index["strike"] == "CARD.STRIKE"

    def test_missing_file(self, tmp_path):
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            index = _load_existing_name_index("nope.json", "CARD")
        assert index == {}


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
        new = [{"id": "A", "val": 1}]
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            result = _merge_with_existing("missing.json", new)
        assert result == new


class TestDiscoverEnemiesFromSaves:
    def test_discovers_from_progress(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "enemies.json").write_text("[]")
        progress = {"encounter_stats": [{"encounter_id": "BOSS.HEXAGHOST", "fight_stats": []}]}
        (save_dir / "progress.save").write_text(json.dumps(progress))

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            enemies = _discover_enemies_from_saves()

        assert len(enemies) == 1
        assert enemies[0]["id"] == "BOSS.HEXAGHOST"
        assert enemies[0]["type"] == "boss"

    def test_discovers_from_run_history(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "enemies.json").write_text("[]")
        history = save_dir / "history"
        history.mkdir()
        run = {
            "players": [{"id": 1}],
            "map_point_history": [[{
                "map_point_type": "elite",
                "rooms": [{"monster_ids": ["GREMLIN_NOB"], "room_type": "elite"}],
                "player_stats": [],
            }]],
        }
        (history / "run_001.run").write_text(json.dumps(run))

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            enemies = _discover_enemies_from_saves()

        assert len(enemies) == 1
        assert enemies[0]["id"] == "MONSTER.GREMLIN_NOB"
        assert enemies[0]["type"] == "elite"
        assert "Act 1" in enemies[0]["act"]

    def test_skips_existing_enemies(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "enemies.json").write_text(json.dumps([{"id": "BOSS.HEXAGHOST", "name": "Hexaghost"}]))
        progress = {"encounter_stats": [{"encounter_id": "BOSS.HEXAGHOST", "fight_stats": []}]}
        (save_dir / "progress.save").write_text(json.dumps(progress))

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            enemies = _discover_enemies_from_saves()

        assert len(enemies) == 0

    def test_no_saves(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "enemies.json").write_text("[]")

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            enemies = _discover_enemies_from_saves()

        assert enemies == []


class TestDiscoverEventsFromSaves:
    def test_discovers_from_progress(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "events.json").write_text("[]")
        progress = {"discovered_events": ["EVENT.BONFIRE", "EVENT.DEAD_ADVENTURER"]}
        (save_dir / "progress.save").write_text(json.dumps(progress))

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            events = _discover_events_from_saves()

        assert len(events) == 2
        ids = {e["id"] for e in events}
        assert "EVENT.BONFIRE" in ids
        assert "EVENT.DEAD_ADVENTURER" in ids

    def test_skips_existing_events(self, tmp_path):
        save_dir = tmp_path / "saves"
        save_dir.mkdir()
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "events.json").write_text(json.dumps([{"id": "EVENT.BONFIRE", "name": "Bonfire"}]))
        progress = {"discovered_events": ["EVENT.BONFIRE"]}
        (save_dir / "progress.save").write_text(json.dumps(progress))

        with patch("sts2.scraper.DATA_DIR", data_dir), \
             patch("sts2.config.SAVE_DIR", save_dir):
            events = _discover_events_from_saves()

        assert len(events) == 0


class TestScrapeCards:
    def test_parses_card_from_html(self, tmp_path):
        card_json = json.dumps({
            "id": "bash-ironclad", "category": "CARD", "name": "Bash",
            "character": "Ironclad", "energy": 2, "cardType": "Attack",
            "rarity": "Starter", "description": "Deal 8 damage. Apply 2 Vulnerable.",
            "upgradedDescription": "Deal 10 damage. Apply 3 Vulnerable.",
        })
        html = f'<html><body>prefix {card_json} suffix</body></html>'
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            cards = _scrape_cards(html)
        assert len(cards) == 1
        assert cards[0]["name"] == "Bash"
        assert cards[0]["type"] == "Attack"
        assert cards[0]["cost"] == "2"
        assert "Vulnerable" in cards[0]["keywords"]

    def test_deduplicates_same_wiki_id(self, tmp_path):
        card_json = json.dumps({
            "id": "bash-ironclad", "category": "CARD", "name": "Bash",
            "character": "Ironclad", "energy": 2, "cardType": "Attack",
            "rarity": "Starter", "description": "Deal 8 damage.",
        })
        html = f'{card_json} {card_json}'
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            cards = _scrape_cards(html)
        assert len(cards) == 1


class TestScrapeRelics:
    def test_parses_relic_from_html(self, tmp_path):
        relic_json = json.dumps({
            "id": "burning-blood", "category": "RELIC", "name": "Burning Blood",
            "relicPools": ["Ironclad"], "rarity": "Starter",
            "description": "At the end of combat, heal 6 HP.",
        })
        html = f'<html>{relic_json}</html>'
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            relics = _scrape_relics(html)
        assert len(relics) == 1
        assert relics[0]["name"] == "Burning Blood"
        assert relics[0]["character"] == "Ironclad"


class TestExistingCount:
    def test_counts_items(self, tmp_path):
        data = [{"id": "A"}, {"id": "B"}, {"id": "C"}]
        (tmp_path / "test.json").write_text(json.dumps(data))
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            assert _existing_count("test.json") == 3

    def test_missing_file(self, tmp_path):
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            assert _existing_count("nope.json") == 0

    def test_corrupt_file(self, tmp_path):
        (tmp_path / "bad.json").write_text("not json")
        with patch("sts2.scraper.DATA_DIR", tmp_path):
            assert _existing_count("bad.json") == 0
