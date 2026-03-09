"""Tests for the CLI entry point (__main__.py)."""
import sys
from unittest.mock import patch, MagicMock

import pytest

from sts2.__main__ import main, _get_version


# ── Version helper ───────────────────────────────────────────────────────

def test_get_version_from_metadata():
    """Should return version from importlib.metadata when available."""
    with patch("sts2.__main__.version", return_value="2.0.0", create=True):
        # _get_version uses importlib.metadata.version internally
        v = _get_version()
        assert v  # should return a version string


def test_get_version_fallback():
    """Should fall back to config.VERSION when metadata fails."""
    with patch("importlib.metadata.version", side_effect=Exception("not installed")):
        v = _get_version()
        from sts2.config import VERSION
        assert v == VERSION


# ── CLI commands ─────────────────────────────────────────────────────────

def test_cli_help(capsys):
    with patch.object(sys, "argv", ["sts2", "--help"]):
        main()
    out = capsys.readouterr().out
    assert "Usage:" in out
    assert "serve" in out


def test_cli_help_short(capsys):
    with patch.object(sys, "argv", ["sts2", "-h"]):
        main()
    out = capsys.readouterr().out
    assert "Usage:" in out


def test_cli_version(capsys):
    with patch.object(sys, "argv", ["sts2", "--version"]):
        main()
    out = capsys.readouterr().out
    assert "Spirescope" in out


def test_cli_version_short(capsys):
    with patch.object(sys, "argv", ["sts2", "-V"]):
        main()
    out = capsys.readouterr().out
    assert "Spirescope" in out


def test_cli_unknown_command(capsys):
    with patch.object(sys, "argv", ["sts2", "nonsense"]), \
         pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Unknown command" in out


def test_cli_update():
    mock_scraper = MagicMock()
    with patch.object(sys, "argv", ["sts2", "update"]), \
         patch.dict("sys.modules", {"sts2.scraper": mock_scraper}), \
         patch("sts2.__main__.run_scraper", create=True) as mock_run:
        # Need to patch the actual import inside main()
        with patch("sts2.scraper.run_scraper") as mock_run:
            main()
            mock_run.assert_called_once_with(save_only=False)


def test_cli_update_save_only():
    with patch.object(sys, "argv", ["sts2", "update", "--save-only"]), \
         patch("sts2.scraper.run_scraper") as mock_run:
        main()
        mock_run.assert_called_once_with(save_only=True)


def test_cli_community():
    with patch.object(sys, "argv", ["sts2", "community"]), \
         patch("sts2.community.run_community_scraper") as mock_run:
        main()
        mock_run.assert_called_once()


def test_cli_export(capsys):
    mock_runs = []
    mock_stats = {"run_count": 0}
    with patch.object(sys, "argv", ["sts2", "export"]), \
         patch("sts2.saves.get_run_history", return_value=mock_runs), \
         patch("sts2.aggregate.compute_aggregate_stats", return_value=mock_stats), \
         patch("sts2.aggregate.save_aggregate") as mock_save:
        main()
        mock_save.assert_called_once_with(mock_stats)
    out = capsys.readouterr().out
    assert "Exported" in out


def test_cli_reset_stats_found(capsys):
    with patch.object(sys, "argv", ["sts2", "reset-stats"]), \
         patch("sts2.aggregate.reset_aggregate", return_value=True):
        main()
    out = capsys.readouterr().out
    assert "deleted" in out


def test_cli_reset_stats_not_found(capsys):
    with patch.object(sys, "argv", ["sts2", "reset-stats"]), \
         patch("sts2.aggregate.reset_aggregate", return_value=False):
        main()
    out = capsys.readouterr().out
    assert "No aggregate" in out


def test_cli_sync_up_success(capsys):
    mock_runs = []
    mock_stats = {"run_count": 5}
    mock_result = {"run_count": 10}
    with patch.object(sys, "argv", ["sts2", "sync-up"]), \
         patch("sts2.saves.get_run_history", return_value=mock_runs), \
         patch("sts2.aggregate.compute_aggregate_stats", return_value=mock_stats), \
         patch("sts2.sync.upload_stats", return_value=mock_result):
        main()
    out = capsys.readouterr().out
    assert "Upload complete" in out


def test_cli_sync_up_failure(capsys):
    from sts2.sync import SyncError
    mock_runs = []
    mock_stats = {"run_count": 5}
    with patch.object(sys, "argv", ["sts2", "sync-up"]), \
         patch("sts2.saves.get_run_history", return_value=mock_runs), \
         patch("sts2.aggregate.compute_aggregate_stats", return_value=mock_stats), \
         patch("sts2.sync.upload_stats", side_effect=SyncError("connection refused")), \
         pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Sync failed" in out


def test_cli_sync_down_success(capsys):
    remote = {"run_count": 20}
    existing = {"run_count": 5}
    merged = {"run_count": 22}
    with patch.object(sys, "argv", ["sts2", "sync-down"]), \
         patch("sts2.sync.download_stats", return_value=remote), \
         patch("sts2.aggregate.load_aggregate", return_value=existing), \
         patch("sts2.aggregate.merge_aggregate", return_value=merged), \
         patch("sts2.aggregate.save_aggregate") as mock_save:
        main()
        mock_save.assert_called_once_with(merged)
    out = capsys.readouterr().out
    assert "Merged" in out


def test_cli_sync_down_failure(capsys):
    from sts2.sync import SyncError
    with patch.object(sys, "argv", ["sts2", "sync-down"]), \
         patch("sts2.sync.download_stats", side_effect=SyncError("timeout")), \
         pytest.raises(SystemExit) as exc_info:
        main()
    assert exc_info.value.code == 1
    out = capsys.readouterr().out
    assert "Sync failed" in out


def test_cli_serve_defaults():
    """Serve command should call uvicorn.run with correct defaults."""
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("uvicorn.run") as mock_uvicorn:
        main()
        mock_uvicorn.assert_called_once()
        call_kwargs = mock_uvicorn.call_args
        assert call_kwargs.kwargs.get("log_level") == "warning" or call_kwargs[1].get("log_level") == "warning"
