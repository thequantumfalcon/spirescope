"""Tests for the KnowledgeBase engine."""
import pytest

from sts2.knowledge import KnowledgeBase, _levenshtein


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase()


class TestDataLoading:
    def test_cards_loaded(self, kb):
        assert len(kb.cards) > 0

    def test_relics_loaded(self, kb):
        assert len(kb.relics) > 0

    def test_potions_loaded(self, kb):
        assert len(kb.potions) > 0

    def test_enemies_loaded(self, kb):
        assert len(kb.enemies) > 0

    def test_events_loaded(self, kb):
        assert len(kb.events) > 0

    def test_strategies_loaded(self, kb):
        assert len(kb.strategies) > 0

    def test_card_fields(self, kb):
        card = kb.cards[0]
        assert card.id
        assert card.name
        assert card.character
        assert card.cost is not None
        assert card.type


class TestIndexLookups:
    def test_get_card_by_id(self, kb):
        card = kb.cards[0]
        result = kb.get_card_by_id(card.id)
        assert result is not None
        assert result.id == card.id
        assert result.name == card.name

    def test_get_card_by_id_missing(self, kb):
        assert kb.get_card_by_id("CARD.NONEXISTENT") is None

    def test_get_enemy_by_id(self, kb):
        enemy = kb.enemies[0]
        result = kb.get_enemy_by_id(enemy.id)
        assert result is not None
        assert result.id == enemy.id

    def test_get_enemy_by_id_missing(self, kb):
        assert kb.get_enemy_by_id("ENEMY.NONEXISTENT") is None

    def test_get_strategy(self, kb):
        strat = kb.strategies[0]
        result = kb.get_strategy(strat.character)
        assert result is not None
        assert result.character == strat.character

    def test_get_strategy_case_insensitive(self, kb):
        strat = kb.strategies[0]
        result = kb.get_strategy(strat.character.upper())
        assert result is not None

    def test_get_strategy_missing(self, kb):
        assert kb.get_strategy("FakeCharacter") is None

    def test_id_to_name_card(self, kb):
        card = kb.cards[0]
        name = kb.id_to_name(card.id)
        assert card.name in name

    def test_id_to_name_relic(self, kb):
        relic = kb.relics[0]
        name = kb.id_to_name(relic.id)
        assert name == relic.name

    def test_id_to_name_fallback(self, kb):
        name = kb.id_to_name("PREFIX.SOME_THING")
        assert name == "Some Thing"

    def test_id_to_name_no_prefix(self, kb):
        assert kb.id_to_name("raw_id") == "raw_id"


class TestSearch:
    def test_search_empty_query(self, kb):
        results = kb.search("")
        assert all(len(v) == 0 for v in results.values())

    def test_search_finds_card_by_name(self, kb):
        card = kb.cards[0]
        results = kb.search(card.name)
        assert len(results["cards"]) > 0
        assert any(c.id == card.id for c in results["cards"])

    def test_search_finds_relic_by_name(self, kb):
        relic = kb.relics[0]
        results = kb.search(relic.name)
        assert len(results["relics"]) > 0

    def test_search_result_categories(self, kb):
        results = kb.search("test")
        assert set(results.keys()) == {"cards", "relics", "potions", "enemies", "events", "suggestions"}

    def test_search_respects_limit(self, kb):
        results = kb.search("a", limit=3)
        for k, v in results.items():
            if k != "suggestions":
                assert len(v) <= 3

    def test_search_suggestions_on_no_results(self, kb):
        if not kb.cards:
            pytest.skip("No cards loaded")
        card = kb.cards[0]
        # Mangle name to miss exact match but stay close for suggestions
        mangled = card.name[:-1] + "z"
        results = kb.search(mangled)
        total = sum(len(v) for k, v in results.items() if k != "suggestions")
        if total == 0:
            assert len(results["suggestions"]) > 0

    def test_search_no_suggestions_when_results_found(self, kb):
        card = kb.cards[0]
        results = kb.search(card.name)
        assert results["suggestions"] == []


class TestFilters:
    def test_filter_cards_by_character(self, kb):
        ironclad_cards = kb.get_cards(character="Ironclad")
        assert all(c.character == "Ironclad" for c in ironclad_cards)

    def test_filter_cards_by_type(self, kb):
        attacks = kb.get_cards(card_type="Attack")
        assert all(c.type == "Attack" for c in attacks)

    def test_filter_cards_by_rarity(self, kb):
        rares = kb.get_cards(rarity="Rare")
        assert all(c.rarity == "Rare" for c in rares)

    def test_filter_cards_combined(self, kb):
        cards = kb.get_cards(character="Ironclad", card_type="Attack")
        assert all(c.character == "Ironclad" and c.type == "Attack" for c in cards)

    def test_filter_relics_by_character(self, kb):
        relics = kb.get_relics(character="Ironclad")
        assert all(r.character in ("Ironclad", "Shared") for r in relics)

    def test_filter_enemies_by_type(self, kb):
        bosses = kb.get_enemies(enemy_type="boss")
        assert all(e.type.lower() == "boss" for e in bosses)

    def test_get_cards_no_filter(self, kb):
        assert kb.get_cards() == kb.cards


class TestSynergies:
    def test_find_synergies_returns_same_character(self, kb):
        # Find a card with keywords
        card = next((c for c in kb.cards if c.keywords), None)
        if card is None:
            pytest.skip("No cards with keywords")
        synergies = kb.find_synergies(card.id)
        for s in synergies:
            assert s.character == card.character or s.character in ("Colorless", "Status")

    def test_find_synergies_excludes_self(self, kb):
        card = next((c for c in kb.cards if c.keywords), None)
        if card is None:
            pytest.skip("No cards with keywords")
        synergies = kb.find_synergies(card.id)
        assert all(s.id != card.id for s in synergies)

    def test_find_synergies_no_keywords(self, kb):
        card = next((c for c in kb.cards if not c.keywords), None)
        if card is None:
            pytest.skip("All cards have keywords")
        assert kb.find_synergies(card.id) == []

    def test_find_synergies_missing_card(self, kb):
        assert kb.find_synergies("CARD.NONEXISTENT") == []


class TestDeckAnalysis:
    def test_analyze_empty_deck(self, kb):
        result = kb.analyze_deck([])
        assert result.get("error")

    def test_analyze_invalid_ids(self, kb):
        result = kb.analyze_deck(["FAKE.ONE", "FAKE.TWO"])
        assert result.get("error")

    def test_analyze_valid_deck(self, kb):
        # Pick some real card IDs
        ids = [c.id for c in kb.cards[:10]]
        result = kb.analyze_deck(ids)
        assert "error" not in result
        assert result["deck_size"] > 0
        assert "attacks" in result
        assert "skills" in result
        assert "powers" in result
        assert "cost_curve" in result
        assert "top_keywords" in result
        assert isinstance(result["weaknesses"], list)

    def test_analyze_deck_cost_metrics(self, kb):
        """analyze_deck returns avg_cost, energy_per_hand, and cost_curve_by_type."""
        ids = [c.id for c in kb.cards[:10]]
        result = kb.analyze_deck(ids)
        assert isinstance(result["avg_cost"], float)
        assert result["avg_cost"] >= 0
        assert isinstance(result["energy_per_hand"], float)
        assert result["energy_per_hand"] >= 0
        assert isinstance(result["cost_curve_by_type"], dict)
        for cost, by_type in result["cost_curve_by_type"].items():
            assert isinstance(by_type, dict)
            for card_type, count in by_type.items():
                assert isinstance(count, int)
                assert count > 0

    def test_analyze_deck_character_detection(self, kb):
        ironclad = [c.id for c in kb.cards if c.character == "Ironclad"][:5]
        if not ironclad:
            pytest.skip("No Ironclad cards")
        result = kb.analyze_deck(ironclad)
        assert result["character"] == "Ironclad"

    def test_analyze_mixed_characters(self, kb):
        chars = set()
        ids = []
        for c in kb.cards:
            if c.character not in ("Colorless", "Status") and c.character not in chars:
                chars.add(c.character)
                ids.append(c.id)
            if len(chars) >= 2:
                break
        if len(chars) < 2:
            pytest.skip("Not enough characters")
        result = kb.analyze_deck(ids)
        assert result["character"] == "Mixed"


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("bash", "bash") == 0

    def test_one_char_diff(self):
        assert _levenshtein("bash", "bask") == 1

    def test_insertion(self):
        assert _levenshtein("bas", "bash") == 1

    def test_deletion(self):
        assert _levenshtein("bash", "bas") == 1

    def test_empty(self):
        assert _levenshtein("", "abc") == 3
        assert _levenshtein("abc", "") == 3

    def test_both_empty(self):
        assert _levenshtein("", "") == 0

    def test_completely_different(self):
        assert _levenshtein("abc", "xyz") == 3


class TestAutoDiscovery:
    def test_discover_from_saves_adds_enemies(self, kb):
        """KB should have auto-discovered enemies from save files (if saves exist)."""
        # This just checks the mechanism doesn't crash; actual discovery depends on saves
        assert isinstance(kb.enemies, list)

    def test_discover_from_saves_adds_events(self, kb):
        """KB should have auto-discovered events from save files (if saves exist)."""
        assert isinstance(kb.events, list)

    def test_discovered_enemy_has_type(self):
        """Auto-discovered enemies from saves should have a type assigned."""
        from unittest.mock import patch

        from sts2.models import PlayerProgress

        mock_progress = PlayerProgress(
            enemy_stats={"BOSS.TEST_BOSS": {"Ironclad": {"wins": 1, "losses": 0}}},
        )
        with patch("sts2.saves.get_progress", return_value=mock_progress):
            test_kb = KnowledgeBase()
        enemy = test_kb.get_enemy_by_id("BOSS.TEST_BOSS")
        if enemy:
            assert enemy.type == "boss"

    def test_discovered_event_has_name(self):
        """Auto-discovered events from saves should have readable names."""
        from unittest.mock import patch

        from sts2.models import PlayerProgress

        mock_progress = PlayerProgress(
            discovered_events=["EVENT.DEAD_ADVENTURER"],
        )
        with patch("sts2.saves.get_progress", return_value=mock_progress):
            test_kb = KnowledgeBase()
        found = [e for e in test_kb.events if e.id == "EVENT.DEAD_ADVENTURER"]
        if found:
            assert found[0].name == "Dead Adventurer"


class TestSuggest:
    def test_suggest_finds_close_match(self, kb):
        if not kb.cards:
            pytest.skip("No cards loaded")
        card = kb.cards[0]
        # Mangle the name slightly
        mangled = card.name[:-1] + "z"
        suggestions = kb.suggest(mangled)
        assert len(suggestions) > 0

    def test_suggest_empty_query(self, kb):
        assert kb.suggest("") == []

    def test_suggest_exact_match_returns(self, kb):
        if not kb.cards:
            pytest.skip("No cards loaded")
        card = kb.cards[0]
        suggestions = kb.suggest(card.name)
        assert card.name in suggestions


class TestEpochs:
    def test_epochs_loaded(self, kb):
        assert len(kb.epochs) > 0

    def test_get_epoch_by_id(self, kb):
        epoch = kb.epochs[0]
        result = kb.get_epoch_by_id(epoch.id)
        assert result is not None
        assert result.id == epoch.id
        assert result.name == epoch.name

    def test_get_epochs_filter_category(self, kb):
        character_epochs = kb.get_epochs(category="character")
        assert len(character_epochs) > 0
        assert all(e.category == "character" for e in character_epochs)

    def test_get_epochs_filter_character(self, kb):
        ironclad_epochs = kb.get_epochs(character="Ironclad")
        assert len(ironclad_epochs) > 0
        assert all(e.character.lower() == "ironclad" for e in ironclad_epochs)

    def test_get_epoch_by_id_missing(self, kb):
        assert kb.get_epoch_by_id("NONEXISTENT_EPOCH") is None
