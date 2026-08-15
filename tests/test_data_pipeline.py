"""P1 data pipeline: source adapters, fallback, provenance, data-bundle updates."""
import hashlib
import json
import tarfile
import urllib.error
from pathlib import Path
from unittest.mock import patch

import pytest

from sts2 import updater
from sts2.sources import (
    WikiggSource,
    _parse_lua_table,
    _split_wiki_text,
    _strip_char_suffix,
    _strip_wiki_templates,
)

LUA_FIXTURE = '''
local all_data = {
  ["Strike (Ironclad)"] = {
    Cost = 1,
    Color = "Ironclad",
    Type = "Attack",
    Rarity = "Basic",
    Text = "Deal [6|9] damage."
  },
  ["Bloodletting"] = {
    Cost = 0,
    Color = "Ironclad",
    Type = "Skill",
    Rarity = "Uncommon",
    Text = "Lose 3 HP.<br>Gain [@IE@IE|@IE@IE@IE]."
  },
  ["Say \\"Hi\\""] = {
    Cost = 2,
    Color = "Ironclad",
    Type = "Skill",
    Rarity = "Rare",
    Text = "Apply 1 $Vulnerable to {{C2|Someone}}."
  }
}
'''


# ── Lua module parsing ──

def test_parse_lua_table():
    entries = _parse_lua_table(LUA_FIXTURE)
    assert len(entries) == 3
    strike = entries["Strike (Ironclad)"]
    assert strike == {"Cost": 1, "Color": "Ironclad", "Type": "Attack",
                      "Rarity": "Basic", "Text": "Deal [6|9] damage."}
    assert entries['Say "Hi"']["Cost"] == 2


def test_split_wiki_text_alternations_and_icons():
    base, up = _split_wiki_text("Deal [6|9] damage.")
    assert (base, up) == ("Deal 6 damage.", "Deal 9 damage.")
    base, up = _split_wiki_text("Lose 3 HP.<br>Gain [@IE@IE|@IE@IE@IE].")
    assert base == "Lose 3 HP. Gain 2 Energy."
    assert up == "Lose 3 HP. Gain 3 Energy."


def test_wiki_text_keywords_and_templates():
    base, _ = _split_wiki_text("Apply 1 $Vulnerable to {{C2|Someone}}.")
    assert base == "Apply 1 Vulnerable to Someone."
    assert _strip_wiki_templates("procure 1 {{P|Ambergris||2}} now") == "procure 1 Ambergris now"
    assert _strip_char_suffix("Strike (Ironclad)") == "Strike"
    assert _strip_char_suffix("Well-Laid Plans") == "Well-Laid Plans"


def test_wiki_template_form_index_picks_plural():
    """`{{C|sing|plural|2}}` must render the indexed form (Distinguished Cape
    regression: '3 Apparitions' became '3 Apparition' in the 2026-08 scrape)."""
    out = _strip_wiki_templates("add 3 {{C|Apparition|Apparitions|2}} to your Deck")
    assert out == "add 3 Apparitions to your Deck"
    # index pointing at an empty slot falls back to the first non-empty arg
    assert _strip_wiki_templates("{{P|Potion-Shaped Rock||2}}") == "Potion-Shaped Rock"
    # a bare numeric template name is not a form index
    assert _strip_wiki_templates("obtain {{2|potions|Potion}}") == "obtain potions"


def test_wiki_templates_survive_exotic_input():
    """A superscript digit is isdigit() but not int()-parseable; unhandled it
    aborted the whole scrape from inside the re.sub callback."""
    assert _strip_wiki_templates("deal {{C|damage|²}}") == "deal damage"
    # trailing empty field must not defeat the form index
    assert _strip_wiki_templates("{{C|A|B|2|}}") == "B"
    # nested templates render fully rather than leaving literal braces
    assert _strip_wiki_templates("{{P|{{C|Foo}}|2}}") == "Foo"


RELIC_LUA_FIXTURE = '''
local all_data = {
  ["Sozu"] = {
    Description = "Gain @CE at the start of each turn. You can no longer obtain {{2|potions|Potion}}.",
    Rarity = "Ancient"
  }
}
'''


def test_wikigg_relics_convert_icon_runs():
    """Relic descriptions must get the same @-icon rendering as card text
    (regression: 28 relics shipped '@CE' verbatim in the 2026-08 scrape)."""
    src = WikiggSource()
    with patch.object(WikiggSource, "_fetch_modules",
                      return_value={"Module:Relics/StS2 data": RELIC_LUA_FIXTURE}):
        relics = src.fetch_relics()
    assert relics[0]["description"] == (
        "Gain 1 Energy at the start of each turn. You can no longer obtain potions.")


def test_regent_module_is_normalised_to_the_app_spelling():
    """The wiki names the character "The Regent"; config.py, logparser.py and
    every template use "Regent". A leak here splits one character into two
    across the whole app."""
    lua = '''
    local d = {
      ["Royal Decree"] = {
        Cost = 1, Color = "The Regent", Type = "Skill",
        Rarity = "Common", Text = "Do a thing."
      }
    }
    '''
    src = WikiggSource()
    with patch.object(WikiggSource, "_fetch_modules",
                      return_value={"Module:Cards/StS2 data/Regent": lua}):
        cards = src.fetch_cards()
    assert [c["character"] for c in cards] == ["Regent"]


def test_character_falls_back_to_the_module_title():
    """A module entry with no Color field still belongs to the character whose
    page it came from."""
    lua = '["Nameless"] = { Cost = 1, Type = "Skill", Text = "x" }'
    src = WikiggSource()
    with patch.object(WikiggSource, "_fetch_modules",
                      return_value={"Module:Cards/StS2 data/Defect": lua}):
        cards = src.fetch_cards()
    assert cards[0]["character"] == "Defect"


class TestWikiggFetchModules:
    """The MediaWiki API call itself: batching, the response cap, and the
    shape-tolerance that keeps one odd page from aborting a whole scrape.
    """

    @staticmethod
    def _response(payload):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode("utf-8")
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        return resp

    def _page(self, title, content):
        return {"title": title,
                "revisions": [{"slots": {"main": {"content": content}}}]}

    def test_titles_are_requested_in_batches_of_three(self):
        """Six modules in one request would be a single oversized response and
        a heavier hit on the wiki; the delay between batches is the politeness
        the scrape depends on."""
        titles = [f"Module:{i}" for i in range(7)]
        responses = [
            self._response({"query": {"pages": [
                self._page(t, f"content {t}") for t in titles[i:i + 3]]}})
            for i in range(0, 7, 3)
        ]
        with patch("sts2.sources.urllib.request.urlopen", side_effect=responses) \
                as urlopen, patch("sts2.sources.time.sleep") as sleep:
            got = WikiggSource()._fetch_modules(titles)
        assert urlopen.call_count == 3
        assert sleep.call_count == 2          # between batches, not before the first
        assert len(got) == 7
        assert got["Module:0"] == "content Module:0"

    def test_an_oversized_response_is_refused(self):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.read.return_value = b"x" * 11
        resp.__enter__ = lambda s: s
        resp.__exit__ = MagicMock(return_value=False)
        with patch("sts2.sources._MAX_RESPONSE_SIZE", 10), \
             patch("sts2.sources.urllib.request.urlopen", return_value=resp), \
             pytest.raises(urllib.error.URLError, match="too large"):
            WikiggSource()._fetch_modules(["Module:X"])

    def test_a_page_with_no_revisions_is_skipped_not_fatal(self):
        payload = {"query": {"pages": [
            {"title": "Module:Missing"},
            self._page("Module:Real", "content"),
        ]}}
        with patch("sts2.sources.urllib.request.urlopen",
                   return_value=self._response(payload)):
            got = WikiggSource()._fetch_modules(["Module:Missing", "Module:Real"])
        assert got == {"Module:Real": "content"}

    def test_an_empty_query_result_yields_nothing(self):
        with patch("sts2.sources.urllib.request.urlopen",
                   return_value=self._response({})):
            assert WikiggSource()._fetch_modules(["Module:X"]) == {}


def test_icon_runs_cover_the_tokens_the_wiki_actually_emits():
    """Token vocabulary counted across the live card/relic/potion modules:
    @CE @DE @IE @SE @NE (energy), @ST (star), @Gold. An earlier pattern was
    written for an invented "@?S" star token, so @ST and @Gold passed through
    verbatim and 58 shipped descriptions read "gain @ST@ST@ST".
    """
    from sts2.sources import _convert_icon_runs
    for token in ("@CE", "@DE", "@IE", "@SE", "@NE"):
        assert _convert_icon_runs(f"Gain {token}.") == "Gain 1 Energy."
    assert _convert_icon_runs("gain @ST@ST@ST.") == "gain 3 Star."
    assert _convert_icon_runs("Gain 300 @Gold.") == "Gain 300 Gold."
    # a digit prefix is the value; repetition is the value without one
    assert _convert_icon_runs("Gain 2 @CE") == "Gain 2 Energy"
    assert _convert_icon_runs("Gain @CE@CE") == "Gain 2 Energy"
    # runs of different units sit flush together in the source
    assert _convert_icon_runs("Gain @CE@ST now") == "Gain 1 Energy 1 Star now"
    # the digit prefix must not reach across a line break
    assert _convert_icon_runs("Deal 3\n@CE@CE") == "Deal 3\n2 Energy"


def test_merge_preserves_curated_categories(tmp_path, monkeypatch):
    """Sources file Curse/Status/Token/Event/Quest cards under Colorless; a
    scrape must never overwrite these app-curated categories (regression:
    the 2026-08 scrape flattened all 76 pseudo-category cards to Colorless)."""
    from sts2 import fetcher
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    existing = [
        _card("Guilty", character="Curse"),
        _card("Burn", character="Status"),
        _card("Alpha", character="Colorless"),
    ]
    (tmp_path / "cards.json").write_text(json.dumps(existing))
    incoming = [
        _card("Guilty", character="Colorless", description="new guilty text"),
        _card("Burn", character="Colorless"),
        _card("Alpha", character="Ironclad"),
    ]
    merged = {c["name"]: c for c in fetcher._merge_with_existing("cards.json", incoming)}
    assert merged["Guilty"]["character"] == "Curse"
    assert merged["Guilty"]["description"] == "new guilty text"  # other fields still update
    assert merged["Burn"]["character"] == "Status"
    assert merged["Alpha"]["character"] == "Ironclad"  # real characters still update


def test_wikigg_fetch_cards_from_fixture():
    src = WikiggSource()
    with patch.object(WikiggSource, "_fetch_modules",
                      return_value={"Module:Cards/StS2 data/Ironclad": LUA_FIXTURE}):
        cards = src.fetch_cards()
    by_name = {c["name"]: c for c in cards}
    assert by_name["Strike"]["rarity"] == "Starter"  # Basic -> Starter
    assert by_name["Strike"]["description"] == "Deal 6 damage."
    assert by_name["Strike"]["description_upgraded"] == "Deal 9 damage."
    assert by_name["Bloodletting"]["description"] == "Lose 3 HP. Gain 2 Energy."
    assert by_name["Bloodletting"]["cost"] == "0"


# ── orchestrator: fallback + provenance (G1 source-kill test) ──

def _run_orchestrator(tmp_path, monkeypatch, primary_result, secondary_result):
    """Run run_fetcher's web phase against stubbed sources + tmp DATA_DIR."""
    import urllib.error

    from sts2 import fetcher
    monkeypatch.setattr(fetcher, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fetcher, "_SCRAPE_DELAY", 0)
    monkeypatch.setattr(
        fetcher, "_discover_enemies_from_saves", lambda: [], raising=True
    )
    monkeypatch.setattr(
        fetcher, "_discover_events_from_saves", lambda: [], raising=True
    )

    class Stub:
        def __init__(self, name, result):
            self.name = name
            self._result = result

        def _get(self):
            if isinstance(self._result, Exception):
                raise self._result
            return [dict(r) for r in self._result]

        def fetch_cards(self):
            return self._get()

        def fetch_relics(self):
            return []

        def fetch_potions(self):
            return []

    import sts2.sources as sources_mod
    monkeypatch.setattr(
        sources_mod, "Sts2ggSource",
        lambda: Stub("primary.example", primary_result),
    )
    monkeypatch.setattr(
        sources_mod, "WikiggSource",
        lambda: Stub("secondary.example", secondary_result),
    )
    _ = urllib.error  # imported for parity with fetcher error handling
    fetcher.run_fetcher(save_only=False)
    path = tmp_path / "cards.json"
    return json.loads(path.read_text()) if path.exists() else []


def _card(name, **kw):
    d = {"id": f"CARD.{name.upper()}", "name": name, "character": "Ironclad",
         "cost": "1", "type": "Attack", "rarity": "Common",
         "description": f"{name} desc", "description_upgraded": "",
         "keywords": []}
    d.update(kw)
    return d


def test_orchestrator_primary_wins_secondary_fills_gaps(tmp_path, monkeypatch):
    cards = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Alpha"), _card("Beta")],
        secondary_result=[_card("Alpha", description="wiki alpha"), _card("Gamma")],
    )
    by_name = {c["name"]: c for c in cards}
    assert set(by_name) == {"Alpha", "Beta", "Gamma"}
    assert by_name["Alpha"]["description"] == "Alpha desc"  # primary wins
    assert by_name["Alpha"]["fetched_from"] == "primary.example"
    assert by_name["Gamma"]["fetched_from"] == "secondary.example"  # gap-filled
    assert by_name["Gamma"]["fetched_at"]  # provenance stamped on new records


def test_orchestrator_falls_back_when_primary_dead(tmp_path, monkeypatch):
    import urllib.error
    cards = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=urllib.error.URLError("connection refused"),
        secondary_result=[_card("Alpha"), _card("Beta")],
    )
    assert {c["name"] for c in cards} == {"Alpha", "Beta"}
    assert all(c["fetched_from"] == "secondary.example" for c in cards)


def test_orchestrator_keeps_existing_when_all_sources_dead(tmp_path, monkeypatch):
    existing = [_card("Keeper")]
    (tmp_path / "cards.json").write_text(json.dumps(existing))
    cards = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=RuntimeError("markup drift"),
        secondary_result=[],
    )
    assert [c["name"] for c in cards] == ["Keeper"]


def test_provenance_moves_only_on_content_change(tmp_path, monkeypatch):
    first = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Alpha")], secondary_result=[],
    )
    stamp = first[0]["fetched_at"]
    assert stamp
    # Same content again: stamp must not churn
    again = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Alpha")], secondary_result=[],
    )
    assert again[0]["fetched_at"] == stamp
    # Changed content: stamp moves (same date here, but source is recorded)
    changed = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Alpha", description="new text")],
        secondary_result=[],
    )
    assert changed[0]["description"] == "new text"
    assert changed[0]["fetched_from"] == "primary.example"


# ── data-bundle updater ──

def test_parse_data_tag():
    assert updater._parse_data_tag("data-v2026.07.22") == "2026-07-22"
    assert updater._parse_data_tag("v2.10.0") == ""
    assert updater._parse_data_tag("data-v2026.7.2") == ""


def _release(tag, tarball="https://github.com/x/y/releases/a.tar.gz",
             sha="https://github.com/x/y/releases/a.sha256"):
    return {"tag_name": tag, "assets": [
        {"name": "spirescope-data.tar.gz", "browser_download_url": tarball},
        {"name": "spirescope-data.sha256", "browser_download_url": sha},
    ]}


def test_data_update_check_detects_newer(tmp_path, monkeypatch):
    (tmp_path / "last_updated.txt").write_text("2026-07-01T00:00:00+00:00")
    monkeypatch.setattr("sts2.config.DATA_DIR", tmp_path)
    releases = [_release("v2.10.0"), _release("data-v2026.07.22"),
                _release("data-v2026.06.01")]

    captured = {}

    def fake_thread(target, daemon):
        class T:
            def start(self):
                target()
        captured["ran"] = True
        return T()

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps(releases).encode()

    monkeypatch.setattr(updater.threading, "Thread",
                        lambda target, daemon: fake_thread(target, daemon))
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: FakeResp())
    monkeypatch.setattr(updater, "update_checks_enabled", lambda: True)
    updater._data_update = None
    updater.check_for_data_update()
    info = updater.get_data_update_info()
    assert info and info["tag"] == "data-v2026.07.22"
    updater._data_update = None


def test_data_update_check_skips_when_current(tmp_path, monkeypatch):
    (tmp_path / "last_updated.txt").write_text("2026-07-22T20:00:00+00:00")
    monkeypatch.setattr("sts2.config.DATA_DIR", tmp_path)

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self):
            return json.dumps([_release("data-v2026.07.22")]).encode()

    class T:
        def __init__(self, target, daemon):
            self.target = target

        def start(self):
            self.target()

    monkeypatch.setattr(updater.threading, "Thread", T)
    monkeypatch.setattr(updater.urllib.request, "urlopen",
                        lambda req, timeout: FakeResp())
    monkeypatch.setattr(updater, "update_checks_enabled", lambda: True)
    updater._data_update = None
    updater.check_for_data_update()
    assert updater.get_data_update_info() is None


def _make_bundle(tmp_path: Path, cards) -> tuple[Path, str]:
    src = tmp_path / "bundle-src" / "data"
    src.mkdir(parents=True)
    (src / "cards.json").write_text(json.dumps(cards))
    # The install gate validates the complete dataset before promoting: every
    # required file must parse, hold identified records, and the whole
    # directory must load as a KnowledgeBase. Empty families fail that on
    # purpose, so ship one real record each.
    (src / "relics.json").write_text(
        json.dumps([{"id": "RELIC.BURNING_BLOOD", "name": "Burning Blood"}]))
    (src / "potions.json").write_text(
        json.dumps([{"id": "POTION.FIRE", "name": "Fire Potion"}]))
    (src / "enemies.json").write_text(
        json.dumps([{"id": "ENCOUNTER.JAW_WORM", "name": "Jaw Worm"}]))
    (src / "events.json").write_text(
        json.dumps([{"id": "EVENT.NEOW", "name": "Neow"}]))
    (src / "patches.json").write_text(
        json.dumps([{"patch": "v0.110.0", "date": "2026-07-31"}]))
    (src / "last_updated.txt").write_text("2026-07-22T20:00:00+00:00")
    bundle = tmp_path / "data.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        tf.add(src, arcname="data")
    return bundle, hashlib.sha256(bundle.read_bytes()).hexdigest()


def test_install_data_update_swaps_atomically(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    (data_dir / "mods").mkdir(parents=True)
    (data_dir / "cards.json").write_text(json.dumps([_card("Old")]))
    (data_dir / "mods" / "local.json").write_text("{}")
    bundle, digest = _make_bundle(tmp_path, [_card("New")])

    import contextlib
    import io

    @contextlib.contextmanager
    def _wrap_bytes(data):
        yield io.BytesIO(data)

    def fake_urlopen(req, timeout):
        data = (bundle.read_bytes() if req.full_url.endswith(".tar.gz")
                else f"{digest}  data.tar.gz".encode())
        return _wrap_bytes(data)

    monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    # The fixture ships one card; the real >=400 floor is exercised by
    # test_updater's validation-gate tests.
    monkeypatch.setattr(updater, "_MIN_CARDS", 1)
    updater._data_update = {
        "tag": "data-v2026.07.22", "date": "2026-07-22",
        "tarball": "https://github.com/x/y/data.tar.gz",
        "sha256": "https://github.com/x/y/data.sha256",
    }
    ok, msg = updater.install_data_update()
    assert ok, msg
    cards = json.loads((data_dir / "cards.json").read_text())
    assert cards[0]["name"] == "New"
    assert (data_dir / "mods" / "local.json").exists()  # local files preserved
    assert not (tmp_path / "data.old").exists()


def test_install_rejects_bad_checksum(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "cards.json").write_text(json.dumps([_card("Old")]))
    bundle, _digest = _make_bundle(tmp_path, [_card("Evil")])

    import contextlib
    import io

    @contextlib.contextmanager
    def _wrap_bytes(data):
        yield io.BytesIO(data)

    def fake_urlopen(req, timeout):
        url = req.full_url
        data = bundle.read_bytes() if url.endswith(".tar.gz") else b"deadbeef  data.tar.gz"
        return _wrap_bytes(data)

    monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
    monkeypatch.setattr(updater.urllib.request, "urlopen", fake_urlopen)
    updater._data_update = {
        "tag": "data-v2026.07.22", "date": "2026-07-22",
        "tarball": "https://github.com/x/y/data.tar.gz",
        "sha256": "https://github.com/x/y/data.sha256",
    }
    ok, msg = updater.install_data_update()
    assert not ok and "Checksum" in msg
    # existing data untouched
    assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Old"
    updater._data_update = None


def test_gap_fill_skips_rename_shadow(tmp_path, monkeypatch):
    """A lagging secondary listing a renamed entity under its old name must
    not resurrect it (the generated id collides with the current record)."""
    primary = [_card("Scare", id="CARD.FOLLOW_THROUGH")]
    secondary = [_card("Follow Through", id="CARD.FOLLOW_THROUGH")]
    cards = _run_orchestrator(tmp_path, monkeypatch,
                              primary_result=primary,
                              secondary_result=secondary)
    assert [c["name"] for c in cards] == ["Scare"]


def test_shipped_data_has_no_test_fixtures():
    """Mock fixtures must never reach shipped data — they are searchable,
    get live detail pages, and inflate the card totals.

    Deliberately keyed on the MOCK id marker, not on empty rarity: 19 real
    cards (Shiny Strike, Chrysalis, ...) ship with a blank rarity because the
    wiki source has no value for them.
    """
    from sts2.config import DATA_DIR

    for name in ("cards.json", "relics.json", "potions.json", "enemies.json"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        entries = json.loads(path.read_text(encoding="utf-8"))
        offenders = [e.get("id", "") for e in entries if "MOCK" in e.get("id", "").upper()]
        assert not offenders, f"{name} ships test fixtures: {offenders}"


def test_shipped_enemies_all_validate():
    """Every shipped enemy must construct as an Enemy model. KnowledgeBase
    skips malformed entries with only a warning, so a shape regression
    (e.g. int acts instead of 'Act N' strings) silently drops enemies."""
    from sts2.config import DATA_DIR
    from sts2.models import Enemy

    path = DATA_DIR / "enemies.json"
    entries = json.loads(path.read_text(encoding="utf-8"))
    bad = []
    for d in entries:
        try:
            Enemy(**d)
        except Exception as exc:
            bad.append(f"{d.get('id')}: {exc}")
    assert not bad, "malformed shipped enemies:\n" + "\n".join(bad[:5])
    assert len(entries) >= 184


def test_shipped_descriptions_are_clean():
    """DATA_MAINTENANCE.md states tests enforce this; this is that test.

    Descriptions must be single-line, single-spaced, and free of unresolved
    "{Name:...}" template tokens. The fetcher normalises all three, but nothing
    checked the result that actually ships, so a regression in _clean_description
    would only surface as broken layout on a live page.
    """
    import re

    from sts2.config import DATA_DIR

    # Every markup form any source emits: template tokens, colour tags, the
    # @-icon vocabulary, and <br> breaks. Written against what the modules
    # actually contain — a narrower guess let 58 descriptions ship with raw
    # "@ST" and "@Gold" while this test stayed green.
    token = re.compile(r"\{\w+:|\[/?(?:gold|blue|red|green)\]|@[A-Za-z]|<br\s*/?>")
    offenders = []
    for name in ("cards.json", "relics.json", "potions.json", "events.json"):
        path = DATA_DIR / name
        if not path.exists():
            continue
        for entry in json.loads(path.read_text(encoding="utf-8")):
            if not isinstance(entry, dict):
                continue
            for key, value in entry.items():
                if not isinstance(value, str) or "description" not in key:
                    continue
                if "\n" in value or "  " in value or token.search(value):
                    offenders.append(f"{name}:{entry.get('id')}.{key}: {value!r}")
    assert not offenders, "unclean shipped descriptions:\n" + "\n".join(offenders[:10])


def test_enemy_hp_uses_one_field_name():
    """Every template reads `hp_range`; two entries carried `hp` instead, so
    any value in them could never render. Keep the schema single-valued."""
    from sts2.config import DATA_DIR

    entries = json.loads((DATA_DIR / "enemies.json").read_text(encoding="utf-8"))
    stray = [e.get("id") for e in entries if "hp" in e]
    assert not stray, f"entries use 'hp' instead of 'hp_range': {stray}"
    missing_field = [e.get("id") for e in entries if "hp_range" not in e]
    assert not missing_field, f"entries have no hp_range field at all: {missing_field}"


def test_gap_filled_description_re_derives_keywords(tmp_path, monkeypatch):
    """Keywords are derived from the description, so text arriving via gap-fill
    must re-derive them or the card ships as a synergy orphan the deck
    analyser cannot see."""
    cards = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Blank", description="", keywords=[])],
        secondary_result=[_card("Blank", description="Gain 5 Block. Exhaust.")],
    )
    blank = next(c for c in cards if c["name"] == "Blank")
    assert blank["description"] == "Gain 5 Block. Exhaust."
    assert set(blank["keywords"]) == {"Block", "Exhaust"}


def test_gap_fill_adopts_upgraded_text_even_when_primary_had_a_description(
        tmp_path, monkeypatch):
    """The upgraded-text fill used to be nested inside the "no description"
    branch, so a card whose primary text existed never picked up the
    secondary's upgraded text."""
    cards = _run_orchestrator(
        tmp_path, monkeypatch,
        primary_result=[_card("Both", description="Deal 6 damage.",
                              description_upgraded="")],
        secondary_result=[_card("Both", description="Deal 6 damage.",
                                description_upgraded="Deal 9 damage.")],
    )
    both = next(c for c in cards if c["name"] == "Both")
    assert both["description"] == "Deal 6 damage."
    assert both["description_upgraded"] == "Deal 9 damage."
