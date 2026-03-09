"""Entry point for Spirescope: python -m sts2"""
import sys
import webbrowser
import threading

USAGE = """\
Spirescope - Slay the Spire 2 companion dashboard

Usage: spirescope [command] [options]

Commands:
  serve         Start the web dashboard (default)
  update        Fetch latest game data from the wiki
  community     Scrape community tips from Reddit
  export        Export aggregate stats to JSON file
  reset-stats   Delete aggregate stats file
  sync-up       Upload local aggregate stats to sync service
  sync-down     Download and merge community stats from sync service

Options:
  --save-only   With 'update': skip wiki, only discover from save files
  --no-browser  With 'serve': don't open browser automatically
  --help, -h    Show this help message
  --version, -V Show version

Environment:
  STS2_SYNC_URL   Sync service URL (required for sync-up/sync-down)
  STS2_SYNC_KEY   Optional API key for sync service authentication
"""


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("spirescope")
    except Exception:
        from sts2.config import VERSION
        return VERSION


def main():
    args = sys.argv[1:]

    if "--help" in args or "-h" in args:
        print(USAGE)
        return

    if "--version" in args or "-V" in args:
        print(f"Spirescope {_get_version()}")
        return

    command = args[0] if args else "serve"

    if command == "update":
        from sts2.fetcher import run_fetcher
        save_only = "--save-only" in args
        run_fetcher(save_only=save_only)
        return

    if command == "community":
        from sts2.community import run_community_scraper
        run_community_scraper()
        return

    if command == "export":
        from sts2.aggregate import compute_aggregate_stats, save_aggregate
        from sts2.saves import get_run_history
        print("Loading run history...")
        runs = get_run_history()
        print(f"Found {len(runs)} runs, computing stats...")
        stats = compute_aggregate_stats(runs)
        save_aggregate(stats)
        print(f"Exported aggregate stats from {stats.get('run_count', 0)} runs.")
        return

    if command == "reset-stats":
        from sts2.aggregate import reset_aggregate
        if reset_aggregate():
            print("Aggregate stats file deleted.")
        else:
            print("No aggregate stats file found.")
        return

    if command == "sync-up":
        from sts2.sync import upload_stats, SyncError
        from sts2.aggregate import compute_aggregate_stats
        from sts2.saves import get_run_history
        print("Computing local stats...")
        runs = get_run_history()
        stats = compute_aggregate_stats(runs)
        print(f"Uploading stats from {stats.get('run_count', 0)} runs...")
        try:
            result = upload_stats(stats)
            print(f"Upload complete. Server now has {result.get('run_count', '?')} total runs.")
        except SyncError as e:
            print(f"Sync failed: {e}")
            sys.exit(1)
        return

    if command == "sync-down":
        from sts2.sync import download_stats, SyncError
        from sts2.aggregate import load_aggregate, merge_aggregate, save_aggregate
        print("Downloading community stats...")
        try:
            remote = download_stats()
            print(f"Downloaded stats from {remote.get('run_count', 0)} runs.")
            existing = load_aggregate()
            merged = merge_aggregate(existing, remote)
            save_aggregate(merged)
            print(f"Merged. Local aggregate now has {merged.get('run_count', 0)} runs.")
        except SyncError as e:
            print(f"Sync failed: {e}")
            sys.exit(1)
        return

    if command == "serve":
        from sts2.config import HOST, PORT
        import uvicorn

        url = f"http://{HOST}:{PORT}"
        if "--no-browser" not in args:
            threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"\n  Spirescope {_get_version()} starting at {url}")
        if HOST not in ("127.0.0.1", "localhost", "::1"):
            print("  WARNING: Spirescope is designed for single-user local use.")
            print("  Binding to a public address exposes it without authentication.\n")
        else:
            print()
        from sts2.app import app
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
        return

    print(f"Unknown command: {command}\n")
    print(USAGE)
    sys.exit(1)

if __name__ == "__main__":
    main()
