"""Knowledge base engine: load, search, filter, and synergy analysis."""
import json
import re

from sts2.config import DATA_DIR
from sts2.models import Card, Relic, Potion, Enemy, Event, EventChoice, CharacterStrategy, SynergyGroup


def get_last_updated() -> str:
    """Return the last data update timestamp, or empty string if unknown."""
    path = DATA_DIR / "last_updated.txt"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _levenshtein(a: str, b: str) -> int:
    """Compute Levenshtein edit distance between two strings."""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr = [i + 1]
        for j, cb in enumerate(b):
            curr.append(min(
                prev[j + 1] + 1,      # deletion
                curr[j] + 1,           # insertion
                prev[j] + (ca != cb),  # substitution
            ))
        prev = curr
    return prev[-1]


class KnowledgeBase:
    def __init__(self):
        self.cards: list[Card] = []
        self.relics: list[Relic] = []
        self.potions: list[Potion] = []
        self.enemies: list[Enemy] = []
        self.events: list[Event] = []
        self.strategies: list[CharacterStrategy] = []

        # Community data from Reddit
        self.community_tips: dict[str, list[str]] = {}  # name_lower -> tips
        self.meta_posts: list[dict] = []

        # O(1) lookup indexes
        self._cards_by_id: dict[str, Card] = {}
        self._enemies_by_id: dict[str, Enemy] = {}
        self._relics_by_id: dict[str, Relic] = {}
        self._potions_by_id: dict[str, Potion] = {}
        self._strategies_by_char: dict[str, CharacterStrategy] = {}

        # Pre-built search index: list of (searchable_text, type, obj)
        self._search_index: list[tuple[str, str, object]] = []
        # All unique entity names for fuzzy suggestions
        self._all_names: list[str] = []

        self._load_all()
        self._load_community_data()
        self._discover_from_saves()
        self._build_indexes()

    def _load_json(self, filename: str) -> list[dict]:
        path = DATA_DIR / filename
        if path.exists():
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return []

    def _load_all(self):
        for d in self._load_json("cards.json"):
            self.cards.append(Card(**d))

        for d in self._load_json("relics.json"):
            self.relics.append(Relic(**d))

        for d in self._load_json("potions.json"):
            self.potions.append(Potion(**d))

        for d in self._load_json("enemies.json"):
            self.enemies.append(Enemy(**d))

        for d in self._load_json("events.json"):
            evt_data = dict(d)
            if "choices" in evt_data:
                evt_data["choices"] = [EventChoice(**c) for c in evt_data["choices"]]
            self.events.append(Event(**evt_data))

        for d in self._load_json("strategy.json"):
            strat_data = dict(d)
            if "archetypes" in strat_data:
                strat_data["archetypes"] = [SynergyGroup(**a) for a in strat_data["archetypes"]]
            self.strategies.append(CharacterStrategy(**strat_data))

    def _load_community_data(self):
        """Load community tips and meta posts from community.json."""
        path = DATA_DIR / "community.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            self.community_tips = data.get("community_tips", {})
            self.meta_posts = data.get("meta_posts", [])
        except (json.JSONDecodeError, OSError):
            pass

    def get_community_tips(self, entity_name: str) -> list[str]:
        """Get community tips for an entity by name."""
        return self.community_tips.get(entity_name.lower().strip(), [])

    def _discover_from_saves(self):
        """Auto-discover enemies and events from save files on startup."""
        try:
            from sts2.saves import get_progress
            progress = get_progress()
            if not progress:
                return

            existing_enemy_ids = {e.id for e in self.enemies}
            existing_event_ids = {e.id for e in self.events}

            # Discover enemies from enemy_stats and encounter_stats
            for enemy_id in list(progress.enemy_stats.keys()) + list(progress.encounter_stats.keys()):
                if enemy_id in existing_enemy_ids:
                    continue
                existing_enemy_ids.add(enemy_id)
                name = enemy_id.split(".", 1)[-1].replace("_", " ").title() if "." in enemy_id else enemy_id
                etype = "boss" if "BOSS" in enemy_id.upper() else "elite" if "ELITE" in enemy_id.upper() else "normal"
                self.enemies.append(Enemy(id=enemy_id, name=name, type=etype,
                                         tips=["Auto-discovered from your save data"]))

            # Discover events
            for event_id in progress.discovered_events:
                if event_id in existing_event_ids:
                    continue
                existing_event_ids.add(event_id)
                name = event_id.split(".", 1)[-1].replace("_", " ").title() if "." in event_id else event_id
                self.events.append(Event(id=event_id, name=name,
                                         description="Auto-discovered from your save data"))
        except Exception:
            pass  # save files may not exist (e.g., CI)

    def _build_indexes(self):
        """Build O(1) lookup dicts and pre-tokenized search index."""
        for c in self.cards:
            self._cards_by_id[c.id] = c
        for e in self.enemies:
            self._enemies_by_id[e.id] = e
        for r in self.relics:
            self._relics_by_id[r.id] = r
        for p in self.potions:
            self._potions_by_id[p.id] = p
        for s in self.strategies:
            self._strategies_by_char[s.character.lower()] = s

        # Build search index with pre-lowered text for fast substring/token matching
        for card in self.cards:
            text = f"{card.name} {card.id} {card.description} {' '.join(card.keywords)}".lower()
            self._search_index.append((text, "cards", card))
        for relic in self.relics:
            text = f"{relic.name} {relic.id} {relic.description}".lower()
            self._search_index.append((text, "relics", relic))
        for potion in self.potions:
            text = f"{potion.name} {potion.id} {potion.description}".lower()
            self._search_index.append((text, "potions", potion))
        for enemy in self.enemies:
            text = f"{enemy.name} {enemy.id}".lower()
            self._search_index.append((text, "enemies", enemy))
        for event in self.events:
            text = f"{event.name} {event.id} {event.description}".lower()
            self._search_index.append((text, "events", event))

        # Collect all unique names for fuzzy suggestions
        seen_names: set[str] = set()
        for entry in self._search_index:
            name = getattr(entry[2], "name", "")
            if name and name.lower() not in seen_names:
                seen_names.add(name.lower())
                self._all_names.append(name)

    def _score_match(self, query: str, text: str) -> float:
        """Fast scoring: exact substring > word boundary > token overlap."""
        if query in text:
            # Boost for matching at word boundary or being a large portion of the name
            if re.search(r'(?:^|\s|_|\.)' + re.escape(query), text):
                return 1.0
            return 0.9
        # Normalized query with underscores
        q_norm = query.replace(" ", "_")
        if q_norm in text.replace(" ", "_"):
            return 0.85
        # Token overlap: split both into words, check overlap ratio
        q_tokens = set(query.split())
        t_tokens = set(text.split())
        if q_tokens and q_tokens <= t_tokens:
            return 0.8
        overlap = q_tokens & t_tokens
        if overlap:
            return 0.5 * len(overlap) / len(q_tokens)
        return 0.0

    def suggest(self, query: str, max_suggestions: int = 3) -> list[str]:
        """Find closest entity names to a misspelled query using edit distance."""
        q = query.lower().strip()
        if not q:
            return []
        max_dist = max(2, len(q) // 3)  # allow more tolerance for longer queries
        candidates: list[tuple[int, str]] = []
        for name in self._all_names:
            dist = _levenshtein(q, name.lower())
            if dist <= max_dist:
                candidates.append((dist, name))
        candidates.sort(key=lambda x: x[0])
        return [name for _, name in candidates[:max_suggestions]]

    def search(self, query: str, limit: int = 20) -> dict:
        """Search across all entity types. Returns dict with results and suggestions."""
        results: dict[str, list] = {"cards": [], "relics": [], "potions": [], "enemies": [], "events": [], "suggestions": []}
        q = query.lower().strip()
        if not q:
            return results

        scored: list[tuple[float, str, object]] = []
        for text, category, obj in self._search_index:
            score = self._score_match(q, text)
            if score > 0.3:
                scored.append((score, category, obj))

        scored.sort(key=lambda x: -x[0])
        counts: dict[str, int] = {k: 0 for k in results if k != "suggestions"}
        for score, category, obj in scored:
            if counts[category] < limit:
                results[category].append(obj)
                counts[category] += 1

        # If no results found, suggest similar names
        total = sum(len(v) for k, v in results.items() if k != "suggestions")
        if total == 0:
            results["suggestions"] = self.suggest(q)

        return results

    def get_cards(self, character: str = None, card_type: str = None,
                  rarity: str = None, cost: str = None, keyword: str = None) -> list[Card]:
        """Filter cards by criteria."""
        result = self.cards
        if character:
            result = [c for c in result if c.character.lower() == character.lower()]
        if card_type:
            result = [c for c in result if c.type.lower() == card_type.lower()]
        if rarity:
            result = [c for c in result if c.rarity.lower() == rarity.lower()]
        if cost:
            result = [c for c in result if c.cost == cost]
        if keyword:
            kw = keyword.lower()
            result = [c for c in result if any(kw in k.lower() for k in c.keywords)]
        return result

    def get_card_by_id(self, card_id: str) -> Card | None:
        return self._cards_by_id.get(card_id)

    def get_relics(self, character: str = None, rarity: str = None) -> list[Relic]:
        result = self.relics
        if character:
            result = [r for r in result if r.character.lower() == character.lower() or r.character == "Shared"]
        if rarity:
            result = [r for r in result if r.rarity.lower() == rarity.lower()]
        return result

    def get_relic_by_id(self, relic_id: str) -> Relic | None:
        return self._relics_by_id.get(relic_id)

    def get_potions(self, rarity: str = None) -> list[Potion]:
        result = self.potions
        if rarity:
            result = [p for p in result if p.rarity.lower() == rarity.lower()]
        return result

    def get_enemy_by_id(self, enemy_id: str) -> Enemy | None:
        return self._enemies_by_id.get(enemy_id)

    def get_enemies(self, act: str = None, enemy_type: str = None) -> list[Enemy]:
        result = self.enemies
        if act:
            result = [e for e in result if any(act.lower() in a.lower() for a in e.act)]
        if enemy_type:
            result = [e for e in result if e.type.lower() == enemy_type.lower()]
        return result

    def get_strategy(self, character: str) -> CharacterStrategy | None:
        return self._strategies_by_char.get(character.lower())

    def find_synergies(self, card_id: str) -> list[Card]:
        """Find cards that synergize with the given card based on shared keywords."""
        card = self.get_card_by_id(card_id)
        if not card or not card.keywords:
            return []

        synergies = []
        for other in self.cards:
            if other.id == card_id:
                continue
            if other.character != card.character and other.character not in ("Colorless", "Status"):
                continue
            shared = set(card.keywords) & set(other.keywords)
            if shared:
                synergies.append(other)
        return synergies

    def analyze_deck(self, card_ids: list[str]) -> dict:
        """Analyze a deck composition."""
        cards = [self.get_card_by_id(cid) for cid in card_ids]
        cards = [c for c in cards if c is not None]

        if not cards:
            return {"error": "No valid cards found"}

        # Determine character
        chars = set(c.character for c in cards if c.character not in ("Colorless", "Status"))
        character = chars.pop() if len(chars) == 1 else "Mixed"

        # Count types
        attacks = [c for c in cards if c.type == "Attack"]
        skills = [c for c in cards if c.type == "Skill"]
        powers = [c for c in cards if c.type == "Power"]

        # Keyword frequency
        keyword_freq: dict[str, int] = {}
        for c in cards:
            for kw in c.keywords:
                keyword_freq[kw] = keyword_freq.get(kw, 0) + 1
        top_keywords = sorted(keyword_freq.items(), key=lambda x: -x[1])

        # Detect archetypes
        strategy = self.get_strategy(character) if character != "Mixed" else None
        detected_archetypes = []
        if strategy:
            for arch in strategy.archetypes:
                arch_cards = set(name.lower() for name in arch.key_cards)
                deck_names = set(c.name.lower() for c in cards)
                overlap = arch_cards & deck_names
                if len(overlap) >= 2:
                    detected_archetypes.append({
                        "name": arch.name,
                        "matched_cards": list(overlap),
                        "missing_key_cards": list(arch_cards - deck_names),
                        "strategy": arch.strategy,
                    })

        # Cost curve
        cost_curve: dict[str, int] = {}
        for c in cards:
            cost_curve[c.cost] = cost_curve.get(c.cost, 0) + 1

        # Weaknesses
        weaknesses = []
        if len(attacks) < len(cards) * 0.3:
            weaknesses.append("Low attack count - may struggle to kill enemies quickly")
        if len(skills) < len(cards) * 0.2:
            weaknesses.append("Few skills - limited defensive options")
        if not any(kw in keyword_freq for kw in ("Block", "Dexterity")):
            weaknesses.append("No Block generation - vulnerable to damage")
        if len(cards) > 30:
            weaknesses.append("Deck is bloated (>30 cards) - key cards drawn less often")
        if len(cards) < 15:
            weaknesses.append("Deck is very thin (<15 cards) - may cycle too fast")

        return {
            "character": character,
            "deck_size": len(cards),
            "attacks": len(attacks),
            "skills": len(skills),
            "powers": len(powers),
            "cost_curve": dict(sorted(cost_curve.items())),
            "top_keywords": top_keywords[:8],
            "detected_archetypes": detected_archetypes,
            "weaknesses": weaknesses,
            "suggestions": [a.get("strategy", "") for a in detected_archetypes[:1]],
        }

    def id_to_name(self, entity_id: str) -> str:
        """Convert a game ID like CARD.BASH to a display name."""
        card = self._cards_by_id.get(entity_id)
        if card:
            return f"{card.name} ({card.character})"
        relic = self._relics_by_id.get(entity_id)
        if relic:
            return relic.name
        potion = self._potions_by_id.get(entity_id)
        if potion:
            return potion.name
        enemy = self._enemies_by_id.get(entity_id)
        if enemy:
            return enemy.name
        # Fallback: strip prefix and format
        if "." in entity_id:
            return entity_id.split(".", 1)[1].replace("_", " ").title()
        return entity_id
