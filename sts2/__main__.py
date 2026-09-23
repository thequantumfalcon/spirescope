"""Entry point for Spirescope: python -m sts2"""
import os
import sys
import threading
import webbrowser

# Guard against custom windowed/frozen builds where stdout/stderr may be None.
# Uvicorn's logger expects a real stream with isatty().
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

def _program_name() -> str:
    """How the reader invoked this, so the help text matches their situation.

    A packaged build has no `spirescope` entry point on PATH and no Python;
    printing "Usage: spirescope" tells that reader to run something they do
    not have.
    """
    if getattr(sys, "frozen", False):
        return os.path.basename(sys.executable)
    return "spirescope"


USAGE = """\
Spirescope - Slay the Spire 2 companion dashboard

Usage: {prog} [command] [options]

Commands:
  serve         Start the web dashboard (default)
  install-data  Install a local data bundle with a SHA-256 checksum file
  validate-data Check a data directory without starting the dashboard
  update        Fetch latest game data from the wiki
  community     Fetch community tips from Steam
  export        Export aggregate stats to JSON file
  reset-stats   Delete aggregate stats file
  localize      Build translated card/relic text from your game install
  sync-up       Upload local aggregate stats to sync service
  sync-down     Download and merge community stats from sync service

Options:
  --browser     With 'serve': force opening browser automatically
  --save-only   With 'update': skip wiki, only discover from save files
  --no-browser  With 'serve': don't open browser automatically
  --lang CODES  With 'localize': comma-separated languages (default: all)
  --list        With 'localize': list languages your game install offers
  --help, -h    Show this help message
  --version, -V Show version

Environment:
  SPIRESCOPE_OPEN_BROWSER  1/0 override for auto-opening browser on 'serve'
  STS2_SYNC_URL   Sync service URL (required for sync-up/sync-down)
  STS2_SYNC_KEY   Optional API key for sync service authentication
"""


def _get_version() -> str:
    from sts2.config import VERSION
    return VERSION


def _run_post_scrape_script(name: str) -> None:
    """Run a packaged correction against the configured writable dataset."""
    from sts2.config import DATA_DIR
    from sts2.corrections import rarity, text
    module = {"fix_card_rarity": rarity, "fix_card_text": text}[name]
    module.main(dry_run=False, data_path=DATA_DIR / "cards.json")


def _canonicalize_card_rarities() -> None:
    """Rarity canonicalization (Basic->Starter, deprecated removal, etc.)."""
    _run_post_scrape_script("fix_card_rarity")


def _pin_card_text() -> None:
    """Re-pin card text the wiki has not caught up on, from patch notes.

    The wiki lags the game, and after the v0.111.0 refresh it was still serving
    text for three cards that two patches had already changed. A scrape that
    returns a plausible string is indistinguishable from a correct one, so the
    corrections are pinned explicitly rather than waited on.
    """
    _run_post_scrape_script("fix_card_text")


def _env_flag(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return None


def _should_open_browser(args: list[str]) -> bool:
    if "--no-browser" in args:
        return False
    if "--browser" in args:
        return True

    env_override = _env_flag("SPIRESCOPE_OPEN_BROWSER")
    if env_override is not None:
        return env_override

    # Open the browser by default everywhere, packaged builds included.
    # Frozen builds used to be excluded, which inverted the default relative to
    # who runs them: the packaged exe is what a player double-clicks, and it
    # greeted them with a console window telling them to go type a URL, while
    # the source run — used by developers, who need it least — opened it.
    # The antivirus mitigation documented in docs/ANTIVIRUS.md is the *visible
    # console* (avoiding the hidden-window profile), which is unchanged here.
    # `--no-browser` and SPIRESCOPE_OPEN_BROWSER=0 still opt out.
    return True


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(USAGE.format(prog=_program_name()))
        return

    if "--version" in args or "-V" in args:
        print(f"Spirescope {_get_version()}")
        return

    # Pick the first positional (non-flag) arg as the command so
    # `python -m sts2 --browser` correctly defaults to "serve" instead of
    # treating "--browser" as an unknown command.
    command = next((a for a in args if not a.startswith("-")), "serve")

    if command == "install-data":
        import argparse
        from pathlib import Path

        from sts2.updater import install_data_update
        parser = argparse.ArgumentParser(prog="spirescope install-data")
        parser.add_argument("archive", type=Path)
        parser.add_argument("--sha256", type=Path, required=True)
        options = parser.parse_args(args[args.index(command) + 1:])
        ok, message = install_data_update(archive=options.archive, checksum=options.sha256)
        print(message)
        sys.exit(0 if ok else 1)

    if command == "validate-data":
        from sts2.data_health import validate_command
        sys.exit(validate_command(args[args.index(command) + 1:]))

    if command == "update":
        from sts2.fetcher import run_fetcher
        save_only = "--save-only" in args
        try:
            run_fetcher(save_only=save_only)
        except (OSError, ValueError, RuntimeError) as exc:
            print(f"Data update failed: {exc}", file=sys.stderr)
            sys.exit(1)
        return

    if command == "community":
        from sts2.community import run_community_scraper
        run_community_scraper()
        return

    if command == "export":
        from sts2.aggregate import _aggregate_storage_path, compute_aggregate_stats, save_aggregate
        from sts2.saves import get_run_history
        from sts2.state_lock import state_lock
        print("Loading run history...")
        runs = get_run_history()
        print(f"Found {len(runs)} runs, computing stats...")
        stats = compute_aggregate_stats(runs)
        try:
            with state_lock(_aggregate_storage_path()):
                if not save_aggregate(stats):
                    raise OSError("Aggregate is too large or unwritable.")
        except OSError as exc:
            print(f"Could not write the aggregate stats file: {exc}")
            sys.exit(1)
        print(f"Exported aggregate stats from {stats.get('run_count', 0)} runs.")
        return

    if command == "reset-stats":
        from sts2.aggregate import reset_aggregate
        if reset_aggregate():
            print("Aggregate stats file deleted.")
        else:
            print("No aggregate stats file found.")
        return

    if command == "localize":
        from sts2.localize import LocalizeError, available_languages, run
        try:
            if "--list" in sys.argv:
                langs = available_languages()
                print("Languages available from your game install:")
                print("  " + ", ".join(langs) if langs
                      else "  none (is the game installed?)")
                return
            wanted = None
            if "--lang" in sys.argv:
                idx = sys.argv.index("--lang")
                if idx + 1 >= len(sys.argv):
                    print("--lang needs a value, e.g. --lang de,ja")
                    sys.exit(1)
                wanted = [c.strip() for c in sys.argv[idx + 1].split(",") if c.strip()]
            print("Reading localization from your game install...")
            written = run(langs=wanted)
        except LocalizeError as exc:
            print(f"Could not build translations: {exc}")
            sys.exit(1)
        if not written:
            print("No translations were produced.")
            return
        print(f"Wrote {len(written)} translation file(s) to "
              f"{written[0].parent}:")
        for path in written:
            print(f"  {path.stem}  ({path.stat().st_size // 1024} KB)")
        print("Pick a language under Settings to use them.")
        return

    if command == "sync-up":
        from sts2.aggregate import compute_aggregate_stats
        from sts2.saves import get_run_history
        from sts2.sync import SyncError, upload_stats
        print("Computing local stats...")
        runs = get_run_history()
        stats = compute_aggregate_stats(runs)
        print(f"Uploading stats from {stats.get('run_count', 0)} runs...")
        try:
            result = upload_stats(stats)
            print(f"Upload complete. Server now has {result.get('run_count', '?')} total runs.")
        except (SyncError, OSError) as e:
            print(f"Sync failed: {e}")
            sys.exit(1)
        return

    if command == "sync-down":
        from sts2.aggregate import (
            DuplicateImportError,
            import_aggregate,
        )
        from sts2.sync import SyncError, download_stats
        print("Downloading community stats...")
        try:
            remote = download_stats()
            print(f"Downloaded stats from {remote.get('run_count', 0)} runs.")
            merged = import_aggregate(remote)
            print(f"Merged. Local aggregate now has {merged.get('run_count', 0)} runs.")
        except (SyncError, OSError) as e:
            print(f"Sync failed: {e}")
            sys.exit(1)
        except DuplicateImportError as e:
            # Nothing new on the server since the last sync-down.
            print(f"Nothing merged: {e}")
        except ValueError as e:
            # The sanitiser's rejections (impossible or non-finite counters)
            # were an uncaught traceback here.
            print(f"Sync failed: downloaded stats rejected: {e}")
            sys.exit(1)
        return

    if command == "serve":
        import uvicorn

        from sts2.config import HOST, PORT

        authority = f"[{HOST}]" if ":" in HOST and not HOST.startswith("[") else HOST
        url = f"http://{authority}:{PORT}"
        open_browser = _should_open_browser(args)
        if open_browser:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        # flush so the banner reaches redirected/supervised logs immediately
        print(f"\n  Spirescope {_get_version()} starting at {url}", flush=True)
        if open_browser:
            # The console stays open on purpose (see docs/ANTIVIRUS.md), so say
            # why — a black window with a log line in it reads like something
            # went wrong to anyone who just double-clicked the icon.
            print("  Opening your browser now. If nothing happens, open the URL above.")
            print("  Keep this window open while you use Spirescope; closing it stops the app.",
                  flush=True)
        else:
            print("  Browser auto-open is turned off. Open the URL above manually.")
            print("  Keep this window open while you use Spirescope; closing it stops the app.",
                  flush=True)
        if HOST not in ("127.0.0.1", "localhost", "::1"):
            if os.environ.get("STS2_AUTH_TOKEN"):
                print("  Network bind: every request must present STS2_AUTH_TOKEN.")
                print(f"  Open {url}/?token=<your token> once per browser to sign in.")
                print("  Use TLS or a reverse proxy for anything beyond a trusted LAN.\n")
            elif os.environ.get("STS2_ALLOW_UNAUTHENTICATED") == "1":
                print("  WARNING: STS2_ALLOW_UNAUTHENTICATED=1 — every client that can")
                print("  reach this port can read your runs and change settings.\n")
            else:
                print("  ERROR: refusing to bind to a non-loopback address without")
                print("  authentication. Set STS2_AUTH_TOKEN to any long random string,")
                print("  or STS2_ALLOW_UNAUTHENTICATED=1 behind a trusted reverse proxy.")
                sys.exit(1)
        else:
            print()
        from sts2.app import app
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
        return

    print(f"Unknown command: {command}\n")
    print(USAGE.format(prog=_program_name()))
    sys.exit(1)

if __name__ == "__main__":
    main()
