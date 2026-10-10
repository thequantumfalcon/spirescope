"""/deck?from_run=live preloads the local player's deck, not seat 0's.

/live, /overlay and the live stream all read the local player (matched by
the SteamID in the save path); the deck analyser asked for seat 0, which in
co-op is the host, so a player who joined someone else's lobby got the
teammate's deck.
"""
import html
import json
import re

import pytest

from sts2 import app as app_module
from sts2 import saves

_HOST = "76561198000000001"
_LOCAL = "76561198000000002"


@pytest.fixture
def coop_run_as_guest(tmp_path, monkeypatch):
    save_dir = tmp_path / "steam" / _LOCAL / "profile1" / "saves"
    save_dir.mkdir(parents=True)
    run = {"players": [
        {"id": _HOST, "character_id": "CHARACTER.IRONCLAD", "current_hp": 70,
         "max_hp": 80, "deck": [{"id": "CARD.BASH"}, {"id": "CARD.STRIKE_IRONCLAD"}]},
        {"id": _LOCAL, "character_id": "CHARACTER.SILENT", "current_hp": 60,
         "max_hp": 70, "deck": [{"id": "CARD.NEUTRALIZE"}, {"id": "CARD.SURVIVOR"}]},
    ]}
    (save_dir / "current_run_mp.save").write_text(json.dumps(run), encoding="utf-8")
    monkeypatch.setattr(saves, "SAVE_DIR", save_dir)
    monkeypatch.setattr(saves, "SAVE_DIRS", [save_dir])

    async def no_log():
        return None

    monkeypatch.setattr(app_module, "_poll_game_log_once", no_log)


def _selected(page: str) -> list[str]:
    match = re.search(r"data-selected='([^']*)'", page)
    assert match, "deck page carries no preloaded selection"
    return json.loads(html.unescape(match.group(1)))


async def test_the_live_deck_is_the_local_players(client, coop_run_as_guest):
    resp = await client.get("/deck", params={"from_run": "live"})
    assert resp.status_code == 200
    assert _selected(resp.text) == ["CARD.NEUTRALIZE", "CARD.SURVIVOR"]


async def test_the_live_view_and_the_deck_agree_on_the_player(client, coop_run_as_guest):
    live = (await client.get("/api/live")).json()
    deck = await client.get("/deck", params={"from_run": "live"})
    assert live["deck"] == _selected(deck.text)
