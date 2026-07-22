"""Patch manifest: build_id -> patch-era resolution (schema v2).

The manifest (sts2/data/patches.json) is an ordered (chronological) list of
patch entries:

    {"patch": "v0.109.0", "date": "2026-07-17", "branch": "beta",
     "build_ids": ["v0.109.0"],
     "changed": {"cards": [...ids], "relics": [...ids], "enemies": [...ids]}}

Mapping is append-as-observed: a run whose build_id matches no entry resolves
to None ("unmapped era") and is surfaced in the admin view for one-click
assignment — no guessing.
"""
import json
import logging
from threading import Lock

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

_PATCHES_FILE = "patches.json"
_lock = Lock()
_cache: list[dict] | None = None


def load_patches() -> list[dict]:
    """The manifest, oldest patch first. Cached; [] when missing/corrupt."""
    global _cache
    if _cache is not None:
        return _cache
    path = DATA_DIR / _PATCHES_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("Failed to load %s: %s", _PATCHES_FILE, exc)
        data = []
    if not isinstance(data, list):
        log.warning("%s is not a list, ignoring", _PATCHES_FILE)
        data = []
    _cache = data
    return _cache


def invalidate_cache():
    global _cache
    _cache = None


def resolve_build(build_id: str) -> dict | None:
    """The patch entry whose build_ids contain build_id, or None (unmapped)."""
    if not build_id:
        return None
    for entry in load_patches():
        if build_id in entry.get("build_ids", []):
            return entry
    return None


def unmapped_builds(runs: list) -> list[dict]:
    """Distinct unresolvable build_ids across runs, with run counts."""
    counts: dict[str, int] = {}
    for r in runs:
        build_id = getattr(r, "build_id", "")
        if build_id and resolve_build(build_id) is None:
            counts[build_id] = counts.get(build_id, 0) + 1
    return [
        {"build_id": b, "count": n}
        for b, n in sorted(counts.items(), reverse=True)
    ]


def assign_build(build_id: str, patch_name: str) -> bool:
    """Append build_id to the named patch's build_ids and persist."""
    if not build_id or not patch_name:
        return False
    with _lock:
        patches = load_patches()
        entry = next((p for p in patches if p.get("patch") == patch_name), None)
        if entry is None:
            return False
        build_ids = entry.setdefault("build_ids", [])
        if build_id not in build_ids:
            build_ids.append(build_id)
            try:
                (DATA_DIR / _PATCHES_FILE).write_text(
                    json.dumps(patches, indent=2) + "\n", encoding="utf-8"
                )
            except OSError as exc:
                log.error("Failed to write %s: %s", _PATCHES_FILE, exc)
                build_ids.remove(build_id)
                return False
        invalidate_cache()
        return True


def changed_in(entity_id: str) -> str:
    """Name of the most recent patch listing entity_id as changed, or ""."""
    if not entity_id:
        return ""
    for entry in reversed(load_patches()):
        changed = entry.get("changed", {})
        for kind in ("cards", "relics", "enemies"):
            if entity_id in changed.get(kind, []):
                return entry.get("patch", "")
    return ""


def current_patch() -> dict | None:
    """The newest patch entry (manifest is ordered oldest first)."""
    patches = load_patches()
    return patches[-1] if patches else None


def era_of(build_id: str) -> str:
    """Patch-era name for a build_id, or "unmapped"."""
    entry = resolve_build(build_id)
    return entry.get("patch", "unmapped") if entry else "unmapped"


def era_index(patch_name: str) -> int:
    """Position of a patch in the chronology (-1 for unknown/unmapped)."""
    for i, entry in enumerate(load_patches()):
        if entry.get("patch") == patch_name:
            return i
    return -1


def branch_of(build_id: str) -> str:
    """Branch (main|beta) a build_id belongs to, or "" when unmapped."""
    entry = resolve_build(build_id)
    return entry.get("branch", "") if entry else ""
