"""P1 data pipeline: source adapters, fallback, provenance, data-bundle updates."""
import hashlib
import json
import tarfile
from pathlib import Path
from unittest.mock import patch

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
