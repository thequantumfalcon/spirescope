"""File system watcher for save directory changes.

Uses watchdog for OS-level file events with debouncing.
Falls back gracefully if watchdog is unavailable.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

log = logging.getLogger(__name__)

try:
    from watchdog.events import FileSystemEventHandler
    from watchdog.observers import Observer

    _HAS_WATCHDOG = True
except ImportError:
    _HAS_WATCHDOG = False
    Observer = None  # type: ignore[assignment]
    FileSystemEventHandler = object  # type: ignore[assignment,misc]


class SaveFileHandler(FileSystemEventHandler):
    """Debounced handler that signals an asyncio Event on save file changes.

    The debounce is on the trailing edge: the event is set once the save
    files have been quiet for the debounce interval, not at the first
    modification. The game writes a file in more than one step, and firing
    at the first event let the refresh read progress.save or a .run file
    half-written; the events for the rest of that write were then swallowed
    by the debounce, so the torn read stayed cached until the next change.
    """

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        event: asyncio.Event,
        debounce_seconds: float = 0.5,
    ):
        self._loop = loop
        self._event = event
        self._debounce = debounce_seconds
        # Only ever touched on the event loop thread (see _restart_timer), so
        # watchdog's thread never races the loop for it and it needs no lock.
        self._timer: asyncio.TimerHandle | None = None

    def _should_handle(self, path: str) -> bool:
        """Only react to save-relevant files."""
        return path.endswith((".save", ".run"))

    def on_modified(self, event):
        if event.is_directory or not self._should_handle(event.src_path):
            return
        # watchdog calls this from its own thread; the timer lives on the loop.
        self._loop.call_soon_threadsafe(self._restart_timer)

    on_created = on_modified

    def on_moved(self, event):
        # A file written under a temporary name and then renamed into place
        # arrives only as a move, with the save file as the destination.
        if event.is_directory or not self._should_handle(getattr(event, "dest_path", "")):
            return
        self._loop.call_soon_threadsafe(self._restart_timer)

    def _restart_timer(self) -> None:
        """Move the signal to one full interval after the latest write."""
        if self._timer is not None:
            self._timer.cancel()
        self._timer = self._loop.call_later(self._debounce, self._fire)

    def _fire(self) -> None:
        self._timer = None
        self._event.set()


def start_observer(
    save_dir: Path,
    loop: asyncio.AbstractEventLoop,
    event: asyncio.Event,
) -> Observer | None:  # type: ignore[valid-type]
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
