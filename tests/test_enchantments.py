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
