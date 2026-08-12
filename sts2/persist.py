"""Atomic persistence for the small state writers.

Language settings, hypotheses, and patch assignments used to write their
files directly (some swallowing errors), so a crash mid-write truncated the
file and the next read silently reset the user's state. Every small writer
funnels through here: temp file, fsync, atomic replace, and a logged False
instead of a silent one when persistence fails.
"""
import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)


def write_text_atomic(path: Path, content: str) -> bool:
    """Write text via temp+fsync+rename. Returns False (logged) on failure."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            fh.write(content)
            fh.flush()
            os.fsync(fh.fileno())
        tmp.replace(path)
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
