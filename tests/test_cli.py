"""Tests for the CLI entry point (__main__.py)."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

from sts2.__main__ import _get_version, _should_open_browser, main

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
    mock_fetcher = MagicMock()
    with patch.object(sys, "argv", ["sts2", "update"]), \
         patch.dict("sys.modules", {"sts2.fetcher": mock_fetcher}), \
         patch("sts2.__main__.run_fetcher", create=True) as mock_run:
        # Need to patch the actual import inside main()
        with patch("sts2.fetcher.run_fetcher") as mock_run:
            main()
            mock_run.assert_called_once_with(save_only=False)


def test_cli_update_save_only():
    with patch.object(sys, "argv", ["sts2", "update", "--save-only"]), \
         patch("sts2.fetcher.run_fetcher") as mock_run:
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


def test_should_open_browser_default_source():
    with patch.object(sys, "frozen", False, create=True), \
         patch.dict("os.environ", {}, clear=False):
        assert _should_open_browser([]) is True


def test_should_open_browser_default_frozen():
    """A packaged build must open the browser too.

    The default used to be "source yes, frozen no", which is inverted relative
    to who runs each: the exe is what a player double-clicks, and it left them
    staring at a console telling them to type a URL. The antivirus mitigation
    is the visible console, not this.
    """
    with patch.object(sys, "frozen", True, create=True), \
         patch.dict("os.environ", {}, clear=False):
        assert _should_open_browser([]) is True


def test_should_open_browser_frozen_respects_opt_outs():
    """Flipping the default must not remove the ways to turn it off."""
    with patch.object(sys, "frozen", True, create=True):
        with patch.dict("os.environ", {}, clear=False):
            assert _should_open_browser(["--no-browser"]) is False
        with patch.dict("os.environ", {"SPIRESCOPE_OPEN_BROWSER": "0"}, clear=False):
            assert _should_open_browser([]) is False


def test_should_open_browser_env_override():
    with patch.object(sys, "frozen", True, create=True), \
         patch.dict("os.environ", {"SPIRESCOPE_OPEN_BROWSER": "1"}, clear=False):
        assert _should_open_browser([]) is True


def test_should_open_browser_flag_override():
    with patch.object(sys, "frozen", True, create=True), \
         patch.dict("os.environ", {"SPIRESCOPE_OPEN_BROWSER": "0"}, clear=False):
        assert _should_open_browser(["--browser"]) is True


# ── Environment flag parsing ─────────────────────────────────────────────

@pytest.mark.parametrize("raw, expected", [
    ("1", True), ("true", True), ("YES", True), (" On ", True),
    ("0", False), ("false", False), ("no", False), ("OFF", False),
    ("maybe", None), ("", None),
])
def test_env_flag_reads_the_usual_spellings(raw, expected):
    """An unrecognised value must read as "unset", not as False -- otherwise a
    typo silently turns a feature off instead of falling through to the
    default."""
    from sts2.__main__ import _env_flag
    with patch.dict("os.environ", {"SPIRESCOPE_TEST_FLAG": raw}, clear=False):
        assert _env_flag("SPIRESCOPE_TEST_FLAG") is expected


def test_env_flag_of_an_unset_variable_is_none():
    from sts2.__main__ import _env_flag
    with patch.dict("os.environ", {}, clear=False):
        os.environ.pop("SPIRESCOPE_TEST_FLAG", None)
        assert _env_flag("SPIRESCOPE_TEST_FLAG") is None


# ── Program name in the help text ────────────────────────────────────────

def test_program_name_matches_a_packaged_build():
    """A packaged build has no `spirescope` on PATH, so printing that name
    tells the reader to run something they do not have."""
    from sts2.__main__ import _program_name
    # Built with os.path.join rather than a literal Windows path: basename()
    # only splits on the host separator, so a hardcoded backslash path is the
    # whole string on Linux and macOS.
    exe = os.path.join("Games", "Spirescope", "Spirescope.exe")
    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", exe):
        assert _program_name() == "Spirescope.exe"


def test_program_name_of_a_source_checkout_is_the_entry_point():
    from sts2.__main__ import _program_name
    with patch.object(sys, "frozen", False, create=True):
        assert _program_name() == "spirescope"


# ── Rarity canonicalization after a wiki refresh ─────────────────────────

def test_rarity_canonicalization_is_a_no_op_when_the_script_is_absent():
    """Frozen builds ship no scripts/ directory; `update` must not explode."""
    from pathlib import Path

    from sts2.__main__ import _canonicalize_card_rarities
    with patch.object(Path, "exists", lambda _self: False), \
         patch("importlib.util.spec_from_file_location") as spec:
        _canonicalize_card_rarities()
        spec.assert_not_called()


def test_rarity_canonicalization_gives_up_on_an_unloadable_script():
    from sts2.__main__ import _canonicalize_card_rarities
    with patch("importlib.util.spec_from_file_location", return_value=None), \
         patch("importlib.util.module_from_spec") as from_spec:
        _canonicalize_card_rarities()
        from_spec.assert_not_called()


# ── export / sync failure paths ──────────────────────────────────────────

def test_cli_export_reports_a_failed_write(capsys):
    """save_aggregate returns False for an oversized or unwritable file; the
    command used to print success regardless."""
    with patch.object(sys, "argv", ["sts2", "export"]), \
         patch("sts2.saves.get_run_history", return_value=[]), \
         patch("sts2.aggregate.compute_aggregate_stats", return_value={"run_count": 0}), \
         patch("sts2.aggregate.save_aggregate", return_value=False), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "Could not write" in capsys.readouterr().out


def test_cli_sync_down_reports_a_failed_persist(capsys):
    with patch.object(sys, "argv", ["sts2", "sync-down"]), \
         patch("sts2.sync.download_stats", return_value={"run_count": 3}), \
         patch("sts2.aggregate.load_aggregate", return_value={}), \
         patch("sts2.aggregate.merge_aggregate", return_value={"run_count": 3}), \
         patch("sts2.aggregate.save_aggregate", return_value=False), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "could not be persisted" in capsys.readouterr().out


# ── localize ─────────────────────────────────────────────────────────────

def test_cli_localize_lists_available_languages(capsys):
    with patch.object(sys, "argv", ["sts2", "localize", "--list"]), \
         patch("sts2.localize.available_languages", return_value=["de", "ja"]):
        main()
    out = capsys.readouterr().out
    assert "de, ja" in out


def test_cli_localize_list_says_so_when_the_game_offers_nothing(capsys):
    with patch.object(sys, "argv", ["sts2", "localize", "--list"]), \
         patch("sts2.localize.available_languages", return_value=[]):
        main()
    assert "is the game installed?" in capsys.readouterr().out


def test_cli_localize_writes_the_requested_languages(capsys, tmp_path):
    written = []
    for code in ("de", "ja"):
        path = tmp_path / f"{code}.json"
        path.write_text("x" * 2048, encoding="utf-8")
        written.append(path)
    with patch.object(sys, "argv", ["sts2", "localize", "--lang", "de, ja"]), \
         patch("sts2.localize.run", return_value=written) as mock_run:
        main()
        mock_run.assert_called_once_with(langs=["de", "ja"])
    out = capsys.readouterr().out
    assert "Wrote 2 translation file(s)" in out
    assert "de  (2 KB)" in out
    assert "Pick a language under Settings" in out


def test_cli_localize_without_lang_builds_every_language(tmp_path):
    path = tmp_path / "de.json"
    path.write_text("{}", encoding="utf-8")
    with patch.object(sys, "argv", ["sts2", "localize"]), \
         patch("sts2.localize.run", return_value=[path]) as mock_run:
        main()
        mock_run.assert_called_once_with(langs=None)


def test_cli_localize_rejects_a_dangling_lang_flag(capsys):
    with patch.object(sys, "argv", ["sts2", "localize", "--lang"]), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    assert "--lang needs a value" in capsys.readouterr().out


def test_cli_localize_reports_a_missing_game_install(capsys):
    from sts2.localize import LocalizeError
    with patch.object(sys, "argv", ["sts2", "localize"]), \
         patch("sts2.localize.run",
               side_effect=LocalizeError("No SlayTheSpire2.pck under /nowhere")), \
         pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "Could not build translations" in out
    assert "No SlayTheSpire2.pck" in out


def test_cli_localize_says_so_when_nothing_was_produced(capsys):
    with patch.object(sys, "argv", ["sts2", "localize"]), \
         patch("sts2.localize.run", return_value=[]):
        main()
    assert "No translations were produced." in capsys.readouterr().out


# ── serve: browser banner and the network-bind gate ──────────────────────

def test_cli_serve_opens_the_browser_and_says_why_the_console_stays_open(capsys):
    """The console window is a deliberate antivirus mitigation, so it has to
    explain itself -- a bare black window reads as a crash to a player who
    just double-clicked the icon."""
    with patch.object(sys, "argv", ["sts2", "serve", "--browser"]), \
         patch("sts2.__main__.threading.Timer") as timer, \
         patch("uvicorn.run"):
        main()
        timer.assert_called_once()
        assert timer.return_value.start.called
    out = capsys.readouterr().out
    assert "Opening your browser now" in out
    assert "Keep this window open" in out


def test_cli_serve_without_a_browser_tells_you_to_open_the_url(capsys):
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("sts2.__main__.threading.Timer") as timer, \
         patch("uvicorn.run"):
        main()
        timer.assert_not_called()
    assert "auto-open is turned off" in capsys.readouterr().out


def test_cli_serve_on_a_network_bind_explains_the_token(capsys):
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("sts2.config.HOST", "0.0.0.0"), \
         patch.dict("os.environ", {"STS2_AUTH_TOKEN": "s3cret"}, clear=False), \
         patch("uvicorn.run") as mock_uvicorn:
        main()
        mock_uvicorn.assert_called_once()
    out = capsys.readouterr().out
    assert "must present STS2_AUTH_TOKEN" in out
    assert "?token=" in out


def test_cli_serve_warns_loudly_about_an_unauthenticated_network_bind(capsys):
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("sts2.config.HOST", "0.0.0.0"), \
         patch.dict("os.environ", {"STS2_ALLOW_UNAUTHENTICATED": "1"}, clear=False), \
         patch("uvicorn.run") as mock_uvicorn:
        os.environ.pop("STS2_AUTH_TOKEN", None)
        main()
        mock_uvicorn.assert_called_once()
    assert "WARNING" in capsys.readouterr().out


def test_cli_serve_refuses_an_unauthenticated_network_bind(capsys):
    """The whole point of the gate: binding to the LAN with no credential must
    not start the server, only explain the two ways to proceed."""
    with patch.object(sys, "argv", ["sts2", "serve", "--no-browser"]), \
         patch("sts2.config.HOST", "0.0.0.0"), \
         patch("uvicorn.run") as mock_uvicorn, \
         patch.dict("os.environ", {}, clear=False):
        os.environ.pop("STS2_AUTH_TOKEN", None)
        os.environ.pop("STS2_ALLOW_UNAUTHENTICATED", None)
        with pytest.raises(SystemExit) as exc:
            main()
        mock_uvicorn.assert_not_called()
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "refusing to bind" in out
    assert "STS2_AUTH_TOKEN" in out
