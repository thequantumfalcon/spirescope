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

Options:
  --save-only   With 'update': skip wiki, only discover from save files
  --help, -h    Show this help message
  --version, -V Show version
"""


def _get_version() -> str:
    try:
        from importlib.metadata import version
        return version("spirescope")
    except Exception:
        return "1.1.0"


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
        from sts2.scraper import run_scraper
        save_only = "--save-only" in args
        run_scraper(save_only=save_only)
        return

    if command == "community":
        from sts2.community import run_community_scraper
        run_community_scraper()
        return

    if command == "serve":
        from sts2.config import HOST, PORT
        import uvicorn

        url = f"http://{HOST}:{PORT}"
        threading.Timer(1.5, lambda: webbrowser.open(url)).start()
        print(f"\n  Spirescope {_get_version()} starting at {url}\n")
        from sts2.app import app
        uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
        return

    print(f"Unknown command: {command}\n")
    print(USAGE)
    sys.exit(1)

if __name__ == "__main__":
    main()
