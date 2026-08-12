"""Tests for the updater module."""
import contextlib
import hashlib
import io
import json
import os
import tarfile
import time
import urllib.error
from unittest.mock import MagicMock, patch

import sts2.updater as updater
from sts2.updater import _parse_version, check_for_update, get_update_info, update_checks_enabled


class TestParseVersion:
    def test_simple(self):
        assert _parse_version("1.2.3") == (1, 2, 3)

    def test_with_v_prefix(self):
        assert _parse_version("v1.2.3") == (1, 2, 3)

    def test_with_V_prefix(self):
        assert _parse_version("V2.0.0") == (2, 0, 0)

    def test_two_parts(self):
        assert _parse_version("1.0") == (1, 0)

    def test_empty(self):
        assert _parse_version("") == (0,)

    def test_non_numeric(self):
        assert _parse_version("abc") == (0,)

    def test_partial_numeric(self):
        assert _parse_version("1.2.beta") == (1, 2)

    def test_comparison_newer(self):
        assert _parse_version("v1.2.0") > _parse_version("1.1.0")

    def test_comparison_equal(self):
        assert _parse_version("v1.1.0") == _parse_version("1.1.0")

    def test_comparison_older(self):
        assert _parse_version("1.0.0") < _parse_version("1.1.0")


class TestCheckForUpdate:
    def setup_method(self):
        updater._latest_version = None
        updater._update_url = None
        updater._checked = False

    def test_newer_version_detected(self):
        mock_data = json.dumps({
            "tag_name": "v2.0.0",
            "html_url": "https://github.com/test/releases/v2.0.0",
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            check_for_update("1.1.0")
            # Wait for background thread
            import time
            time.sleep(0.5)

        info = get_update_info()
        assert info is not None
        assert info["version"] == "2.0.0"
        assert "v2.0.0" in info["url"]

    def test_same_version_no_update(self):
        mock_data = json.dumps({
            "tag_name": "v1.1.0",
            "html_url": "https://github.com/test/releases/v1.1.0",
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            check_for_update("1.1.0")
            import time
            time.sleep(0.5)

        assert get_update_info() is None

    def test_network_error_no_crash(self):
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("timeout")):
            check_for_update("1.1.0")
            import time
            time.sleep(0.5)

        assert get_update_info() is None
        assert updater._checked is True

    def test_older_version_no_update(self):
        mock_data = json.dumps({
            "tag_name": "v1.0.0",
            "html_url": "https://github.com/test/releases/v1.0.0",
        }).encode()
        mock_resp = MagicMock()
        mock_resp.read.return_value = mock_data
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("urllib.request.urlopen", return_value=mock_resp):
            check_for_update("1.1.0")
            import time
            time.sleep(0.5)

        assert get_update_info() is None

    def test_disabled_in_frozen_build(self):
        with patch.object(updater.sys, "frozen", True, create=True), \
             patch.dict("os.environ", {}, clear=False), \
             patch("urllib.request.urlopen") as mock_urlopen:
            check_for_update("1.1.0")

        mock_urlopen.assert_not_called()
        assert updater._checked is True


class TestGetUpdateInfo:
    def setup_method(self):
        updater._latest_version = None
        updater._update_url = None

    def test_no_update(self):
        assert get_update_info() is None

    def test_with_update(self):
        updater._latest_version = "2.0.0"
        updater._update_url = "https://example.com/release"
        info = get_update_info()
        assert info == {"version": "2.0.0", "url": "https://example.com/release"}


class TestUpdateChecksEnabled:
    def test_source_default_enabled(self):
        with patch.object(updater.sys, "frozen", False, create=True), \
             patch.dict("os.environ", {}, clear=False):
            assert update_checks_enabled() is True

    def test_frozen_default_disabled(self):
        with patch.object(updater.sys, "frozen", True, create=True), \
             patch.dict("os.environ", {}, clear=False):
            assert update_checks_enabled() is False

    def test_env_override_enables_checks(self):
        with patch.object(updater.sys, "frozen", True, create=True), \
             patch.dict("os.environ", {"SPIRESCOPE_CHECK_UPDATES": "1"}, clear=False):
            assert update_checks_enabled() is True

    def test_env_override_disables_checks_for_source_build(self):
        """SPIRESCOPE_CHECK_UPDATES=0 must force checks off even for a source
        build, symmetric with =1 forcing them on for a frozen one."""
        with patch.object(updater.sys, "frozen", False, create=True), \
             patch.dict("os.environ", {"SPIRESCOPE_CHECK_UPDATES": "0"}, clear=False):
            assert update_checks_enabled() is False


# ---------------------------------------------------------------------------
# Data-bundle updater: crash-safety, locking, download/extraction caps,
# full-dataset validation, and the on-demand check contract.
# ---------------------------------------------------------------------------

def _card(name, **kw):
    d = {"id": f"CARD.{name.upper()}", "name": name, "character": "Ironclad",
         "cost": "1", "type": "Attack", "rarity": "Common",
         "description": f"{name} desc", "description_upgraded": "", "keywords": []}
    d.update(kw)
    return d


def _cards(n):
    return [_card(f"Card{i}") for i in range(n)]


def _full_bundle_files(cards=None, **overrides):
    """A complete, valid bundle payload: every file _validate_dataset requires."""
    files = {
        "cards.json": cards if cards is not None else _cards(400),
        "relics.json": [],
        "potions.json": [],
        "enemies.json": [],
        "events.json": [],
        "patches.json": [],
        "last_updated.txt": "2026-07-22T20:00:00+00:00",
    }
    files.update(overrides)
    return files


def _make_bundle(tmp_path, files: dict):
    """Build data.tar.gz under tmp_path containing data/<name> for each entry."""
    src = tmp_path / "bundle-src" / "data"
    src.mkdir(parents=True)
    for name, content in files.items():
        if name.endswith(".txt"):
            (src / name).write_text(content)
        else:
            (src / name).write_text(json.dumps(content))
    bundle = tmp_path / "data.tar.gz"
    with tarfile.open(bundle, "w:gz") as tf:
        tf.add(src, arcname="data")
    return bundle


@contextlib.contextmanager
def _wrap_bytes(data: bytes):
    yield io.BytesIO(data)


def _fake_urlopen(bundle, digest: str):
    def _do(req, timeout):
        if req.full_url.endswith(".tar.gz"):
            return _wrap_bytes(bundle.read_bytes())
        return _wrap_bytes(f"{digest}  data.tar.gz".encode())
    return _do


def _set_pending_update(tag="data-v2026.07.22", tarball="https://github.com/x/y/data.tar.gz",
                         sha256="https://github.com/x/y/data.sha256"):
    updater._data_update = {"tag": tag, "date": "2026-07-22", "tarball": tarball, "sha256": sha256}


class TestRecoverDataDir:
    def test_restores_from_backup_when_live_missing(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        backup_dir = tmp_path / "data.backup"
        backup_dir.mkdir()
        (backup_dir / "cards.json").write_text(json.dumps(_cards(2)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        recovered = updater.recover_data_dir()

        assert recovered is True
        assert data_dir.exists()
        assert not backup_dir.exists()
        assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Card0"

    def test_restores_from_backup_when_live_incomplete(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()  # a crash left the live dir present but without cards.json
        backup_dir = tmp_path / "data.backup"
        backup_dir.mkdir()
        (backup_dir / "cards.json").write_text(json.dumps(_cards(2)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        recovered = updater.recover_data_dir()

        assert recovered is True
        assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Card0"

    def test_noop_when_live_already_valid(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        assert updater.recover_data_dir() is False
        assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Card0"

    def test_noop_when_neither_live_nor_backup_usable(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"  # never created — nothing to recover from
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        assert updater.recover_data_dir() is False
        assert not data_dir.exists()


class TestLock:
    def test_second_attempt_fails_cleanly_while_lock_held(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        _set_pending_update()

        lock_path = updater._lock_path(data_dir)
        held_fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        try:
            def _boom(req, timeout):
                raise AssertionError("must not touch the network while the lock is held")
            monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)

            ok, msg = updater.install_data_update()

            assert not ok
            assert "already in progress" in msg.lower()
            assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Card0"
        finally:
            os.close(held_fd)
            lock_path.unlink(missing_ok=True)
            updater._data_update = None

    def test_stale_lock_is_taken_over(self, tmp_path):
        lock_path = tmp_path / "data.update.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)
        stale_time = time.time() - updater._LOCK_STALE_SECONDS - 60
        os.utime(lock_path, (stale_time, stale_time))

        acquired = updater._acquire_lock(lock_path)

        assert acquired is not None
        os.close(acquired)
        lock_path.unlink(missing_ok=True)

    def test_fresh_lock_is_not_taken_over(self, tmp_path):
        lock_path = tmp_path / "data.update.lock"
        fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.close(fd)

        assert updater._acquire_lock(lock_path) is None
        lock_path.unlink()


class TestDownloadCap:
    def test_bundle_over_cap_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater, "_MAX_BUNDLE_BYTES", 10)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "cap" in msg.lower()
        assert json.loads((data_dir / "cards.json").read_text())[0]["name"] == "Card0"
        updater._data_update = None

    def test_checksum_file_over_cap_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater, "_MAX_CHECKSUM_BYTES", 4)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "cap" in msg.lower()
        updater._data_update = None


class TestChecksumUrlOrigin:
    def test_non_github_checksum_url_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        def _boom(req, timeout):
            raise AssertionError("must not reach the network before the origin check")
        monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
        _set_pending_update(sha256="https://evil.example.com/data.sha256")

        ok, msg = updater.install_data_update()

        assert not ok
        assert "github.com" in msg.lower()
        updater._data_update = None

    def test_non_github_tarball_url_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

        def _boom(req, timeout):
            raise AssertionError("must not reach the network before the origin check")
        monkeypatch.setattr(updater.urllib.request, "urlopen", _boom)
        _set_pending_update(tarball="https://evil.example.com/data.tar.gz")

        ok, msg = updater.install_data_update()

        assert not ok
        assert "github.com" in msg.lower()
        updater._data_update = None


class TestExtractionCaps:
    def test_too_many_members_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater, "_MAX_MEMBERS", 1)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "entries" in msg.lower()
        updater._data_update = None

    def test_oversized_member_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater, "_MAX_MEMBER_BYTES", 1)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "too large" in msg.lower()
        updater._data_update = None

    def test_expanded_size_cap_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater, "_MAX_EXPANDED_BYTES", 1)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "expands" in msg.lower()
        updater._data_update = None


class TestFullValidationGate:
    def test_missing_required_file_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        files = _full_bundle_files()
        del files["relics.json"]
        bundle = _make_bundle(tmp_path, files)
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "relics.json" in msg
        updater._data_update = None

    def test_too_few_cards_rejected(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files(cards=_cards(5)))
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert not ok
        assert "cards.json" in msg.lower()
        updater._data_update = None

    def test_complete_bundle_installs_and_keeps_one_backup(self, tmp_path, monkeypatch):
        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "cards.json").write_text(json.dumps(_cards(1)))
        bundle = _make_bundle(tmp_path, _full_bundle_files())
        digest = hashlib.sha256(bundle.read_bytes()).hexdigest()

        monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)
        monkeypatch.setattr(updater.urllib.request, "urlopen", _fake_urlopen(bundle, digest))
        _set_pending_update()

        ok, msg = updater.install_data_update()

        assert ok, msg
        installed = json.loads((data_dir / "cards.json").read_text())
        assert len(installed) == 400
        assert updater.get_data_update_info() is None
        # The pre-install dataset is kept as a recovery backup, not discarded.
        backup = updater._backup_dir(data_dir)
        assert backup.exists()
        assert json.loads((backup / "cards.json").read_text())[0]["name"] == "Card0"


class TestCheckForDataUpdateOnDemand:
    def test_returns_the_finding(self, tmp_path, monkeypatch):
        (tmp_path / "last_updated.txt").write_text("2026-07-01T00:00:00+00:00")
        monkeypatch.setattr("sts2.config.DATA_DIR", tmp_path)
        monkeypatch.setattr(updater, "update_checks_enabled", lambda: True)
        monkeypatch.setattr(updater, "recover_data_dir", lambda: False)
        release = {"tag_name": "data-v2026.07.22", "assets": [
            {"name": "spirescope-data.tar.gz", "browser_download_url": "https://github.com/x/y/a.tar.gz"},
            {"name": "spirescope-data.sha256", "browser_download_url": "https://github.com/x/y/a.sha256"},
        ]}

        class FakeResp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps([release]).encode()

        class T:
            def __init__(self, target, daemon):
                self.target = target

            def start(self):
                self.target()

        monkeypatch.setattr(updater.threading, "Thread", T)
        monkeypatch.setattr(updater.urllib.request, "urlopen", lambda req, timeout: FakeResp())
        updater._data_update = None

        result = updater.check_for_data_update()

        assert result is not None and result["tag"] == "data-v2026.07.22"
        assert updater.get_data_update_info() == result
        updater._data_update = None

    def test_idempotent_while_a_check_is_in_flight(self, monkeypatch):
        monkeypatch.setattr(updater, "update_checks_enabled", lambda: True)
        monkeypatch.setattr(updater, "recover_data_dir", lambda: False)
        monkeypatch.setattr(updater, "_data_checking", True)
        monkeypatch.setattr(updater, "_data_update", {"tag": "data-v2026.07.22"})

        def _boom(*a, **kw):
            raise AssertionError("must not start a second check while one is in flight")
        monkeypatch.setattr(updater.threading, "Thread", _boom)

        result = updater.check_for_data_update()

        assert result == {"tag": "data-v2026.07.22"}

    def test_disabled_returns_current_finding_without_checking(self, monkeypatch):
        monkeypatch.setattr(updater, "update_checks_enabled", lambda: False)
        monkeypatch.setattr(updater, "recover_data_dir", lambda: False)
        monkeypatch.setattr(updater, "_data_update", None)

        def _boom(*a, **kw):
            raise AssertionError("must not check the network when checks are disabled")
        monkeypatch.setattr(updater.threading, "Thread", _boom)

        assert updater.check_for_data_update() is None
