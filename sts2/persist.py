"""Atomic persistence for the small state writers.

Language settings, hypotheses, and patch assignments used to write their
files directly (some swallowing errors), so a crash mid-write truncated the
file and the next read silently reset the user's state. Every small writer
funnels through here: temp file, fsync, atomic replace, and a logged False
instead of a silent one when persistence fails.

Concurrency: a module-level lock serializes the write below (unique temp
name + fsync + rename) across threads WITHIN this process, so two threads
writing the same path no longer collide on a shared temp file or interleave
their renames. This is NOT cross-process coordination — a second `python -m
sts2` process, or a separate worker, is not covered. It also does NOT make a
load-modify-write sequence atomic: two callers that each read a file,
mutate a dict, and then call this to write it back can still race and lose
an update, because the lock only covers the write() call itself, not
whatever the caller did before it. Callers that need read-modify-write
atomicity must coordinate that themselves.
"""
import json
import logging
import os
import threading
import uuid
from pathlib import Path

log = logging.getLogger(__name__)

_write_lock = threading.Lock()


def _fsync_dir(dir_path: Path) -> None:
    """Best-effort fsync of a directory so a completed rename is durably
    committed, not just visible. No-op on Windows, which has no directory-fsync
    equivalent (os.open on a directory raises OSError there); failures here
    must never turn an already-successful write into a reported failure, so
    they're swallowed rather than propagated.
    """
    if os.name == "nt":
        return
    try:
        fd = os.open(str(dir_path), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass


def write_text_atomic(path: Path, content: str) -> bool:
    """Write text via temp+fsync+rename. Returns False (logged) on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Unique per call (pid + random hex): a fixed name shared by every
        # writer let two concurrent writers to the same path collide on the
        # same temp file, so one of them failed the rename outright.
        tmp = path.with_suffix(
            path.suffix + f".{os.getpid()}.{uuid.uuid4().hex}.tmp")
        with _write_lock:
            with open(tmp, "w", encoding="utf-8") as fh:
                fh.write(content)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.replace(path)
            _fsync_dir(path.parent)
        return True
    except OSError:
        log.warning("Could not persist %s", path, exc_info=True)
        return False


def write_json_atomic(path: Path, data, *, indent: int = 2) -> bool:
    """JSON variant. allow_nan=False: Infinity/NaN round-trip as nonstandard
    JSON that other parsers reject, so they must never reach disk."""
    try:
        content = json.dumps(data, indent=indent, allow_nan=False)
    except ValueError:
        log.error("Refusing to persist non-finite numbers to %s", path)
        return False
    return write_text_atomic(path, content + "\n")
