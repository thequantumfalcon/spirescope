"""Lifespan, the save watcher, the log poller and the last-resort error handler.

None of this is reachable through the test client's normal request path: the
lifespan only runs when a real server starts, the watcher and log poller are
background coroutines, and the global exception handler exists precisely for
the requests that never reach a route. All four fail silently by design --
they swallow exceptions so a bad save file or a locked log cannot take the
dashboard down -- which also means a break in them is invisible.
"""
import asyncio

import pytest

from sts2 import app as app_module

# ------------------------------------------------------------------ lifespan

async def test_lifespan_starts_the_watcher_and_stops_it_again(monkeypatch):
    """Nothing used to run after yield: the watcher task was never cancelled
    and the observer threads were never stopped or joined, so shutdown relied
    on daemon threads dying with the process."""
    started = {}

    async def fake_watch():
        started["watching"] = True
        await asyncio.Event().wait()          # never completes on its own

    monkeypatch.setattr(app_module, "_watch_saves", fake_watch)
    monkeypatch.setattr(app_module, "_prewarm_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr("sts2.updater.check_for_update", lambda _v: None)
    monkeypatch.setattr("sts2.updater.check_for_data_update", lambda: None)

    stopped, joined = [], []

    class _Observer:
        def stop(self):
            stopped.append(True)

        def join(self, _timeout):
            joined.append(True)

    monkeypatch.setattr(app_module, "_observers", [_Observer()])

    async with app_module._lifespan(app_module.app):
        await asyncio.sleep(0)
        assert started.get("watching")

    assert stopped == [True], "observer threads must be stopped on shutdown"
    assert joined == [True], "and joined, not left to die with the process"
    assert app_module._observers == []


async def test_lifespan_survives_an_observer_that_refuses_to_stop(monkeypatch):
    """A wedged observer must not stop the rest of shutdown."""
    monkeypatch.setattr(app_module, "_watch_saves",
                        lambda: asyncio.Event().wait())
    monkeypatch.setattr(app_module, "_prewarm_caches", lambda: asyncio.sleep(0))
    monkeypatch.setattr("sts2.updater.check_for_update", lambda _v: None)
    monkeypatch.setattr("sts2.updater.check_for_data_update", lambda: None)

    class _Bad:
        def stop(self):
            raise RuntimeError("wedged")

        def join(self, _timeout):
            raise RuntimeError("wedged")

    monkeypatch.setattr(app_module, "_observers", [_Bad()])
    async with app_module._lifespan(app_module.app):
        pass
    assert app_module._observers == []


# ------------------------------------------------------------ cache pre-warm

async def test_prewarm_populates_the_progress_and_run_caches(monkeypatch):
    from sts2.models import PlayerProgress
    progress = PlayerProgress()
    runs = []
    monkeypatch.setattr(app_module, "get_progress", lambda: progress)
    monkeypatch.setattr(app_module, "get_run_history", lambda: runs)
    monkeypatch.setattr(app_module, "_progress_cache", None)
    await app_module._prewarm_caches()
    assert app_module._progress_cache is progress


async def test_prewarm_failure_never_stops_startup(monkeypatch, caplog):
    """A corrupt save file at startup would otherwise abort the lifespan and
    the server would never come up at all."""
    def boom():
        raise OSError("save file locked")

    monkeypatch.setattr(app_module, "get_progress", boom)
    await app_module._prewarm_caches()          # must not raise


# --------------------------------------------------------------- mtime scan

def test_check_mtime_is_zero_when_no_save_tree_exists(monkeypatch, tmp_path):
    monkeypatch.setattr(app_module, "SAVE_DIRS", [tmp_path / "absent"])
    assert app_module._check_mtime() == 0.0


def test_check_mtime_spans_every_detected_save_tree(monkeypatch, tmp_path):
    """History merges the vanilla and modded trees, but change detection used
    to watch only whichever was freshest at startup -- switching between them
    mid-session left the dashboard blind to the active one."""
    import os
    vanilla, modded = tmp_path / "vanilla", tmp_path / "modded"
    for d, mtime in ((vanilla, 1_000), (modded, 9_000)):
        (d / "history").mkdir(parents=True)
        progress = d / "progress.save"
        progress.write_text("{}", encoding="utf-8")
        os.utime(progress, (mtime, mtime))
        run = d / "history" / "1.run"
        run.write_text("{}", encoding="utf-8")
        os.utime(run, (mtime, mtime))
    monkeypatch.setattr(app_module, "SAVE_DIRS", [vanilla, modded])
    assert app_module._check_mtime() >= 9_000


def test_check_mtime_skips_a_run_file_it_cannot_stat(monkeypatch, tmp_path):
    """A file deleted between glob() and stat() is normal while the game is
    writing; it must not abort the whole scan."""
    from pathlib import Path
    (tmp_path / "history").mkdir()
    (tmp_path / "history" / "1.run").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(app_module, "SAVE_DIRS", [tmp_path])
    real_stat = Path.stat

    def flaky(self, *a, **kw):
        if self.suffix == ".run":
            raise OSError("vanished mid-scan")
        return real_stat(self, *a, **kw)

    monkeypatch.setattr(Path, "stat", flaky)
    assert app_module._check_mtime() >= 0.0     # must not raise


# ------------------------------------------------------------- log tailer

class _Tailer:
    def __init__(self, result=None, state=None):
        self._result = result
        self.state = state

    def poll(self):
        return self._result


class _State:
    def __init__(self, active):
        self.active = active


@pytest.fixture(autouse=True)
def _reset_log_state(monkeypatch):
    monkeypatch.setattr(app_module, "_log_tailer", None)
    monkeypatch.setattr(app_module, "_log_run_state", None)
    monkeypatch.setattr(app_module, "_log_poll_lock", None)


async def test_polling_the_log_records_a_live_run(monkeypatch):
    class _Result:
        @staticmethod
        def model_dump():
            return {"active": True, "floor": 7}

    monkeypatch.setattr(app_module, "_log_tailer", _Tailer(_Result()))
    await app_module._poll_game_log_once()
    assert app_module._log_run_state == {"active": True, "floor": 7}


async def test_polling_accepts_a_tailer_that_offers_to_dict(monkeypatch):
    class _Result:
        @staticmethod
        def to_dict():
            return {"active": True, "floor": 3}

    monkeypatch.setattr(app_module, "_log_tailer", _Tailer(_Result()))
    await app_module._poll_game_log_once()
    assert app_module._log_run_state == {"active": True, "floor": 3}


async def test_a_plain_dict_result_is_stored_as_is(monkeypatch):
    monkeypatch.setattr(app_module, "_log_tailer", _Tailer({"active": True}))
    await app_module._poll_game_log_once()
    assert app_module._log_run_state == {"active": True}


async def test_a_finished_run_clears_the_live_state(monkeypatch):
    """The tailer stops returning results once the run ends; without this the
    dashboard keeps showing the last floor of a run that is already over."""
    monkeypatch.setattr(app_module, "_log_run_state", {"active": True})
    monkeypatch.setattr(app_module, "_log_tailer",
                        _Tailer(None, state=_State(active=False)))
    await app_module._poll_game_log_once()
    assert app_module._log_run_state is None


async def test_no_result_and_no_previous_run_changes_nothing(monkeypatch):
    monkeypatch.setattr(app_module, "_log_tailer",
                        _Tailer(None, state=_State(active=False)))
    await app_module._poll_game_log_once()
    assert app_module._log_run_state is None


async def test_a_tailer_that_raises_never_reaches_the_request(monkeypatch):
    """The log lives in the game's directory and can be locked or half-written
    at any moment; that must not turn into a 500 on the live page."""
    class _Boom:
        state = None

        def poll(self):
            raise OSError("log file locked by the game")

    monkeypatch.setattr(app_module, "_log_tailer", _Boom())
    await app_module._poll_game_log_once()      # must not raise


async def test_the_poller_builds_its_own_tailer_on_first_use(monkeypatch):
    built = {}

    class _Fake:
        state = None

        def __init__(self):
            built["yes"] = True

        def poll(self):
            return None

    monkeypatch.setattr("sts2.logparser.LogTailer", _Fake)
    await app_module._poll_game_log_once()
    assert built.get("yes")
    assert app_module._log_tailer is not None


# --------------------------------------------------- last-resort error handler

def _request(path="/boom", accept="text/html"):
    from starlette.requests import Request
    return Request({
        "type": "http", "http_version": "1.1", "method": "GET", "path": path,
        "raw_path": path.encode(), "root_path": "", "query_string": b"",
        "headers": [(b"accept", accept.encode())], "app": app_module.app,
        "scheme": "http", "server": ("testserver", 80), "client": ("test", 1),
    })


async def test_an_unhandled_error_renders_the_error_page(caplog):
    resp = await app_module.global_error_handler(
        _request(), RuntimeError("kaboom"))
    assert resp.status_code == 500
    assert b"Something went wrong" in resp.body


async def test_an_unhandled_error_on_an_api_path_returns_json():
    resp = await app_module.global_error_handler(
        _request("/api/cards", accept="application/json"), RuntimeError("x"))
    assert resp.status_code == 500
    assert b'"status":500' in resp.body.replace(b" ", b"")


async def test_the_logged_path_is_sanitised(caplog):
    """The path reaches the log verbatim otherwise, so a crafted URL could
    inject newlines into the log stream."""
    import logging
    caplog.set_level(logging.ERROR)
    await app_module.global_error_handler(
        _request("/boom\r\nFAKE-LOG-LINE"), RuntimeError("x"))
    assert "FAKE-LOG-LINE" in caplog.text        # still present...
    assert "\r\n" not in caplog.text.split("FAKE")[0][-40:]  # ...but not as a break


# ------------------------------------------- data refresh and background loops

async def test_refresh_data_clears_caches():
    """_refresh_data should reset analytics cache."""
    from unittest.mock import AsyncMock, patch

    import sts2.app as app_mod
    from sts2.app import _refresh_data

    original_kb = app_mod.kb
    # Pre-fill caches
    app_mod._analytics_cache = {None: {"total": 5}}
    app_mod._analytics_cache_time = {None: 1000.0}

    try:
        with patch("sts2.app.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=[original_kb, None, []]):
            await _refresh_data()

        assert app_mod._analytics_cache == {}
        assert app_mod._analytics_cache_time == {}
    finally:
        app_mod.kb = original_kb


async def test_refresh_data_reloads_kb():
    """_refresh_data should create a new KnowledgeBase."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import sts2.app as app_mod
    from sts2.app import _refresh_data

    original_kb = app_mod.kb
    mock_kb = MagicMock()
    try:
        with patch("sts2.app.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=[mock_kb, None, []]):
            await _refresh_data()
        assert app_mod.kb is mock_kb
    finally:
        app_mod.kb = original_kb  # Restore for other tests


async def test_poll_game_log_handles_error():
    """_poll_game_log should not crash on exceptions."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from sts2.app import _poll_game_log

    mock_tailer = MagicMock()
    mock_tailer.poll.side_effect = RuntimeError("log file missing")
    mock_tailer.state = None

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            raise asyncio.CancelledError  # Stop the infinite loop
        return fn(*args, **kwargs)

    import asyncio

    with patch("sts2.logparser.LogTailer", return_value=mock_tailer), \
         patch("sts2.app.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("sts2.app.asyncio.sleep", new_callable=AsyncMock):
        try:
            await _poll_game_log()
        except asyncio.CancelledError:
            pass  # Expected — we use this to break the infinite loop

    # If we got here without an unhandled exception, the error handling works
    assert call_count >= 2


async def test_watch_saves_polling_fallback():
    """_watch_saves should fall back to polling when watchdog unavailable."""
    from unittest.mock import patch

    from sts2.app import _watch_saves

    call_count = 0

    async def fake_sleep(t):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            raise asyncio.CancelledError

    import asyncio
    from unittest.mock import MagicMock
    mock_dir = MagicMock()
    mock_dir.exists.return_value = False
    with patch("sts2.watcher.start_observer", return_value=None), \
         patch("sts2.app.SAVE_DIRS", [mock_dir]), \
         patch("sts2.app.asyncio.sleep", side_effect=fake_sleep), \
         patch("sts2.app._check_mtime", return_value=0.0):
        try:
            await _watch_saves()
        except asyncio.CancelledError:
            pass

    assert call_count >= 2  # Confirms polling loop ran
