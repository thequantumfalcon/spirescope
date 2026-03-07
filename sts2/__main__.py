"""Entry point for Spirescope: python -m sts2"""
import sys
import webbrowser
import threading

def main():
    if len(sys.argv) > 1 and sys.argv[1] == "update":
        from sts2.scraper import run_scraper
        run_scraper()
        return

    from sts2.config import HOST, PORT
    import uvicorn

    url = f"http://{HOST}:{PORT}"
    threading.Timer(1.5, lambda: webbrowser.open(url)).start()
    print(f"\n  Spirescope starting at {url}\n")
    uvicorn.run("sts2.app:app", host=HOST, port=PORT, log_level="warning")

if __name__ == "__main__":
    main()
