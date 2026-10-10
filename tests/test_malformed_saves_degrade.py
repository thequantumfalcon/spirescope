"""A save file with an unexpected shape degrades to "no current run" or "no
progress" instead of failing every page that reads it.

get_run_history already skipped a bad run file and kept the rest, but
get_current_run and get_progress had no guard: one value of the wrong type
anywhere in the file raised out of them, and /, /cards, /collections,
/epochs, /live, /overlay and /api/live answered 500 until the game rewrote
the file.
"""
import json
import logging

import pytest

from sts2 import app as app_module
from sts2 import saves
from sts2.models import CurrentRun
from sts2.saves import get_current_run, get_progress


def _player(**overrides):
    player = {"id": 1, "character_id": "CHARACTER.IRONCLAD", "current_hp": 60,
              "max_hp": 80, "gold": 99, "deck": [{"id": "CARD.BASH"}],
              "relics": [], "potions": []}
    player.update(overrides)
    return player


_BAD_CURRENT_RUNS = {
    "players not a list": {"players": {"id": 1}},
    "deck entry not an object": {"players": [_player(deck=["CARD.BASH"])]},
    "value the model rejects": {"players": [_player(current_hp="plenty")]},
    "floor history not a list of lists": {"players": [_player()],
                                          "map_point_history": [5]},
}

_BAD_PROGRESS = {
    "character stats not objects": {"character_stats": [1, 2]},
    "card stats a string": {"card_stats": "CARD.BASH"},
    "value the model rejects": {"total_playtime": "forever"},
    "epochs not objects": {"epochs": ["NEOW_EPOCH"]},
}


@pytest.fixture
def save_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(saves, "SAVE_DIR", tmp_path)
    monkeypatch.setattr(saves, "SAVE_DIRS", [tmp_path])
    return tmp_path


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


@pytest.mark.parametrize("data", _BAD_CURRENT_RUNS.values(), ids=_BAD_CURRENT_RUNS.keys())
def test_a_malformed_current_run_reads_as_no_run(save_dir, caplog, data):
    _write(save_dir / "current_run.save", data)
    with caplog.at_level(logging.WARNING, logger="sts2.saves"):
        run = get_current_run()
    assert run == CurrentRun(active=False)
    assert "current_run.save" in caplog.text


@pytest.mark.parametrize("data", [[{"players": []}], "a string", 7],
                         ids=["list", "string", "number"])
def test_a_save_that_is_not_a_json_object_is_ignored(save_dir, caplog, data):
    _write(save_dir / "current_run.save", data)
    _write(save_dir / "current_run.save.backup", data)
    _write(save_dir / "progress.save", data)
    with caplog.at_level(logging.WARNING, logger="sts2.saves"):
        assert get_current_run() == CurrentRun(active=False)
        assert get_progress() is None
    assert "not a JSON object" in caplog.text


def test_a_well_formed_run_still_reads_in_full(save_dir):
    """The guard only catches failures; a good save parses as before."""
    _write(save_dir / "current_run.save", {"players": [_player()]})
    run = get_current_run()
    assert run.active and run.character == "Ironclad"
    assert run.current_hp == 60 and run.deck == ["CARD.BASH"]


@pytest.mark.parametrize("data", _BAD_PROGRESS.values(), ids=_BAD_PROGRESS.keys())
def test_malformed_progress_reads_as_no_progress(save_dir, caplog, data):
    _write(save_dir / "progress.save", data)
    with caplog.at_level(logging.WARNING, logger="sts2.saves"):
        assert get_progress() is None
    assert "progress.save" in caplog.text


@pytest.mark.parametrize("value", [None, "2026-03-07", 1.5, True])
def test_an_epoch_date_that_is_not_an_integer_reads_as_no_date(save_dir, value):
    _write(save_dir / "progress.save",
           {"epochs": [{"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": value}]})
    progress = get_progress()
    assert progress is not None
    assert progress.epochs == [{"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": 0}]


def test_an_integer_epoch_date_is_kept(save_dir):
    _write(save_dir / "progress.save",
           {"epochs": [{"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": 1772861383}]})
    assert get_progress().epochs[0]["obtain_date"] == 1772861383


# ------------------------------------------------------------ the pages

@pytest.fixture
def uncached_saves(save_dir, monkeypatch):
    """Route the app's progress and live-run reads straight to the tmp saves,
    without the module caches that would carry the result into other tests."""
    async def progress():
        return get_progress()

    async def runs():
        return []

    async def no_log():
        return None

    monkeypatch.setattr(app_module, "_get_progress", progress)
    monkeypatch.setattr(app_module, "_get_runs", runs)
    monkeypatch.setattr(app_module, "_poll_game_log_once", no_log)
    return save_dir


@pytest.mark.parametrize("path", ["/live", "/overlay", "/api/live"])
async def test_live_pages_survive_a_malformed_current_run(client, uncached_saves, path):
    _write(uncached_saves / "current_run.save", _BAD_CURRENT_RUNS["players not a list"])
    resp = await client.get(path)
    assert resp.status_code == 200


async def test_the_live_api_reports_no_run_for_a_malformed_save(client, uncached_saves):
    _write(uncached_saves / "current_run.save", _BAD_CURRENT_RUNS["value the model rejects"])
    resp = await client.get("/api/live")
    assert resp.status_code == 200
    assert resp.json()["active"] is False


@pytest.mark.parametrize("path", ["/", "/cards", "/collections", "/epochs", "/records"])
async def test_progress_pages_survive_malformed_progress(client, uncached_saves, path):
    _write(uncached_saves / "progress.save", _BAD_PROGRESS["character stats not objects"])
    resp = await client.get(path)
    assert resp.status_code == 200


async def test_the_epochs_page_survives_a_null_obtain_date(client, uncached_saves):
    _write(uncached_saves / "progress.save",
           {"epochs": [{"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": None}]})
    resp = await client.get("/epochs")
    assert resp.status_code == 200


async def test_the_epochs_page_survives_an_out_of_range_obtain_date(client, uncached_saves):
    _write(uncached_saves / "progress.save",
           {"epochs": [{"id": "NEOW_EPOCH", "state": "revealed", "obtain_date": 10 ** 20}]})
    resp = await client.get("/epochs")
    assert resp.status_code == 200
