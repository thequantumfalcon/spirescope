"""Tests for aggregate stats sync client."""
import json
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError, URLError

import pytest

from sts2.sync import SyncError, _validate_url, download_stats, upload_stats


class TestUploadStats:
    """Tests for upload_stats()."""

    def test_raises_when_no_url(self):
        with patch("sts2.sync.SYNC_URL", ""):
            with pytest.raises(SyncError, match="not configured"):
                upload_stats({"run_count": 5})

    def test_raises_on_oversized_payload(self):
        big = {"data": "x" * 6_000_000}
        with patch("sts2.sync.SYNC_URL", "https://example.com"):
            with pytest.raises(SyncError, match="too large"):
                upload_stats(big)

    def test_success(self):
        response_data = {"run_count": 100, "status": "ok"}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open", return_value=mock_resp) as mock_open:
            result = upload_stats({"run_count": 5})

        assert result == response_data
        req = mock_open.call_args[0][0]
        assert req.get_method() == "POST"
        assert "/api/v1/aggregate" in req.full_url

    def test_http_error(self):
        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open",
                   side_effect=HTTPError("url", 500, "Internal Server Error", {}, None)):
            with pytest.raises(SyncError, match="500"):
                upload_stats({"run_count": 5})

    def test_connection_error(self):
        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open",
                   side_effect=URLError("Connection refused")):
            with pytest.raises(SyncError, match="Connection failed"):
                upload_stats({"run_count": 5})


class TestDownloadStats:
    """Tests for download_stats()."""

    def test_raises_when_no_url(self):
        with patch("sts2.sync.SYNC_URL", ""):
            with pytest.raises(SyncError, match="not configured"):
                download_stats()

    def test_success(self):
        response_data = {"run_count": 200, "card_pick_rates": {}}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open", return_value=mock_resp):
            result = download_stats()

        assert result == response_data

    def test_invalid_format_missing_run_count(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"cards": {}}).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open", return_value=mock_resp):
            with pytest.raises(SyncError, match="Invalid aggregate format"):
                download_stats()

    def test_oversized_response(self):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b"x" * 5_000_002
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open", return_value=mock_resp):
            with pytest.raises(SyncError, match="too large"):
                download_stats()

    def test_http_error(self):
        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync._open",
                   side_effect=HTTPError("url", 404, "Not Found", {}, None)):
            with pytest.raises(SyncError, match="404"):
                download_stats()


class TestHeaders:
    """Tests for header construction."""

    def test_api_key_included_when_set(self):
        response_data = {"run_count": 1}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync.SYNC_API_KEY", "secret-key-123"), \
             patch("sts2.sync._open", return_value=mock_resp) as mock_open:
            download_stats()

        req = mock_open.call_args[0][0]
        assert req.get_header("X-api-key") == "secret-key-123"

    def test_no_api_key_when_empty(self):
        response_data = {"run_count": 1}
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(response_data).encode()
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("sts2.sync.SYNC_URL", "https://example.com"), \
             patch("sts2.sync.SYNC_API_KEY", ""), \
             patch("sts2.sync._open", return_value=mock_resp) as mock_open:
            download_stats()

        req = mock_open.call_args[0][0]
        assert not req.has_header("X-api-key")


class TestValidateUrl:
    """Tests for _validate_url() SSRF protection."""

    def test_https_valid(self):
        # Should not raise for valid HTTPS URL (DNS resolution may fail, that's OK)
        with patch("sts2.sync.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("93.184.216.34", 0)),
        ]):
            assert _validate_url("https://example.com/sync") == "https://example.com/sync"

    def test_http_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _validate_url("http://example.com/sync")

    def test_no_scheme_rejected(self):
        with pytest.raises(ValueError, match="HTTPS"):
            _validate_url("example.com/sync")

    def test_loopback_rejected(self):
        with pytest.raises(ValueError, match="private|loopback"):
            _validate_url("https://127.0.0.1/sync")

    def test_private_ip_rejected(self):
        with pytest.raises(ValueError, match="private|loopback"):
            _validate_url("https://192.168.1.1/sync")

    def test_private_10_rejected(self):
        with pytest.raises(ValueError, match="private|loopback"):
            _validate_url("https://10.0.0.1/sync")

    def test_dns_resolves_to_private_rejected(self):
        with patch("sts2.sync.socket.getaddrinfo", return_value=[
            (2, 1, 6, "", ("127.0.0.1", 0)),
        ]):
            with pytest.raises(ValueError, match="private|loopback"):
                _validate_url("https://evil.example.com/sync")


class TestRedirectValidation:
    """urlopen follows 3xx, and only the configured URL was ever validated —
    so one Location header voided every check in _validate_url."""

    def _handler(self):
        from sts2.sync import _ValidatingRedirectHandler
        return _ValidatingRedirectHandler()

    def _req(self, url="https://sync.example.com/api/v1/aggregate"):
        import urllib.request

        from sts2.sync import _headers
        return urllib.request.Request(url, headers=_headers(), method="GET")

    def test_redirect_into_loopback_is_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            self._handler().redirect_request(
                self._req(), None, 302, "Found", {}, "https://127.0.0.1:8000/health")

    def test_redirect_to_cloud_metadata_is_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            self._handler().redirect_request(
                self._req(), None, 302, "Found", {},
                "https://169.254.169.254/latest/meta-data/")

    def test_redirect_to_private_lan_is_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            self._handler().redirect_request(
                self._req(), None, 302, "Found", {}, "https://192.168.1.1/setup.cgi")

    def test_redirect_downgrade_to_http_is_rejected(self):
        import pytest
        with pytest.raises(ValueError):
            self._handler().redirect_request(
                self._req(), None, 302, "Found", {}, "http://sync.example.com/x")

    def test_api_key_is_not_forwarded_to_another_origin(self):
        from unittest.mock import patch
        with patch("sts2.sync.SYNC_API_KEY", "SECRET-KEY"):
            req = self._req()
            assert req.headers.get("X-api-key") == "SECRET-KEY"
            with patch("sts2.sync._validate_url", return_value="ok"):
                new = self._handler().redirect_request(
                    req, None, 302, "Found", {}, "https://other.example.net/x")
        assert new is not None
        assert not any(k.lower() == "x-api-key" for k in new.headers)

    def test_api_key_survives_a_same_origin_redirect(self):
        from unittest.mock import patch
        with patch("sts2.sync.SYNC_API_KEY", "SECRET-KEY"):
            req = self._req()
            with patch("sts2.sync._validate_url", return_value="ok"):
                new = self._handler().redirect_request(
                    req, None, 302, "Found", {}, "https://sync.example.com/moved")
        assert new is not None
        assert any(k.lower() == "x-api-key" for k in new.headers)

    def test_carrier_grade_nat_is_rejected(self):
        import pytest

        from sts2.sync import _validate_url
        with pytest.raises(ValueError):
            _validate_url("https://100.64.0.1/api")


class TestInvalidUrlSurfacesAsSyncError:
    """A malformed STS2_SYNC_URL was a raw ValueError traceback: the CLI
    catches SyncError only."""

    def test_upload_wraps_validation_error(self, monkeypatch):
        import pytest

        import sts2.sync as sync
        monkeypatch.setattr(sync, "SYNC_URL", "not a url")
        with pytest.raises(sync.SyncError, match="Invalid sync URL"):
            sync.upload_stats({"run_count": 1})

    def test_download_wraps_validation_error(self, monkeypatch):
        import pytest

        import sts2.sync as sync
        monkeypatch.setattr(sync, "SYNC_URL", "http://example.com")  # not https
        with pytest.raises(sync.SyncError, match="Invalid sync URL"):
            sync.download_stats()
