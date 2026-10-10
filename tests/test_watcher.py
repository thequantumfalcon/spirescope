"""Tests for file system watcher and event-driven SSE."""
import asyncio
import contextlib
import threading
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sts2 import app as app_mod
from sts2.models import CurrentRun
from sts2.watcher import SaveFileHandler, start_observer

# The sts2.app globals _refresh_data rebinds. A test that lets one of them
# keep a mock leaves it there for every module that runs afterwards.
_REFRESHED_GLOBALS = (
    "kb", "_progress_cache", "_progress_cache_time", "_run_cache",
    "_run_cache_by_id", "_run_cache_time", "_analytics_cache",
    "_analytics_cache_time", "_data_generation",
)


@pytest.fixture(autouse=True)
def _app_globals_are_left_alone():
    """Fail any test here that leaves an sts2.app global rebound.

    Autouse fixtures are set up before the ones a test asks for, so this
    teardown runs after monkeypatch has put its patches back: whatever is
    still different here is a real leak, not a patch about to be undone.
    """
    before = {name: getattr(app_mod, name) for name in _REFRESHED_GLOBALS}
    yield
    leaked = [name for name, value in before.items()
              if getattr(app_mod, name) is not value]
    assert not leaked, f"test left sts2.app globals rebound: {leaked}"


@pytest.fixture
def app_state(monkeypatch):
    """Register every global _refresh_data rebinds with monkeypatch first, so
    teardown restores the originals whatever the refresh assigned to them."""
    from sts2 import patches as patch_manifest

    for name in _REFRESHED_GLOBALS:
        monkeypatch.setattr(app_mod, name, getattr(app_mod, name))
    monkeypatch.setattr(patch_manifest, "_cache", patch_manifest._cache)
    return app_mod


class _ManualLoop:
    """Stands in for the event loop: runs thread-safe callbacks at once and
    holds call_later timers until the test fires them."""

    def __init__(self):
        self.timers = []

    def call_soon_threadsafe(self, callback, *args):
        callback(*args)

    def call_later(self, delay, callback, *args):
        timer = SimpleNamespace(delay=delay, callback=callback, args=args,
                                cancelled=False)
        timer.cancel = lambda: setattr(timer, "cancelled", True)
        self.timers.append(timer)
        return timer

    def live_timers(self):
        return [t for t in self.timers if not t.cancelled]


class TestSaveFileHandler:
    """Unit tests for the watchdog event handler."""

    def _make_handler(self, event=None, loop=None, debounce=0.5):
        event = event or MagicMock()
        loop = loop or MagicMock()
        return SaveFileHandler(loop, event, debounce_seconds=debounce)

    def test_ignores_directories(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=True, src_path="/saves/history")
        handler.on_modified(evt)
        handler._loop.call_soon_threadsafe.assert_not_called()

    def test_ignores_non_save_files(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/readme.txt")
        handler.on_modified(evt)
        handler._loop.call_soon_threadsafe.assert_not_called()

    def test_triggers_on_save_file(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save")
        handler.on_modified(evt)
        handler._loop.call_soon_threadsafe.assert_called_once()

    def test_triggers_on_run_file(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/history/abc123.run")
        handler.on_modified(evt)
        handler._loop.call_soon_threadsafe.assert_called_once()

    def test_on_created_also_triggers(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/new_file.save")
        handler.on_created(evt)
        handler._loop.call_soon_threadsafe.assert_called_once()

    def test_a_save_renamed_into_place_triggers(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save.tmp",
                              dest_path="/saves/progress.save")
        handler.on_moved(evt)
        handler._loop.call_soon_threadsafe.assert_called_once()

    def test_a_move_to_another_kind_of_file_is_ignored(self):
        handler = self._make_handler()
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save",
                              dest_path="/saves/progress.save.bak")
        handler.on_moved(evt)
        handler._loop.call_soon_threadsafe.assert_not_called()

    def test_a_burst_of_writes_signals_once_after_the_last_one(self):
        """Trailing edge: nothing fires while the game is still writing, and
        the one signal comes a full interval after the final write."""
        loop, event = _ManualLoop(), MagicMock()
        handler = SaveFileHandler(loop, event, debounce_seconds=0.5)
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save")

        for _ in range(3):
            handler.on_modified(evt)
            event.set.assert_not_called()

        live = loop.live_timers()
        assert len(live) == 1, "each write must restart the quiet period"
        assert live[0].delay == 0.5
        live[0].callback(*live[0].args)
        event.set.assert_called_once()

    def test_a_write_after_the_signal_starts_a_new_quiet_period(self):
        loop, event = _ManualLoop(), MagicMock()
        handler = SaveFileHandler(loop, event, debounce_seconds=0.5)
        evt = SimpleNamespace(is_directory=False, src_path="/saves/history/1.run")

        handler.on_modified(evt)
        first = loop.live_timers()[0]
        first.callback(*first.args)
        handler.on_created(evt)
        assert event.set.call_count == 1

        second = loop.live_timers()[-1]
        assert second is not first
        second.callback(*second.args)
        assert event.set.call_count == 2

    async def test_the_signal_waits_for_the_files_to_go_quiet(self):
        """The same against a real loop, with writes arriving from another
        thread the way watchdog delivers them."""
        loop = asyncio.get_running_loop()
        event = asyncio.Event()
        handler = SaveFileHandler(loop, event, debounce_seconds=0.4)
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save")

        def write():
            threading.Thread(target=handler.on_modified, args=(evt,)).start()

        write()
        await asyncio.sleep(0.1)
        assert not event.is_set(), "fired on the first write, mid-save"
        write()
        last_write = time.monotonic()
        await asyncio.sleep(0.1)
        assert not event.is_set()

        await asyncio.wait_for(event.wait(), timeout=3.0)
        assert time.monotonic() - last_write >= 0.35


class TestStartObserver:
    """Tests for the observer factory function."""

    def test_returns_none_when_watchdog_unavailable(self, tmp_path):
        loop = MagicMock()
        event = MagicMock()
        with patch("sts2.watcher._HAS_WATCHDOG", False):
            result = start_observer(tmp_path, loop, event)
        assert result is None

    def test_returns_none_on_observer_error(self, tmp_path):
        loop = MagicMock()
        event = MagicMock()
        with patch("sts2.watcher.Observer", side_effect=RuntimeError("fail")):
            result = start_observer(tmp_path, loop, event)
        assert result is None

    def test_starts_observer_successfully(self, tmp_path):
        loop = MagicMock()
        event = MagicMock()
        mock_observer = MagicMock()
        with patch("sts2.watcher._HAS_WATCHDOG", True), \
             patch("sts2.watcher.Observer", return_value=mock_observer):
            result = start_observer(tmp_path, loop, event)
        assert result is mock_observer
        mock_observer.schedule.assert_called_once()
        mock_observer.start.assert_called_once()
        assert mock_observer.daemon is True


@pytest.fixture
def fresh_events(monkeypatch):
    """Give the test its own copies of both app events. An asyncio.Event binds
    to the loop that first waits on it, so waiting on the module's own events
    here would tie them to this test's loop for the rest of the session."""
    monkeypatch.setattr(app_mod, "_save_changed_event", asyncio.Event())
    monkeypatch.setattr(app_mod, "_live_data_event", asyncio.Event())


@pytest.mark.usefixtures("fresh_events")
class TestSaveChangedEvent:
    """Integration tests for the event-driven SSE wake-up."""

    async def test_sse_wakes_on_event(self):
        """SSE generator should return quickly when the event is set."""
        from sts2.app import _live_data_event

        _live_data_event.set()
        start = time.monotonic()
        try:
            await asyncio.wait_for(_live_data_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pytest.fail("Event wait should not timeout when event is set")
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"Should wake instantly, took {elapsed:.2f}s"
        # Clean up
        _live_data_event.clear()

    async def test_sse_times_out_without_event(self):
        """SSE generator should fall back to 3s poll when no event."""
        from sts2.app import _live_data_event

        _live_data_event.clear()
        start = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_live_data_event.wait(), timeout=0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05, "Should have waited for the timeout"

    async def test_refresh_data_reloads_caches(self, app_state):
        """_refresh_data should reload KB, progress, and runs."""
        from sts2 import app as app_mod

        with patch.object(app_mod, "KnowledgeBase") as mock_kb, \
             patch.object(app_mod, "get_progress", return_value=None), \
             patch.object(app_mod, "get_run_history", return_value=[]):
            await app_mod._refresh_data()

        mock_kb.assert_called_once()
        assert app_mod._analytics_cache == {}
        assert app_mod._analytics_cache_time == {}

    async def test_refresh_data_invalidates_patch_cache(self, app_state):
        """A data-bundle install rewrites patches.json; if the manifest cache
        survives the refresh, current-patch scoping and era comparisons keep
        serving the old manifest until the process restarts."""
        from sts2 import app as app_mod
        from sts2 import patches as patch_manifest

        patch_manifest.load_patches()
        assert patch_manifest._cache is not None

        with patch.object(app_mod, "KnowledgeBase"), \
             patch.object(app_mod, "get_progress", return_value=None), \
             patch.object(app_mod, "get_run_history", return_value=[]):
            await app_mod._refresh_data()

        assert patch_manifest._cache is None


@contextlib.asynccontextmanager
async def _running_watcher(monkeypatch, tmp_path, *, watchdog):
    """Run the real _watch_saves loop, in watchdog or polling mode, with
    _refresh_data replaced by a recorder; yields the shared event log."""
    events: list[str] = []

    async def fake_refresh():
        events.append("refresh")
        await asyncio.sleep(0.05)  # a reload takes time; live views must not wait on it

    monkeypatch.setattr(app_mod, "_refresh_data", fake_refresh)
    monkeypatch.setattr(app_mod, "SAVE_DIRS", [tmp_path])
    monkeypatch.setattr(app_mod, "_observers", [])
    monkeypatch.setattr(app_mod, "_save_watcher_last_mtime", 0)
    monkeypatch.setattr("sts2.watcher.start_observer",
                        lambda *_a: object() if watchdog else None)
    task = asyncio.create_task(app_mod._watch_saves())
    await asyncio.sleep(0.01)
    try:
        yield events
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _record_live_wakes(events):
    """What an SSE stream does: wait on the live event, act, wait again."""
    while True:
        await app_mod._live_data_event.wait()
        events.append("wake")
        while app_mod._live_data_event.is_set():
            await asyncio.sleep(0)


async def _until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        await asyncio.sleep(0.01)


class _LogTailer:
    """A tailer whose every poll reports a new live-run state."""
    state = None

    def __init__(self):
        self.floor = 0

    def poll(self):
        self.floor += 1
        return {"active": True, "floor": self.floor}


@pytest.mark.usefixtures("fresh_events")
class TestLiveWakeups:
    """A game-log change is not a save change. The log tailer and the save
    watcher used to share one event, so every log line during combat made the
    watcher rebuild the KnowledgeBase and re-read every run file."""

    @pytest.fixture(autouse=True)
    def _log_state(self, monkeypatch):
        monkeypatch.setattr(app_mod, "_log_tailer", _LogTailer())
        monkeypatch.setattr(app_mod, "_log_run_state", None)
        monkeypatch.setattr(app_mod, "_log_poll_lock", None)

    async def test_a_log_change_does_not_reload_data(self, monkeypatch, tmp_path):
        async with _running_watcher(monkeypatch, tmp_path, watchdog=True) as events:
            for _ in range(3):
                await app_mod._poll_game_log_once()
                await asyncio.sleep(0.05)
        assert app_mod._log_run_state == {"active": True, "floor": 3}
        assert "refresh" not in events

    async def test_a_log_change_wakes_live_streams(self, monkeypatch, tmp_path):
        async with _running_watcher(monkeypatch, tmp_path, watchdog=True) as events:
            viewer = asyncio.create_task(_record_live_wakes(events))
            await asyncio.sleep(0)
            await app_mod._poll_game_log_once()
            await _until(lambda: "wake" in events)
            viewer.cancel()
        assert events == ["wake"]

    async def test_a_save_change_wakes_live_streams_then_reloads_and_wakes_them_again(
            self, monkeypatch, tmp_path):
        """Live streams read current_run.save from disk, so they are woken as
        soon as the change is seen (as they were when they shared the
        watchdog's event) and again once the reload has finished."""
        async with _running_watcher(monkeypatch, tmp_path, watchdog=True) as events:
            viewer = asyncio.create_task(_record_live_wakes(events))
            await asyncio.sleep(0)
            app_mod._save_changed_event.set()   # what the watchdog handler does
            await _until(lambda: events.count("wake") >= 2)
            viewer.cancel()
        assert events == ["wake", "refresh", "wake"]

    async def test_the_polling_fallback_still_reloads_and_wakes_live_streams(
            self, monkeypatch, tmp_path):
        """Without watchdog the watcher polls save mtimes every 10 s; a newer
        mtime must still reload and then wake live streams."""
        real_sleep = asyncio.sleep

        async def quick_poll(delay, *args, **kwargs):
            await real_sleep(0.01 if delay == 10 else delay, *args, **kwargs)

        mtimes = iter([100.0, 200.0])
        monkeypatch.setattr(app_mod, "_check_mtime", lambda: next(mtimes, 200.0))
        monkeypatch.setattr(asyncio, "sleep", quick_poll)
        async with _running_watcher(monkeypatch, tmp_path, watchdog=False) as events:
            viewer = asyncio.create_task(_record_live_wakes(events))
            await _until(lambda: "wake" in events)
            viewer.cancel()
        assert events == ["refresh", "wake"]

    async def test_the_live_stream_wakes_on_a_live_data_signal(self, monkeypatch):
        """The SSE stream sends the next payload as soon as the live event
        fires instead of sitting out its 3 s fallback poll."""
        from sts2 import routes

        reads = iter(range(1, 100))

        async def live_run(_player=None):
            return CurrentRun(active=False, gold=next(reads))

        async def no_runs():
            return []

        monkeypatch.setattr(routes, "_get_live_run", live_run)
        monkeypatch.setattr(app_mod, "_get_runs", no_runs)
        request = SimpleNamespace(client=SimpleNamespace(host="127.0.0.1"))
        resp = await routes.live_stream(request, player=None)
        body = resp.body_iterator
        pending = None
        try:
            first = await asyncio.wait_for(body.__anext__(), timeout=5.0)
            assert '"gold": 1' in first
            pending = asyncio.ensure_future(body.__anext__())
            await asyncio.sleep(0.1)    # let the stream reach its wait
            assert not pending.done()
            await app_mod._poll_game_log_once()   # a log change
            second = await asyncio.wait_for(pending, timeout=1.0)
            assert '"gold": 2' in second
        finally:
            if pending is not None and not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await pending
            await body.aclose()
