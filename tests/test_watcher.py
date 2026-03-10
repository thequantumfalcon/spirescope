"""Tests for file system watcher and event-driven SSE."""
import asyncio
import time
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from sts2.watcher import SaveFileHandler, start_observer


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

    def test_debounce_prevents_rapid_triggers(self):
        handler = self._make_handler(debounce=1.0)
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save")

        handler.on_modified(evt)
        assert handler._loop.call_soon_threadsafe.call_count == 1

        # Second call within debounce window should be ignored
        handler.on_modified(evt)
        assert handler._loop.call_soon_threadsafe.call_count == 1

    def test_debounce_allows_after_window(self):
        handler = self._make_handler(debounce=0.01)
        evt = SimpleNamespace(is_directory=False, src_path="/saves/progress.save")

        handler.on_modified(evt)
        assert handler._loop.call_soon_threadsafe.call_count == 1

        # Simulate time passing beyond debounce window
        handler._last_trigger = time.monotonic() - 1.0
        handler.on_modified(evt)
        assert handler._loop.call_soon_threadsafe.call_count == 2


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


class TestSaveChangedEvent:
    """Integration tests for the event-driven SSE wake-up."""

    async def test_sse_wakes_on_event(self):
        """SSE generator should return quickly when the event is set."""
        from sts2.app import _save_changed_event

        _save_changed_event.set()
        start = time.monotonic()
        try:
            await asyncio.wait_for(_save_changed_event.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            pytest.fail("Event wait should not timeout when event is set")
        elapsed = time.monotonic() - start
        assert elapsed < 0.5, f"Should wake instantly, took {elapsed:.2f}s"
        # Clean up
        _save_changed_event.clear()

    async def test_sse_times_out_without_event(self):
        """SSE generator should fall back to 3s poll when no event."""
        from sts2.app import _save_changed_event

        _save_changed_event.clear()
        start = time.monotonic()
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(_save_changed_event.wait(), timeout=0.1)
        elapsed = time.monotonic() - start
        assert elapsed >= 0.05, "Should have waited for the timeout"

    async def test_refresh_data_reloads_caches(self):
        """_refresh_data should reload KB, progress, and runs."""
        from sts2 import app as app_mod

        with patch.object(app_mod, "KnowledgeBase") as mock_kb, \
             patch.object(app_mod, "get_progress", return_value=None), \
             patch.object(app_mod, "get_run_history", return_value=[]):
            await app_mod._refresh_data()

        mock_kb.assert_called_once()
        assert app_mod._analytics_cache == {}
        assert app_mod._analytics_cache_time == {}
