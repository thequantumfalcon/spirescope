"""Data source adapters for the update pipeline.

See docs/DATA_SOURCES.md for the source decision record. Every adapter
returns lists of plain dicts in the cards.json / relics.json / potions.json
record shape; the orchestrator in fetcher.run_fetcher merges them
(primary wins per entity, secondary fills gaps).
"""
import json
import logging
import re
import time
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_WIKI_API = "https://slaythespire.wiki.gg/api.php"
_WIKI_CARD_MODULES = [
    "Module:Cards/StS2 data/Ironclad",
    "Module:Cards/StS2 data/Silent",
    "Module:Cards/StS2 data/Defect",
    "Module:Cards/StS2 data/Necrobinder",
    "Module:Cards/StS2 data/Regent",
    "Module:Cards/StS2 data/Colorless",
]
_WIKI_RELIC_MODULE = "Module:Relics/StS2 data"
_WIKI_POTION_MODULE = "Module:Potions/StS2 data"

# Wiki uses "Basic"; the app uses "Starter" (same mapping as fix_card_rarity)
_WIKI_RARITY_MAP = {"Basic": "Starter"}


class Sts2ggSource:
    """Primary: slaythespire2.gg RSC extraction (wraps fetcher internals)."""

    name = "slaythespire2.gg"

    def fetch_cards(self) -> list[dict]:
        from sts2 import fetcher
        return fetcher._scrape_cards(fetcher._fetch_with_retry("/cards"))

    def fetch_relics(self) -> list[dict]:
        from sts2 import fetcher
        return fetcher._scrape_relics(fetcher._fetch_with_retry("/relics"))

    def fetch_potions(self) -> list[dict]:
        from sts2 import fetcher
        return fetcher._scrape_potions(fetcher._fetch_with_retry("/potions"))


# ── wiki.gg Lua module parsing ──

_LUA_ENTRY_RE = re.compile(r'\["((?:[^"\\]|\\.)+)"\]\s*=\s*\{')
_LUA_FIELD_RE = re.compile(
    r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|(\d+)|(true|false))'
)


def _parse_lua_table(content: str) -> dict[str, dict]:
    """Parse the wiki's regular `["Name"] = { Field = value, ... }` tables.

    Not a Lua interpreter — relies on the data modules' flat, regular shape.
    """
    entries: dict[str, dict] = {}
    matches = list(_LUA_ENTRY_RE.finditer(content))
    for i, m in enumerate(matches):
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(content)
        # Scan the whole span to the next entry: the field regex only
        # matches `Word = value` pairs, so trailing braces are inert.
        block = content[start:end]
        fields: dict = {}
        for fm in _LUA_FIELD_RE.finditer(block):
            key = fm.group(1)
            if fm.group(2) is not None:
                fields[key] = fm.group(2).replace('\\"', '"')
            elif fm.group(3) is not None:
                fields[key] = int(fm.group(3))
            else:
                fields[key] = fm.group(4) == "true"
        name = m.group(1).replace('\\"', '"')
        entries[name] = fields
    return entries


def _strip_wiki_templates(s: str) -> str:
    """Render `{{C2|Dowsing}}` / `{{P|Ambergris||2}}` wiki templates to the
    entity name (first non-empty argument after the template name)."""
    def _pick(m):
        args = [a for a in m.group(1).split("|")[1:] if a]
        return args[0] if args else ""
    return re.sub(r"\{\{([^{}]*)\}\}", _pick, s)


def _split_wiki_text(text: str) -> tuple[str, str]:
    """Wiki card text -> (base, upgraded) descriptions.

    Handles `[6|9]` alternations, `$Keyword` markers, `@IE`/`@IS` icon runs,
    and `<br>` breaks. Cleanup/hygiene is applied by the caller via
    fetcher._clean_description.
    """
    def _side(s: str, idx: int) -> str:
        s = re.sub(
            r"\[([^\[\]|]*)\|([^\[\]|]*)\]",
            lambda m: m.group(1 + idx),
            s,
        )
        # Icon runs (per-character codes: @IE, @CE, ...). A preceding digit
        # is the value and the icon is just the unit ("1 @CE" -> "1 Energy");
        # bare runs encode the value by repetition ("@IE@IE" -> "2 Energy").
        s = re.sub(r"(\d+)\s*(?:@[A-Z]E)+", r"\1 Energy", s)
        s = re.sub(r"(\d+)\s*(?:@[A-Z]S)+", r"\1 Star", s)
        s = re.sub(r"(?:@[A-Z]E)+", lambda m: f"{len(m.group(0)) // 3} Energy", s)
        s = re.sub(r"(?:@[A-Z]S)+", lambda m: f"{len(m.group(0)) // 3} Star", s)
        s = s.replace("<br>", " ").replace("<br/>", " ").replace("<br />", " ")
        s = re.sub(r"\$(\w[\w' -]*)", r"\1", s)
        return _strip_wiki_templates(s)

    return _side(text, 0), _side(text, 1)


def _strip_char_suffix(name: str) -> str:
    """'Strike (Ironclad)' -> 'Strike'."""
    return re.sub(r"\s*\([^)]*\)$", "", name)


class WikiggSource:
    """Secondary: slaythespire.wiki.gg MediaWiki API (Lua data modules)."""

    name = "slaythespire.wiki.gg"

    def _fetch_modules(self, titles: list[str]) -> dict[str, str]:
        """Fetch raw Lua content for the given module pages."""
        from sts2.fetcher import _SCRAPE_DELAY, _get_user_agent
        contents: dict[str, str] = {}
        # The API allows batching titles with | separators
        for batch_start in range(0, len(titles), 3):
            if batch_start:
                time.sleep(_SCRAPE_DELAY)
            batch = titles[batch_start:batch_start + 3]
            params = urllib.parse.urlencode({
                "action": "query",
                "titles": "|".join(batch),
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "format": "json",
                "formatversion": "2",
            })
            req = urllib.request.Request(
                f"{_WIKI_API}?{params}",
                headers={"User-Agent": _get_user_agent()},
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            for page in data.get("query", {}).get("pages", []):
                revs = page.get("revisions", [])
                if revs:
                    contents[page["title"]] = revs[0]["slots"]["main"]["content"]
        return contents

    def fetch_cards(self) -> list[dict]:
        from sts2.fetcher import (
            _clean_description,
            _extract_keywords,
            _load_existing_name_index,
        )
        name_index = _load_existing_name_index("cards.json", "CARD")
        modules = self._fetch_modules(_WIKI_CARD_MODULES)
        cards = []
        for title, content in modules.items():
            for raw_name, fields in _parse_lua_table(content).items():
                name = _strip_char_suffix(raw_name)
                character = fields.get("Color", "") or title.rsplit("/", 1)[-1]
                if character == "The Regent":
                    character = "Regent"
                base, upgraded = _split_wiki_text(str(fields.get("Text", "")))
                desc = _clean_description(base)
                game_id = name_index.get(name.lower().strip()) or (
                    f"CARD.{re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')}"
                )
                rarity = str(fields.get("Rarity", ""))
                cards.append({
                    "id": game_id,
                    "name": name,
                    "character": character,
                    "cost": str(fields.get("Cost", "")) or "Unplayable",
                    "type": str(fields.get("Type", "Skill")),
                    "rarity": _WIKI_RARITY_MAP.get(rarity, rarity),
                    "description": desc,
                    "description_upgraded": _clean_description(upgraded),
                    "keywords": _extract_keywords(desc),
                })
        return sorted(cards, key=lambda c: (c["character"], c["name"]))

    def fetch_relics(self) -> list[dict]:
        from sts2.fetcher import _clean_description, _load_existing_name_index
        name_index = _load_existing_name_index("relics.json", "RELIC")
        modules = self._fetch_modules([_WIKI_RELIC_MODULE])
        relics = []
        for content in modules.values():
            for name, fields in _parse_lua_table(content).items():
                game_id = name_index.get(name.lower().strip()) or (
                    f"RELIC.{re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')}"
                )
                rarity = str(fields.get("Rarity", ""))
                relics.append({
                    "id": game_id,
                    "name": name,
                    "character": str(fields.get("Character", "")) or "Shared",
                    "rarity": _WIKI_RARITY_MAP.get(rarity, rarity),
                    "description": _clean_description(_strip_wiki_templates(
                        re.sub(r"\$(\w[\w' -]*)", r"\1",
                               str(fields.get("Description", "")))
                    )),
                })
        return sorted(relics, key=lambda r: (r["character"], r["name"]))

    def fetch_potions(self) -> list[dict]:
        from sts2.fetcher import _clean_description, _load_existing_name_index
        name_index = _load_existing_name_index("potions.json", "POTION")
        modules = self._fetch_modules([_WIKI_POTION_MODULE])
        potions = []
        for content in modules.values():
            for name, fields in _parse_lua_table(content).items():
                base, _up = _split_wiki_text(str(fields.get("Text", "")))
                game_id = name_index.get(name.lower().strip()) or (
                    f"POTION.{re.sub(r'[^A-Z0-9]+', '_', name.upper()).strip('_')}"
                )
                potions.append({
                    "id": game_id,
                    "name": name,
                    "rarity": str(fields.get("Rarity", "")),
                    "description": _clean_description(base),
                })
        return sorted(potions, key=lambda p: p["name"])
