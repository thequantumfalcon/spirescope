"""Lightweight update checker — queries GitHub releases on startup."""
import json
import logging
import os
import sys
import threading
import urllib.error
import urllib.request

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
    """Disable automatic update checks in frozen builds unless opted in."""
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
            with urllib.request.urlopen(req, timeout=10) as resp:
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


def check_for_data_update() -> None:
    """Check GitHub for a newer data bundle (runs in background thread)."""
    global _data_checked
    if not update_checks_enabled():
        _data_checked = True
        return

    def _check():
        global _data_update, _data_checked
        try:
            req = urllib.request.Request(
                _RELEASES_LIST_URL,
                headers={"User-Agent": "Spirescope", "Accept": "application/vnd.github+json"},
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
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
                if tarball and sha_file and tarball.startswith("https://github.com/"):
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

    threading.Thread(target=_check, daemon=True).start()


def get_data_update_info() -> dict | None:
    """Pending data-bundle update, or None."""
    return _data_update


def install_data_update() -> tuple[bool, str]:
    """Download, sha256-verify, and atomically install the pending bundle.

    Never raises; on any failure the existing data stays in place.
    Returns (ok, message).
    """
    global _data_update
    info = _data_update
    if not info:
        return False, "No data update available."
    import hashlib
    import shutil
    import tarfile
    import tempfile

    from sts2.config import DATA_DIR
    try:
        with tempfile.TemporaryDirectory(prefix="sts2-data-") as tmp:
            tmp_dir = __import__("pathlib").Path(tmp)
            bundle = tmp_dir / "data.tar.gz"
            for url, dest in ((info["tarball"], bundle),
                              (info["sha256"], tmp_dir / "data.sha256")):
                req = urllib.request.Request(url, headers={"User-Agent": "Spirescope"})
                with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
                    shutil.copyfileobj(resp, f, length=1 << 16)

            expected = (tmp_dir / "data.sha256").read_text().split()[0].strip().lower()
            digest = hashlib.sha256(bundle.read_bytes()).hexdigest()
            if digest != expected:
                return False, "Checksum mismatch — bundle rejected."

            extract_dir = tmp_dir / "extracted"
            with tarfile.open(bundle, "r:gz") as tf:
                tf.extractall(extract_dir, filter="data")
            # Bundle contains the data files at its root or under data/
            root = extract_dir / "data" if (extract_dir / "data" / "cards.json").exists() else extract_dir
            if not (root / "cards.json").exists():
                return False, "Bundle missing cards.json — rejected."
            json.loads((root / "cards.json").read_text(encoding="utf-8"))

            # Atomic-ish swap: stage next to DATA_DIR, then rename
            staging = DATA_DIR.parent / (DATA_DIR.name + ".new")
            backup = DATA_DIR.parent / (DATA_DIR.name + ".old")
            for leftover in (staging, backup):
                shutil.rmtree(leftover, ignore_errors=True)
            shutil.copytree(root, staging)
            # Preserve local-only files (mods dir, fetcher baseline)
            mods = DATA_DIR / "mods"
            if mods.exists() and not (staging / "mods").exists():
                shutil.copytree(mods, staging / "mods")
            DATA_DIR.rename(backup)
            try:
                staging.rename(DATA_DIR)
            except OSError:
                backup.rename(DATA_DIR)  # roll back
                raise
            shutil.rmtree(backup, ignore_errors=True)
        _data_update = None
        log.info("Data bundle %s installed", info["tag"])
        return True, f"Game data updated to {info['tag']}."
    except Exception as exc:
        log.exception("Data update failed")
        return False, f"Data update failed: {exc}"
