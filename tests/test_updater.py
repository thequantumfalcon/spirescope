"""Tests for the updater module."""
import json
import urllib.error
from unittest.mock import MagicMock, patch

import sts2.updater as updater
from sts2.updater import _parse_version, check_for_update, get_update_info


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
