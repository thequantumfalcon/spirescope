"""Lightweight update checker — queries GitHub releases on startup."""
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

log = logging.getLogger(__name__)

_RELEASES_URL = "https://api.github.com/repos/thequantumfalcon/Spirescope/releases/latest"

_latest_version: str | None = None
_update_url: str | None = None
_checked = False


def _parse_version(tag: str) -> tuple[int, ...]:
    """Parse 'v1.2.3' or '1.2.3' into (1, 2, 3)."""
    tag = tag.lstrip("vV")
    parts = []
    for p in tag.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts) or (0,)


def update_checks_enabled() -> bool:
    """Whether background update checks (app + data) should run.

    SPIRESCOPE_CHECK_UPDATES=1/true/yes/on forces checks on, including for a
    frozen build. SPIRESCOPE_CHECK_UPDATES=0/false/no/off forces checks off,
    including for a source run. Either direction overrides the default,
    which is on for source runs and off for frozen builds, so a packaged
    user isn't surprised by an unsolicited network call.
    """
    raw = os.environ.get("SPIRESCOPE_CHECK_UPDATES")
    if raw is not None:
        normalized = raw.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
    return not getattr(sys, "frozen", False)


def check_for_update(current_version: str) -> None:
    """Check GitHub for a newer release (runs in background thread)."""
    global _checked
    if not update_checks_enabled():
        _checked = True
        return

    def _check():
        global _latest_version, _update_url, _checked
        try:
            req = urllib.request.Request(
                _RELEASES_URL,
                headers={"User-Agent": "Spirescope", "Accept": "application/vnd.github+json"},
            )
            # Hardcoded https GitHub API endpoints — no file:/custom schemes.
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                data = json.loads(resp.read().decode("utf-8"))
            tag = data.get("tag_name", "")
            if tag and _parse_version(tag) > _parse_version(current_version):
                _latest_version = tag.lstrip("vV")
                _raw_url = data.get("html_url", "")
                _update_url = _raw_url if _raw_url.startswith("https://github.com/") else ""
                log.info("Update available: %s (current: %s)", _latest_version, current_version)
        except Exception:
            pass  # Network errors are fine — this is best-effort
        finally:
            _checked = True

    threading.Thread(target=_check, daemon=True).start()


def get_update_info() -> dict | None:
    """Return update info if a newer version is available, else None."""
    if _latest_version:
        return {"version": _latest_version, "url": _update_url}
    return None


# ---------------------------------------------------------------------------
# Data-bundle updates (decoupled from app releases; tags: data-vYYYY.MM.DD)
# ---------------------------------------------------------------------------

_RELEASES_LIST_URL = "https://api.github.com/repos/thequantumfalcon/Spirescope/releases?per_page=20"

_data_update: dict | None = None
_data_checked = False
_data_checking = False

_GITHUB_PREFIX = "https://github.com/"

# A bundle is untrusted network input until it passes checksum + shape
# validation, so it is bounded like any other untrusted archive: capped
# before it touches disk, and capped again before tar is allowed to expand
# it into real files.
_MAX_BUNDLE_BYTES = 50 * 1024 * 1024        # 50 MB
_MAX_CHECKSUM_BYTES = 4 * 1024              # 4 KB
_MAX_MEMBERS = 1000
_MAX_MEMBER_BYTES = 20 * 1024 * 1024        # 20 MB per file
_MAX_EXPANDED_BYTES = 200 * 1024 * 1024     # 200 MB total

_REQUIRED_DATA_FILES = ("cards.json", "relics.json", "potions.json",
                         "enemies.json", "events.json", "patches.json")
# The field that identifies a record in each family. Entity files key on
# "id"; the patch manifest keys on "patch".
_IDENTIFYING_FIELD = {
    "cards.json": "id", "relics.json": "id", "potions.json": "id",
    "enemies.json": "id", "events.json": "id", "patches.json": "patch",
}
_MIN_CARDS = 400

# Long enough that a slow install never trips it, short enough that a lock
# left behind by a killed process self-heals without manual cleanup.
_LOCK_STALE_SECONDS = 600


class _RejectBundle(Exception):
    """A downloaded/extracted bundle failed validation. str(exc) is user-facing."""


def _local_data_date() -> str:
    """Date (YYYY-MM-DD) of the local game data, from last_updated.txt."""
    from sts2.config import DATA_DIR
    try:
        stamp = (DATA_DIR / "last_updated.txt").read_text(encoding="utf-8")
        return stamp.strip()[:10]
    except OSError:
        return ""


def _parse_data_tag(tag: str) -> str:
    """'data-v2026.07.22' -> '2026-07-22' ('' when not a data tag)."""
    m = __import__("re").fullmatch(r"data-v(\d{4})\.(\d{2})\.(\d{2})", tag)
    return f"{m.group(1)}-{m.group(2)}-{m.group(3)}" if m else ""


def _backup_dir(data_dir: Path) -> Path:
    return data_dir.parent / (data_dir.name + ".backup")


def _lock_path(data_dir: Path) -> Path:
    return data_dir.parent / (data_dir.name + ".update.lock")


def _staging_dir(data_dir: Path) -> Path:
    import uuid
    return data_dir.parent / f"{data_dir.name}.staging-{uuid.uuid4().hex[:12]}"


def _dataset_looks_valid(path: Path) -> bool:
    """Lightweight liveness check used for crash recovery only.

    Deliberately weaker than _validate_dataset (which gates promoting a new
    bundle): this only asks "is there a usable dataset here", so an older or
    hand-edited local dataset still counts as valid and recovery never
    second-guesses data the app was already running on.
    """
    try:
        data = json.loads((path / "cards.json").read_text(encoding="utf-8"))
        return isinstance(data, list) and len(data) > 0
    except (OSError, json.JSONDecodeError):
        return False


def recover_data_dir() -> bool:
    """Restore the live data dir from backup if a previous install crashed mid-swap.

    install_data_update() renames the live dir to a backup and then renames
    the staged replacement into place; a process killed between those two
    renames leaves no live dataset at all. This heals that: idempotent no-op
    when the live dir already looks usable, otherwise falls back to the
    backup kept from the last successful install. Called on the update-check
    path (and defensively at the start of install_data_update) so the app
    never has to be told to repair itself. Returns whether it restored.
    """
    from sts2.config import DATA_DIR
    if _dataset_looks_valid(DATA_DIR):
        return False
    backup = _backup_dir(DATA_DIR)
    if not _dataset_looks_valid(backup):
        return False
    import shutil
    log.warning("Live data dir missing or incomplete — restoring from backup")
    shutil.rmtree(DATA_DIR, ignore_errors=True)
    backup.rename(DATA_DIR)
    return True


def _acquire_lock(lock_path: Path, stale_after: float = _LOCK_STALE_SECONDS) -> int | None:
    """Create an exclusive lock file; return its fd, or None if held by another attempt.

    A lock file older than stale_after is treated as abandoned by a killed
    process and taken over rather than blocking forever.
    """
    try:
        return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError:
        pass
    import time
    try:
        age = time.time() - lock_path.stat().st_mtime
    except OSError:
        age = float("inf")
    if age <= stale_after:
        return None
    try:
        lock_path.unlink()
    except OSError:
        return None
    try:
        return os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except OSError:
        return None


def _release_lock(lock_path: Path, fd: int) -> None:
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        lock_path.unlink()
    except OSError:
        pass


def _fsync_path(path: Path) -> None:
    """Best-effort durability for one file. Never raises."""
    try:
        fd = os.open(str(path), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _fsync_tree(root: Path) -> None:
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            _fsync_path(Path(dirpath) / name)


def _download_capped(url: str, dest: Path, max_bytes: int, hasher=None) -> None:
    """Stream url to dest, hashing as bytes arrive (one read of the response).

    Raises _RejectBundle once more than max_bytes have arrived, checked as
    the response streams in so an oversized response is never fully written
    to disk or read into memory first.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "Spirescope"})
    total = 0
    # Asset URLs are origin-checked against https://github.com/ before this call.
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:  # nosec B310
        while True:
            chunk = resp.read(1 << 16)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise _RejectBundle(f"Download exceeded the {max_bytes}-byte cap — rejected.")
            f.write(chunk)
            if hasher is not None:
                hasher.update(chunk)
        f.flush()
        os.fsync(f.fileno())


def _extract_capped(bundle: Path, extract_dir: Path) -> None:
    """Extract bundle with member-count/per-file/total-expanded-size caps.

    Keeps the existing "data" tar filter (blocks absolute paths, symlinks
    escaping the target, device files, etc.) and adds the size caps a tar
    filter alone doesn't cover.
    """
    import tarfile
    with tarfile.open(bundle, "r:gz") as tf:
        members = tf.getmembers()
        if len(members) > _MAX_MEMBERS:
            raise _RejectBundle(f"Bundle has too many entries ({len(members)}) — rejected.")
        total = 0
        for member in members:
            if member.isfile():
                if member.size > _MAX_MEMBER_BYTES:
                    raise _RejectBundle(f"Bundle entry {member.name!r} is too large — rejected.")
                total += member.size
        if total > _MAX_EXPANDED_BYTES:
            raise _RejectBundle("Bundle expands beyond the size cap — rejected.")
        tf.extractall(extract_dir, filter="data")


def _validate_dataset(root: Path) -> None:
    """Raise _RejectBundle unless the bundle is a dataset this app can load.

    Parsing as JSON is not enough: a file of 400 bare strings satisfied
    "cards.json is a list of at least 400 entries" while being nothing the
    app can render. Every required file must therefore be a list of objects
    whose entries carry the identifying fields the models require, and the
    whole directory must survive an actual KnowledgeBase construction before
    it is allowed anywhere near the live data directory.
    """
    if not (root / "last_updated.txt").exists():
        raise _RejectBundle("Bundle missing last_updated.txt — rejected.")
    for name in _REQUIRED_DATA_FILES:
        path = root / name
        if not path.exists():
            raise _RejectBundle(f"Bundle missing {name} — rejected.")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            raise _RejectBundle(f"Bundle {name} failed to parse — rejected.") from exc
        if not isinstance(data, list):
            raise _RejectBundle(f"Bundle {name} is not a list — rejected.")
        # Entries must be objects carrying their family's identifying field;
        # anything else is not the shape consumers assume. patches.json keys
        # on "patch" rather than "id", so the field is per-family.
        key = _IDENTIFYING_FIELD[name]
        for entry in data:
            if not isinstance(entry, dict) or not entry.get(key):
                raise _RejectBundle(
                    f"Bundle {name} has entries without a '{key}' field "
                    f"— rejected.")
        if name == "cards.json" and len(data) < _MIN_CARDS:
            raise _RejectBundle("Bundle cards.json has too few entries — rejected.")
    _validate_loadable(root)


def _validate_loadable(root: Path) -> None:
    """Build a KnowledgeBase against the candidate directory in a subprocess.

    The final proof that a bundle is usable is that the app can actually load
    it. Done in a subprocess because DATA_DIR binds at import time, so the
    running process cannot be repointed, and because a hostile or corrupt
    dataset must not be able to damage live state to prove itself.
    """
    import subprocess
    import sys

    probe = (
        "import os, sys\n"
        "from sts2.knowledge import KnowledgeBase\n"
        "kb = KnowledgeBase()\n"
        "if len(kb.cards) < %d:\n"
        "    sys.exit('too few cards loaded')\n"
        "if not kb.relics or not kb.enemies:\n"
        "    sys.exit('required families did not load')\n"
    ) % _MIN_CARDS
    env = dict(os.environ, STS2_DATA_DIR=str(root))
    # Isolate the probe completely. Beyond not touching real user state, the
    # save directory MUST be redirected: KnowledgeBase back-fills entities
    # discovered from save files, so a probe pointed at the player's real
    # saves reports families as present that the bundle does not actually
    # contain — an empty-relics bundle passed until this was redirected.
    probe_dir = root / "_probe"
    env["STS2_STATE_DIR"] = str(probe_dir / "state")
    env["STS2_MODS_DIR"] = str(probe_dir / "mods")
    env["STS2_SAVE_DIR"] = str(probe_dir / "saves")
    env["STS2_LOG_FILE"] = str(probe_dir / "none.log")
    env["STS2_LANG"] = "en"
    try:
        result = subprocess.run([sys.executable, "-c", probe], env=env,
                                capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        raise _RejectBundle("Bundle could not be verified — rejected.") from exc
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip().splitlines()
        reason = detail[-1][:200] if detail else "unknown error"
        raise _RejectBundle(f"Bundle does not load: {reason} — rejected.")


def check_for_data_update() -> dict | None:
    """Check GitHub for a newer data bundle (runs in background thread).

    Idempotent: a check already in flight is not restarted by a second call,
    so this is safe to wire up behind a UI "check now" trigger as well as
    the startup call. Always returns the current finding (None if none yet),
    so on-demand callers get a result even though the check itself runs
    asynchronously.
    """
    global _data_checked, _data_checking
    recover_data_dir()
    if not update_checks_enabled():
        _data_checked = True
        return _data_update
    if _data_checking:
        return _data_update

    def _check():
        global _data_update, _data_checked, _data_checking
        try:
            req = urllib.request.Request(
                _RELEASES_LIST_URL,
                headers={"User-Agent": "Spirescope", "Accept": "application/vnd.github+json"},
            )
            # Hardcoded https GitHub API endpoints — no file:/custom schemes.
            with urllib.request.urlopen(req, timeout=10) as resp:  # nosec B310
                releases = json.loads(resp.read().decode("utf-8"))
            local_date = _local_data_date()
            best = None
            for rel in releases:
                date = _parse_data_tag(rel.get("tag_name", ""))
                if not date or (best and date <= best["date"]):
                    continue
                assets = {a.get("name", ""): a.get("browser_download_url", "")
                          for a in rel.get("assets", [])}
                tarball = next((u for n, u in assets.items() if n.endswith(".tar.gz")), "")
                sha_file = next((u for n, u in assets.items() if n.endswith(".sha256")), "")
                if (tarball and sha_file
                        and tarball.startswith(_GITHUB_PREFIX)
                        and sha_file.startswith(_GITHUB_PREFIX)):
                    best = {"tag": rel["tag_name"], "date": date,
                            "tarball": tarball, "sha256": sha_file}
            if best and (not local_date or best["date"] > local_date):
                _data_update = best
                log.info("Data update available: %s (local data: %s)",
                         best["tag"], local_date or "unknown")
        except Exception:
            pass  # best-effort
        finally:
            _data_checked = True
            _data_checking = False

    _data_checking = True
    threading.Thread(target=_check, daemon=True).start()
    return _data_update


def get_data_update_info() -> dict | None:
    """Pending data-bundle update, or None."""
    return _data_update


def _merge_local_build_ids(local_patches, staged_patches) -> None:
    """Carry hand-assigned build_id -> patch mappings across a bundle install.

    The bundle ships patches.json, and the staging rule is "bundle wins for its
    own files", so /admin/patches assignments were discarded on every data
    update — silently changing which runs count as current-patch and therefore
    the win rates shown. Build ids are user knowledge the bundle cannot know,
    so they are unioned back in; everything else still comes from the bundle.
    """
    if not local_patches.exists() or not staged_patches.exists():
        return
    try:
        local = json.loads(local_patches.read_text(encoding="utf-8"))
        staged = json.loads(staged_patches.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        log.warning("Could not merge local patch assignments: %s", exc)
        return
    if not isinstance(local, list) or not isinstance(staged, list):
        return
    local_ids = {p.get("patch"): p.get("build_ids") or []
                 for p in local if isinstance(p, dict)}
    carried = 0
    for entry in staged:
        if not isinstance(entry, dict):
            continue
        mine = [b for b in local_ids.get(entry.get("patch"), []) if isinstance(b, str)]
        if not mine:
            continue
        existing = entry.setdefault("build_ids", [])
        for build_id in mine:
            if build_id not in existing:
                existing.append(build_id)
                carried += 1
    if carried:
        try:
            staged_patches.write_text(json.dumps(staged, indent=2) + "\n", encoding="utf-8")
            log.info("Carried %d local build-id assignment(s) into the new patch manifest", carried)
        except OSError as exc:
            log.warning("Could not write merged patch manifest: %s", exc)


def install_data_update() -> tuple[bool, str]:
    """Download, sha256-verify, extract, validate, and atomically install the
    pending data bundle.

    Crash-safe: the live dataset is renamed to a backup only after the new
    dataset has been downloaded, checksummed, extracted, fully validated and
    staged — so a crash at any point before that leaves the live dataset
    untouched, and a crash during the swap itself is recoverable from the
    backup via recover_data_dir() on the next run. A lock file serializes
    concurrent install attempts instead of letting them race on shared
    staging/backup paths. Never raises; on any failure the existing data
    stays in place. Returns (ok, message).
    """
    global _data_update
    info = _data_update
    if not info:
        return False, "No data update available."

    from sts2.config import DATA_DIR
    recover_data_dir()

    lock_path = _lock_path(DATA_DIR)
    lock_fd = _acquire_lock(lock_path)
    if lock_fd is None:
        return False, "Another data update is already in progress."

    import shutil
    import tempfile

    staging = None
    try:
        if not info["tarball"].startswith(_GITHUB_PREFIX):
            raise _RejectBundle("Bundle URL is not from github.com — rejected.")
        if not info["sha256"].startswith(_GITHUB_PREFIX):
            raise _RejectBundle("Checksum URL is not from github.com — rejected.")

        with tempfile.TemporaryDirectory(prefix="sts2-data-") as tmp:
            tmp_dir = Path(tmp)
            bundle = tmp_dir / "data.tar.gz"
            checksum_file = tmp_dir / "data.sha256"

            import hashlib
            hasher = hashlib.sha256()
            _download_capped(info["tarball"], bundle, _MAX_BUNDLE_BYTES, hasher=hasher)
            _download_capped(info["sha256"], checksum_file, _MAX_CHECKSUM_BYTES)

            expected = checksum_file.read_text(encoding="utf-8").split()[0].strip().lower()
            if hasher.hexdigest() != expected:
                raise _RejectBundle("Checksum mismatch — bundle rejected.")

            extract_dir = tmp_dir / "extracted"
            _extract_capped(bundle, extract_dir)
            # Bundle contains the data files at its root or under data/
            root = extract_dir / "data" if (extract_dir / "data" / "cards.json").exists() else extract_dir
            _validate_dataset(root)

            staging = _staging_dir(DATA_DIR)
            shutil.rmtree(staging, ignore_errors=True)
            shutil.copytree(root, staging)
            # Preserve local-only content: anything present locally that the
            # bundle doesn't ship (mods dir, fetcher baseline, aggregate
            # stats, user settings) carries over; bundle wins for its files.
            # The listing is snapshotted first — the app may write into
            # DATA_DIR while this runs, so iterating it live risks a file
            # vanishing mid-loop.
            for item in list(DATA_DIR.iterdir()):
                target = staging / item.name
                if target.exists():
                    continue
                try:
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                except FileNotFoundError:
                    continue  # vanished between the listing and the copy
            _merge_local_build_ids(DATA_DIR / "patches.json", staging / "patches.json")
            _fsync_tree(staging)

            # The old backup is safe to drop now: DATA_DIR itself is still
            # the live, valid dataset until the rename below, so this instant
            # never leaves fewer than one full dataset on disk.
            backup = _backup_dir(DATA_DIR)
            shutil.rmtree(backup, ignore_errors=True)
            DATA_DIR.rename(backup)
            try:
                staging.rename(DATA_DIR)
            except OSError:
                backup.rename(DATA_DIR)  # roll back
                raise
            staging = None
        _data_update = None
        log.info("Data bundle %s installed", info["tag"])
        return True, f"Game data updated to {info['tag']}."
    except _RejectBundle as exc:
        log.warning("Data update rejected: %s", exc)
        return False, str(exc)
    except Exception as exc:
        log.exception("Data update failed")
        return False, f"Data update failed: {exc}"
    finally:
        if staging is not None and staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        _release_lock(lock_path, lock_fd)
