"""File system watcher for save directory changes.

Uses watchdog for OS-level file events with debouncing.
Falls back gracefully if watchdog is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False
    Observer = None  # type: ignore[assignment,misc]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


class SaveFileHandler(FileSystemEventHandler):
    """Debounced handler that signals an asyncio Event on save file changes."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
        debounce_seconds: float = 0.5,
    ):
        self._loop = loop
        self._event = event
        self._debounce = debounce_seconds
        self._last_trigger = 0.0

    def _should_handle(self, path: str) -> bool:
        """Only react to save-relevant files."""
        return path.endswith((".save", ".run"))

    def on_modified(self, event):  # type: ignore[override]
        if event.is_directory or not self._should_handle(event.src_path):
            return
        now = time.monotonic()
        if now - self._last_trigger < self._debounce:
            return
        self._last_trigger = now
        self._loop.call_soon_threadsafe(self._event.set)

    on_created = on_modified  # type: ignore[assignment]


def start_observer(
    save_dir: Path,
    loop: asyncio.AbstractEventLoop,
    event: asyncio.Event,
) -> Observer | None:
    """Start watchdog Observer. Returns None if watchdog unavailable or fails."""
    if not _HAS_WATCHDOG:
        log.info("watchdog not installed, using polling fallback")
        return None
    try:
        handler = SaveFileHandler(loop, event)
        observer = Observer()
        observer.schedule(handler, str(save_dir), recursive=True)
        observer.daemon = True
        observer.start()
        log.info("File watcher started for %s", save_dir)
        return observer
    except Exception:
        log.warning("watchdog failed, falling back to polling", exc_info=True)
        return None
