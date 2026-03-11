"""Knowledge base engine: load, search, filter, and synergy analysis."""
import json
import logging
import re

from sts2.config import DATA_DIR, MODS_DIR
from sts2.models import (
    Card,
    CharacterStrategy,
    Enemy,
    Event,
    EventChoice,
    Potion,
    Relic,
    SynergyGroup,
)

log = logging.getLogger(__name__)


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
        self._load_mods()
        self._load_community_data()
        self._discover_from_saves()
        self._build_indexes()

    def _load_json(self, filename: str) -> list[dict]:
        path = DATA_DIR / filename
        if not path.exists():
            return []
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list):
                log.warning("%s is not a list, skipping", filename)
                return []
            return data
        except (json.JSONDecodeError, OSError) as exc:
            log.error("Failed to load %s: %s", filename, exc)
            return []

    def _load_all(self):
        for d in self._load_json("cards.json"):
            try:
                self.cards.append(Card(**d))
            except Exception as exc:
                log.warning("Skipping malformed card %s: %s", d.get("id", "?"), exc)

        for d in self._load_json("relics.json"):
            try:
                self.relics.append(Relic(**d))
            except Exception as exc:
                log.warning("Skipping malformed relic %s: %s", d.get("id", "?"), exc)

        for d in self._load_json("potions.json"):
            try:
                self.potions.append(Potion(**d))
            except Exception as exc:
                log.warning("Skipping malformed potion %s: %s", d.get("id", "?"), exc)

        for d in self._load_json("enemies.json"):
            try:
                self.enemies.append(Enemy(**d))
            except Exception as exc:
                log.warning("Skipping malformed enemy %s: %s", d.get("id", "?"), exc)

        for d in self._load_json("events.json"):
            try:
                evt_data = dict(d)
                if "choices" in evt_data:
                    evt_data["choices"] = [EventChoice(**c) for c in evt_data["choices"]]
                self.events.append(Event(**evt_data))
            except Exception as exc:
                log.warning("Skipping malformed event %s: %s", d.get("id", "?"), exc)

        for d in self._load_json("strategy.json"):
            try:
                strat_data = dict(d)
                if "archetypes" in strat_data:
                    strat_data["archetypes"] = [SynergyGroup(**a) for a in strat_data["archetypes"]]
                self.strategies.append(CharacterStrategy(**strat_data))
            except Exception as exc:
                log.warning("Skipping malformed strategy %s: %s", d.get("character", "?"), exc)

    def _load_mods(self):
        """Load mod data from JSON files in the mods directory."""
        if not MODS_DIR.exists():
            return
        existing_card_ids = {c.id for c in self.cards}
        existing_relic_ids = {r.id for r in self.relics}
        existing_potion_ids = {p.id for p in self.potions}
        existing_enemy_ids = {e.id for e in self.enemies}
        for mod_file in sorted(MODS_DIR.glob("*.json")):
            try:
                data = json.loads(mod_file.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("Skipping malformed mod file %s: %s", mod_file.name, exc)
                continue
            mod_name = data.get("mod_name", mod_file.stem)
            for d in data.get("cards", []):
                try:
                    card = Card(**d, source="mod")
                    if card.id in existing_card_ids:
                        log.warning("Mod %s: card %s conflicts with base, skipped", mod_name, card.id)
                        continue
                    existing_card_ids.add(card.id)
                    self.cards.append(card)
                except Exception as exc:
                    log.warning("Mod %s: skipping malformed card: %s", mod_name, exc)
            for d in data.get("relics", []):
                try:
                    relic = Relic(**d, source="mod")
                    if relic.id in existing_relic_ids:
                        log.warning("Mod %s: relic %s conflicts with base, skipped", mod_name, relic.id)
                        continue
                    existing_relic_ids.add(relic.id)
                    self.relics.append(relic)
                except Exception as exc:
                    log.warning("Mod %s: skipping malformed relic: %s", mod_name, exc)
            for d in data.get("potions", []):
                try:
                    potion = Potion(**d, source="mod")
                    if potion.id in existing_potion_ids:
                        continue
                    existing_potion_ids.add(potion.id)
                    self.potions.append(potion)
                except Exception as exc:
                    log.warning("Mod %s: skipping malformed potion: %s", mod_name, exc)
            for d in data.get("enemies", []):
                try:
                    enemy = Enemy(**d, source="mod")
                    if enemy.id in existing_enemy_ids:
                        continue
                    existing_enemy_ids.add(enemy.id)
                    self.enemies.append(enemy)
                except Exception as exc:
                    log.warning("Mod %s: skipping malformed enemy: %s", mod_name, exc)
            log.info("Loaded mod: %s", mod_name)

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
        """Auto-discover cards, relics, potions, enemies, and events from save files."""
        try:
            from sts2.saves import get_progress
            progress = get_progress()
            if not progress:
                return

            existing_card_ids = {c.id for c in self.cards}
            existing_relic_ids = {r.id for r in self.relics}
            existing_potion_ids = {p.id for p in self.potions}
            existing_enemy_ids = {e.id for e in self.enemies}
            existing_event_ids = {e.id for e in self.events}

            # Discover cards from discovered_cards
            for card_id in progress.discovered_cards:
                if card_id in existing_card_ids:
                    continue
                existing_card_ids.add(card_id)
                name = card_id.split(".", 1)[-1].replace("_", " ").title() if "." in card_id else card_id
                self.cards.append(Card(id=card_id, name=name, character="Unknown",
                                       cost="?", type="Unknown", rarity="Unknown", source="discovered"))

            # Discover relics from discovered_relics
            for relic_id in progress.discovered_relics:
                if relic_id in existing_relic_ids:
                    continue
                existing_relic_ids.add(relic_id)
                name = relic_id.split(".", 1)[-1].replace("_", " ").title() if "." in relic_id else relic_id
                self.relics.append(Relic(id=relic_id, name=name, source="discovered"))

            # Discover potions from discovered_potions
            for potion_id in progress.discovered_potions:
                if potion_id in existing_potion_ids:
                    continue
                existing_potion_ids.add(potion_id)
                name = potion_id.split(".", 1)[-1].replace("_", " ").title() if "." in potion_id else potion_id
                self.potions.append(Potion(id=potion_id, name=name, source="discovered"))

            # Discover enemies from enemy_stats and encounter_stats
            for enemy_id in list(progress.enemy_stats.keys()) + list(progress.encounter_stats.keys()):
                if enemy_id in existing_enemy_ids:
                    continue
                existing_enemy_ids.add(enemy_id)
                name = enemy_id.split(".", 1)[-1].replace("_", " ").title() if "." in enemy_id else enemy_id
                etype = "boss" if "BOSS" in enemy_id.upper() else "elite" if "ELITE" in enemy_id.upper() else "normal"
                self.enemies.append(Enemy(id=enemy_id, name=name, type=etype,
                                         tips=["Auto-discovered from your save data"], source="discovered"))

            # Discover events
            for event_id in progress.discovered_events:
                if event_id in existing_event_ids:
                    continue
                existing_event_ids.add(event_id)
                name = event_id.split(".", 1)[-1].replace("_", " ").title() if "." in event_id else event_id
                self.events.append(Event(id=event_id, name=name,
                                         description="Auto-discovered from your save data",
                                         source="discovered"))
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

    def _score_match(self, query: str, text: str, boundary_re=None) -> float:
        """Fast scoring: exact substring > word boundary > token overlap."""
        if query in text:
            # Boost for matching at word boundary or being a large portion of the name
            if boundary_re and boundary_re.search(text):
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
            if abs(len(name) - len(q)) > max_dist:
                continue  # length difference alone exceeds max_dist
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

        boundary_re = re.compile(r'(?:^|\s|_|\.)' + re.escape(q))
        scored: list[tuple[float, str, object]] = []
        for text, category, obj in self._search_index:
            score = self._score_match(q, text, boundary_re)
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

        # Filter out discovered/unknown-type cards for ratio checks
        typed_cards = [c for c in cards if c.type != "Unknown"]

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
        cost_curve_by_type: dict[str, dict[str, int]] = {}
        numeric_costs: list[int] = []
        for c in cards:
            cost_curve[c.cost] = cost_curve.get(c.cost, 0) + 1
            by_type = cost_curve_by_type.setdefault(c.cost, {})
            by_type[c.type] = by_type.get(c.type, 0) + 1
            if c.cost.isdigit():
                numeric_costs.append(int(c.cost))

        avg_cost = round(sum(numeric_costs) / len(numeric_costs), 1) if numeric_costs else 0.0
        energy_per_hand = round(avg_cost * 5, 1)

        # Weaknesses
        weaknesses = []
        tc = len(typed_cards) or 1  # avoid division by zero
        if len(attacks) < tc * 0.3:
            weaknesses.append("Low attack count — may struggle to kill enemies quickly")
        if len(skills) < tc * 0.2:
            weaknesses.append("Few skills — limited defensive options")
        if not any(kw in keyword_freq for kw in ("Block", "Dexterity")):
            weaknesses.append("No Block generation — vulnerable to damage")
        if "AoE" not in keyword_freq:
            weaknesses.append("No AoE — vulnerable to multi-enemy fights")
        if "Draw" not in keyword_freq:
            weaknesses.append("No card draw — may stall in longer fights")
        if tc > 30:
            weaknesses.append("Deck is bloated (>30 cards) — key cards drawn less often")
        if tc < 15:
            weaknesses.append("Deck is very thin (<15 cards) — may cycle too fast")

        # Mana curve warnings
        high_cost = sum(v for k, v in cost_curve.items() if k.isdigit() and int(k) >= 3)
        zero_cost = cost_curve.get("0", 0)
        if high_cost > tc * 0.4:
            weaknesses.append(f"Heavy mana curve — {high_cost}/{tc} cards cost 3+. Add cheap cards or energy relics.")
        if len(powers) >= 4 and zero_cost < 2:
            weaknesses.append(f"{len(powers)} Powers but only {zero_cost} zero-cost cards — setup turns will be slow.")
        if zero_cost > tc * 0.5:
            weaknesses.append("Over half your deck is 0-cost — may lack impactful plays.")

        # Strengths
        strengths = []
        if 18 <= tc <= 25:
            strengths.append("Good deck size — consistent draws without bloat")
        if any(kw in keyword_freq for kw in ("Block", "Dexterity")) and any(kw in keyword_freq for kw in ("Strength", "Poison", "Lightning")):
            strengths.append("Balanced offense and defense — both scaling and Block present")
        if detected_archetypes:
            strengths.append(f"Clear archetype: {detected_archetypes[0]['name']}")

        return {
            "character": character,
            "deck_size": len(cards),
            "attacks": len(attacks),
            "skills": len(skills),
            "powers": len(powers),
            "cost_curve": dict(sorted(cost_curve.items(), key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0]))),
            "cost_curve_by_type": dict(sorted(cost_curve_by_type.items(), key=lambda kv: (0, int(kv[0])) if kv[0].isdigit() else (1, kv[0]))),
            "avg_cost": avg_cost,
            "energy_per_hand": energy_per_hand,
            "top_keywords": top_keywords[:8],
            "detected_archetypes": detected_archetypes,
            "weaknesses": weaknesses,
            "strengths": strengths,
            "suggestions": [a.get("strategy", "") for a in detected_archetypes[:1]],
        }

    def get_data_status(self, skip_last_updated: bool = False) -> dict:
        """Return data source status for the home page."""
        from sts2.config import SAVE_DIR
        save_exists = SAVE_DIR.exists() and (SAVE_DIR / "progress.save").exists()
        status = {
            "cards": len(self.cards),
            "relics": len(self.relics),
            "potions": len(self.potions),
            "enemies": len(self.enemies),
            "events": len(self.events),
            "save_connected": save_exists,
        }
        if not skip_last_updated:
            status["last_updated"] = get_last_updated()
        return status

    def get_counter_cards(self, enemy: "Enemy", limit: int = 8) -> list[Card]:
        """Find cards that counter an enemy based on keyword heuristics.

        Analyzes enemy tips/patterns for damage, scaling, multi-attack hints,
        then returns cards with matching defensive/offensive keywords.
        """
        if not enemy:
            return []

        enemy_text = " ".join(enemy.tips + enemy.patterns).lower()

        # Determine what the enemy does → what counters it
        need_keywords: dict[str, float] = {}  # keyword → weight

        # High damage enemies → need Block
        if any(w in enemy_text for w in ("high damage", "heavy damage", "hits hard",
                                          "large attack", "massive")):
            need_keywords["Block"] = 2.0
            need_keywords["Dexterity"] = 1.5

        # Multi-attack enemies → need Block per hit (Dexterity)
        if any(w in enemy_text for w in ("multi", "multiple", "hits", "times",
                                          "each turn", "x times")):
            need_keywords["Dexterity"] = 2.0
            need_keywords["Block"] = 1.5

        # Scaling enemies → need burst damage
        if any(w in enemy_text for w in ("strength", "scaling", "grows", "stronger",
                                          "buff", "enrage")):
            need_keywords["Strength"] = 1.5
            need_keywords["Weak"] = 1.5
            need_keywords["Poison"] = 1.0

        # Enemies with artifact → need multi-debuff
        if "artifact" in enemy_text:
            need_keywords["Weak"] = 0.5  # reduced since artifact blocks it
            need_keywords["Poison"] = 1.5

        # Boss-type → value Weak and sustained damage
        if enemy.type == "boss":
            need_keywords["Weak"] = need_keywords.get("Weak", 0) + 1.0
            need_keywords["Strength"] = need_keywords.get("Strength", 0) + 0.5
            need_keywords["Block"] = need_keywords.get("Block", 0) + 0.5

        # Elite-type → value burst and Block
        if enemy.type == "elite":
            need_keywords["Block"] = need_keywords.get("Block", 0) + 0.5

        if not need_keywords:
            # Generic fallback: recommend Block + damage
            need_keywords = {"Block": 1.0, "Strength": 0.5}

        # Score each card
        scored: list[tuple[float, Card]] = []
        for card in self.cards:
            if card.character in ("Status", "Curse"):
                continue
            if not card.keywords:
                continue
            score = sum(need_keywords.get(kw, 0) for kw in card.keywords)
            if score > 0:
                # Bonus for uncommon/rare (more impactful)
                if card.rarity in ("Uncommon", "Rare"):
                    score *= 1.2
                scored.append((score, card))

        scored.sort(key=lambda x: -x[0])
        # Deduplicate by name (different characters may share keyword patterns)
        seen_names: set[str] = set()
        result = []
        for _, card in scored:
            if card.name not in seen_names:
                seen_names.add(card.name)
                result.append(card)
                if len(result) >= limit:
                    break
        return result

    def get_undiscovered_cards(self, discovered_ids: list[str]) -> list[Card]:
        """Return cards that exist in the KB but haven't been discovered yet."""
        discovered = set(discovered_ids)
        return [c for c in self.cards
                if c.id not in discovered
                and c.character not in ("Status", "Curse", "Unknown")]

    def find_relic_archetypes(self, relic_name: str) -> list[dict]:
        """Find strategy archetypes that mention this relic."""
        results = []
        name_lower = relic_name.lower()
        for strat in self.strategies:
            for arch in strat.archetypes:
                if any(name_lower == kr.lower() for kr in arch.key_relics):
                    results.append({
                        "character": strat.character,
                        "archetype": arch.name,
                        "strategy": arch.strategy,
                    })
        return results

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
