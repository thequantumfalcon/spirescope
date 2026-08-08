"""P5 enchantment visibility: parsing from run history and current-run saves."""
import json
from unittest.mock import patch

from sts2.saves import get_current_run, get_run_history

ENCHANTED_DECK = [
    {"id": "CARD.STRIKE_NECROBINDER", "floor_added_to_deck": 1,
     "enchantment": {"amount": 1, "id": "ENCHANTMENT.TEZCATARAS_EMBER"}},
    {"id": "CARD.DEFEND_NECROBINDER", "upgrade_count": 1},
    {"id": "CARD.REAP"},
]

RUN_JSON = {
    "win": True,
    "ascension": 2,
    "seed": "ABCDEF123456",
    "build_id": "v0.109.0",
    "players": [{"character": "CHAR.NECROBINDER", "deck": ENCHANTED_DECK,
                 "relics": []}],
    "map_point_history": [],
}

CURRENT_RUN_JSON = {
    "players": [{"character_id": "CHARACTER.NECROBINDER",
                 "current_hp": 50, "max_hp": 70, "gold": 100,
                 "deck": ENCHANTED_DECK, "relics": [], "potions": []}],
    "current_act_index": 0,
    "run_time": 300,
}


def test_run_history_parses_enchantments(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    (history / "1000.run").write_text(json.dumps(RUN_JSON))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert runs[0].enchantments == {
        "CARD.STRIKE_NECROBINDER": "ENCHANTMENT.TEZCATARAS_EMBER"
    }


def test_run_history_no_enchantments_is_empty_dict(tmp_path):
    history = tmp_path / "history"
    history.mkdir()
    plain = dict(RUN_JSON)
    plain["players"] = [{"character": "CHAR.IRONCLAD",
                         "deck": [{"id": "CARD.BASH"}], "relics": []}]
    (history / "1000.run").write_text(json.dumps(plain))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert runs[0].enchantments == {}


def test_current_run_parses_deck_enchantments(tmp_path):
    (tmp_path / "current_run.save").write_text(json.dumps(CURRENT_RUN_JSON))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        run = get_current_run()
    assert run.active
    assert run.deck == ["CARD.STRIKE_NECROBINDER", "CARD.DEFEND_NECROBINDER",
                        "CARD.REAP"]
    assert run.deck_enchantments == ["ENCHANTMENT.TEZCATARAS_EMBER", "", ""]
    assert run.deck_upgrades == [False, True, False]


# ── P8: badges + epoch deprecation ──

def test_get_progress_aggregates_badges(tmp_path):
    progress = {
        "total_playtime": 100,
        "character_stats": [
            {"id": "CHARACTER.IRONCLAD", "badges": [
                {"count": 2, "id": "ELITE", "rarity": "bronze"},
                {"count": 1, "id": "HEALER", "rarity": "gold"},
            ]},
            {"id": "CHARACTER.SILENT", "badges": [
                {"count": 3, "id": "ELITE", "rarity": "bronze"},
            ]},
        ],
    }
    (tmp_path / "progress.save").write_text(json.dumps(progress))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        from sts2.saves import get_progress
        p = get_progress()
    assert p.badges == {"ELITE": {"bronze": 5}, "HEALER": {"gold": 1}}


def test_discover_badges_from_saves(tmp_path):
    from sts2.fetcher import _discover_badges_from_saves
    progress = {"character_stats": [{"id": "CHARACTER.IRONCLAD", "badges": [
        {"count": 1, "id": "BIG_DECK", "rarity": "silver"}]}]}
    (tmp_path / "progress.save").write_text(json.dumps(progress))
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "badges.json").write_text("[]")
    with patch("sts2.config.SAVE_DIR", tmp_path), \
         patch("sts2.fetcher.DATA_DIR", data_dir):
        found = _discover_badges_from_saves()
    assert found == [{"id": "BADGE.BIG_DECK", "name": "Big Deck",
                      "requirement": "", "source": "discovered"}]


def test_deprecated_epochs_never_suggested():
    from sts2.models import Epoch
    active = Epoch(id="EPOCH.A", name="A")
    dead = Epoch(id="EPOCH.B", name="B", status="deprecated")
    # mirror the routes.py suggestion predicate
    obtained = set()
    suggestable = [e for e in (active, dead)
                   if e.id not in obtained and e.status != "deprecated"]
    assert suggestable == [active]


# ── P10: i18n language persistence + fallback ──

def test_i18n_zht_translates_and_falls_back():
    from sts2.i18n import get_translator
    t = get_translator("zht")
    assert t("nav.cards") == "卡牌"
    assert t("settings.language") == "語言"
    # Missing key falls back to English, then to the key itself
    assert t("nav.live_run") == "即時戰局"
    assert t("no.such.key") == "no.such.key"


def test_language_persistence_round_trip(tmp_path, monkeypatch):
    from sts2 import i18n
    monkeypatch.delenv("STS2_LANG", raising=False)
    monkeypatch.setattr(i18n, "_settings_path", lambda: tmp_path / "settings.json")
    assert i18n.get_language() == "en"
    assert i18n.set_language("zht") is True
    assert i18n.get_language() == "zht"
    assert i18n.set_language("klingon") is False  # unknown locale rejected
    assert i18n.get_language() == "zht"
    # env var wins over the persisted setting
    monkeypatch.setenv("STS2_LANG", "en")
    assert i18n.get_language() == "en"


def test_available_languages_lists_locales():
    from sts2.i18n import available_languages
    codes = {lang["code"] for lang in available_languages()}
    assert {"en", "zht"} <= codes


# ── content overlays: official game text swapped in at KB load ──

def _stub_content_locale(tmp_path, monkeypatch, code, payload):
    """Point i18n at a temp locales dir holding one content overlay."""
    import json as _json

    from sts2 import i18n
    locales = tmp_path / "locales"
    (locales / "content").mkdir(parents=True)
    # locale file must exist for set_language/available_languages semantics
    (locales / f"{code}.json").write_text(
        _json.dumps({"_meta": {"language": code}, "nav": {"cards": "x"}}),
        encoding="utf-8")
    (locales / "content" / f"{code}.json").write_text(
        _json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(i18n, "_LOCALES_DIR", locales)
    monkeypatch.setattr(i18n, "_cache", {})
    monkeypatch.setattr(i18n, "_content_cache", {})
    monkeypatch.setenv("STS2_LANG", code)


def test_content_overlay_translates_kb_and_search(tmp_path, monkeypatch):
    from sts2.knowledge import KnowledgeBase
    _stub_content_locale(tmp_path, monkeypatch, "ja", {
        "cards": {"CARD.BASH": {"name": "バッシュ", "description": "テスト説明"}},
    })
    kb = KnowledgeBase()
    bash = next(c for c in kb.cards if c.id == "CARD.BASH")
    assert bash.name == "バッシュ"
    assert bash.description == "テスト説明"
    # untranslated entities keep English (per-entity fallback)
    strike = next(c for c in kb.cards if c.id == "CARD.STRIKE_IRONCLAD")
    assert strike.name == "Strike"
    # search index was built from overlaid names
    results = kb.search("バッシュ")
    assert any(c.id == "CARD.BASH" for c in results["cards"])


def test_content_overlay_absent_is_noop(tmp_path, monkeypatch):
    from sts2 import i18n
    monkeypatch.setenv("STS2_LANG", "en")
    monkeypatch.setattr(i18n, "_content_cache", {})
    from sts2.knowledge import KnowledgeBase
    kb = KnowledgeBase()
    bash = next(c for c in kb.cards if c.id == "CARD.BASH")
    assert bash.name == "Bash"


def test_overlay_keeps_english_name_for_english_keyed_joins(tmp_path, monkeypatch):
    """community.json and strategy.json are keyed by English names, so a
    translated entity must remember its English name or community tips and
    archetype detection silently vanish in every non-English locale."""
    from sts2.knowledge import KnowledgeBase
    _stub_content_locale(tmp_path, monkeypatch, "ja", {
        "cards": {"CARD.BASH": {"name": "バッシュ"}},
    })
    kb = KnowledgeBase()
    bash = next(c for c in kb.cards if c.id == "CARD.BASH")
    assert bash.name == "バッシュ" and bash.name_en == "Bash"
    assert kb.english_name(bash) == "Bash"
    # untranslated entities report their own name
    strike = next(c for c in kb.cards if c.id == "CARD.STRIKE_IRONCLAD")
    assert kb.english_name(strike) == strike.name


def test_overlay_ignores_malformed_entries(tmp_path, monkeypatch):
    """setattr bypasses pydantic validation, so a bad overlay value would
    only detonate later inside index building — and KnowledgeBase() runs at
    app import, taking the whole server down for that locale."""
    from sts2.knowledge import KnowledgeBase
    _stub_content_locale(tmp_path, monkeypatch, "ja", {
        "cards": {
            "CARD.BASH": {"name": ["not", "a", "string"]},
            "CARD.STRIKE_IRONCLAD": "not an object",
        },
        "relics": "not an object",
    })
    kb = KnowledgeBase()  # must not raise
    assert next(c for c in kb.cards if c.id == "CARD.BASH").name == "Bash"


def test_overlay_read_failure_is_not_cached(tmp_path, monkeypatch):
    """A transient read error must not pin the locale to English until the
    process restarts."""
    from sts2 import i18n
    _stub_content_locale(tmp_path, monkeypatch, "ja", {
        "cards": {"CARD.BASH": {"name": "バッシュ"}},
    })
    target = tmp_path / "locales" / "content" / "ja.json"
    real_read = i18n.Path.read_text

    def flaky(self, *a, **kw):
        if self == target:
            raise OSError("locked by another process")
        return real_read(self, *a, **kw)

    monkeypatch.setattr(i18n.Path, "read_text", flaky)
    assert i18n.load_content_overlay("ja") == {}
    monkeypatch.setattr(i18n.Path, "read_text", real_read)
    assert i18n.load_content_overlay("ja")["cards"]["CARD.BASH"]["name"] == "バッシュ"


async def test_settings_language_post_round_trip(client, tmp_path, monkeypatch):
    """No test exercised this route, so a NameError in it shipped green.

    Covers the whole handler: CSRF rejection, unknown-locale rejection, and
    the success path that swaps the translator and rebuilds the KB.
    """
    from sts2 import i18n
    from sts2.app import generate_csrf_token
    monkeypatch.setattr(i18n, "_settings_path", lambda: tmp_path / "settings.json")

    resp = await client.post("/settings/language",
                             data={"language": "zht", "csrf_token": "bad"})
    assert resp.status_code == 403

    resp = await client.post(
        "/settings/language",
        data={"language": "klingon", "csrf_token": generate_csrf_token()})
    assert resp.status_code == 400

    resp = await client.post(
        "/settings/language",
        data={"language": "zht", "csrf_token": generate_csrf_token()},
        follow_redirects=False)
    assert resp.status_code == 303
    assert "saved=1" in resp.headers["location"]


def test_language_codes_reject_path_fragments(tmp_path, monkeypatch):
    """'content/de' is 10 chars and resolves to the overlay directory, so it
    would persist as a language the settings page cannot represent."""
    from sts2 import i18n
    monkeypatch.delenv("STS2_LANG", raising=False)
    monkeypatch.setattr(i18n, "_settings_path", lambda: tmp_path / "settings.json")
    for bad in ("content/de", "content\\de", "../config", "DE", "e n"):
        assert i18n.set_language(bad) is False
        assert i18n.load_content_overlay(bad) == {}
    assert i18n.set_language("zht") is True


async def test_settings_page_renders_in_zht(client):
    from sts2.app import templates
    from sts2.i18n import get_translator
    old = templates.env.globals["t"]
    templates.env.globals["t"] = get_translator("zht")
    try:
        resp = await client.get("/settings")
    finally:
        templates.env.globals["t"] = old
    assert resp.status_code == 200
    assert "設定" in resp.text  # zh-TW chrome
    assert "語言" in resp.text
    assert "卡牌" in resp.text  # nav in zh-TW too
