"""POST /shutdown stops the server the way Ctrl+C in its console does.

It used to call os.kill(pid, SIGTERM). On Windows that is TerminateProcess:
the process died on the spot, the lifespan cleanup never ran, and a data
install in flight was cut off, leaving its lock file (treated as live for ten
minutes) and an orphan staging directory behind.
"""
import hashlib
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

import pytest

from sts2.app import _ADMIN_TOKEN, generate_csrf_token

REPO = Path(__file__).resolve().parent.parent

# Runs the real `serve` command in a child process, with the app's lifespan
# wrapped so that leaving it writes a marker file. The marker exists only if
# the lifespan's cleanup ran to completion.
_SERVE_WITH_MARKER = r"""
import contextlib
import sys
from pathlib import Path

import sts2.app as spirescope_app

marker = Path(sys.argv[1])
inner = spirescope_app.app.router.lifespan_context


@contextlib.asynccontextmanager
async def lifespan(application):
    async with inner(application):
        yield
    marker.write_text("cleaned up", encoding="utf-8")


spirescope_app.app.router.lifespan_context = lifespan
sys.argv = ["sts2", "serve", "--no-browser"]
from sts2.__main__ import main

main()
print("SERVE RETURNED", flush=True)
"""


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _request(url: str, *, method: str = "GET", headers=None) -> int:
    # No proxy: the request must go straight to the child on loopback.
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, data=b"" if method == "POST" else None,
                                 headers=headers or {}, method=method)
    with opener.open(req, timeout=10) as resp:
        return resp.status


def _hold_live_stream(url: str, opened: threading.Event) -> None:
    """Keep a Live page's event stream open until the server goes away."""
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(url, timeout=300) as resp:
            resp.readline()
            opened.set()
            while resp.read(1):
                pass
    except Exception:  # noqa: BLE001 - the server ending the stream is the point
        pass
    finally:
        opened.set()


def test_shutdown_runs_the_lifespan_cleanup_and_exits_cleanly(tmp_path):
    """With a Live page open, too: a graceful stop waits for open responses,
    and the event stream only idles out after five minutes."""
    port = _free_port()
    marker = tmp_path / "lifespan-cleanup-ran"
    env = dict(os.environ,
               STS2_HOST="127.0.0.1", STS2_PORT=str(port),
               STS2_STATE_DIR=str(tmp_path / "state"),
               STS2_SAVE_DIR=str(tmp_path / "saves"),
               STS2_GAME_DIR=str(tmp_path / "game"),
               STS2_MODS_DIR=str(tmp_path / "mods"),
               STS2_LOG_FILE=str(tmp_path / "godot.log"),
               STS2_LANG="en", SPIRESCOPE_CHECK_UPDATES="0",
               SPIRESCOPE_OPEN_BROWSER="0",
               SPIRESCOPE_ADMIN_TOKEN="graceful-shutdown-test-token")
    child = subprocess.Popen([sys.executable, "-c", _SERVE_WITH_MARKER, str(marker)],
                             cwd=str(REPO), env=env, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE, text=True)
    try:
        base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 180
        while True:
            assert child.poll() is None, child.communicate()[1][-2000:]
            try:
                if _request(base + "/health") == 200:
                    break
            except (urllib.error.URLError, OSError):
                pass
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.2)

        stream_open = threading.Event()
        threading.Thread(target=_hold_live_stream, daemon=True,
                         args=(base + "/api/live/stream", stream_open)).start()
        assert stream_open.wait(30)

        status = _request(base + "/shutdown", method="POST",
                          headers={"X-Admin-Token": "graceful-shutdown-test-token"})
        assert status == 200

        out, err = child.communicate(timeout=60)
    finally:
        if child.poll() is None:
            child.kill()
            child.communicate()

    assert marker.exists(), f"lifespan cleanup did not run (exit {child.returncode}): {err[-2000:]}"
    assert child.returncode == 0, err[-2000:]
    assert "SERVE RETURNED" in out


class _CapturedTimer:
    """Stands in for threading.Timer and keeps what it was asked to run."""

    created: list = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        _CapturedTimer.created.append(self)

    def start(self):
        pass

    def fire(self):
        self.function(*self.args, **self.kwargs)


@pytest.fixture
def captured_timers(monkeypatch):
    import sts2.routes as routes
    _CapturedTimer.created = []
    monkeypatch.setattr(threading, "Timer", _CapturedTimer)
    monkeypatch.setattr(routes, "_server_exit_requested", False)
    return _CapturedTimer.created


async def test_shutdown_asks_the_server_to_exit_instead_of_killing_the_process(
        client, captured_timers):
    with patch("os.kill") as kill, patch("signal.raise_signal") as raise_signal:
        resp = await client.post("/shutdown", headers={"X-Admin-Token": _ADMIN_TOKEN})
        assert resp.status_code == 200
        assert len(captured_timers) == 1
        captured_timers[0].fire()

    import signal
    kill.assert_not_called()
    raise_signal.assert_called_once_with(signal.SIGINT)


async def test_a_second_stop_request_does_not_force_the_exit(client, captured_timers):
    """uvicorn treats a second Ctrl+C as "quit now" and skips the cleanup, so
    a double-clicked Stop button must deliver the request only once."""
    with patch("signal.raise_signal") as raise_signal:
        for _ in range(2):
            resp = await client.post("/shutdown",
                                     headers={"X-CSRF-Token": generate_csrf_token()})
            assert resp.status_code == 200
        for timer in captured_timers:
            timer.fire()

    assert raise_signal.call_count == 1


async def test_shutdown_is_refused_while_a_data_install_runs(client, captured_timers,
                                                             tmp_path, monkeypatch):
    """A real install is held part-way through. Stopping then would leave the
    lock and a staging directory behind, so the request is refused until the
    install finishes."""
    import sts2.updater as updater

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    archive = tmp_path / "bundle.tar.gz"
    archive.write_bytes(b"not checked")
    checksum = tmp_path / "bundle.sha256"
    checksum.write_text(hashlib.sha256(b"not checked").hexdigest())
    monkeypatch.setattr("sts2.config.DATA_DIR", data_dir)

    entered, release = threading.Event(), threading.Event()

    def held_extract(bundle, extract_dir):
        entered.set()
        assert release.wait(30)
        raise updater._RejectBundle("held by the test")

    monkeypatch.setattr(updater, "_extract_capped", held_extract)
    worker = threading.Thread(target=updater.install_data_update,
                              kwargs={"archive": archive, "checksum": checksum})
    worker.start()
    try:
        assert entered.wait(30)
        resp = await client.post("/shutdown", headers={"X-Admin-Token": _ADMIN_TOKEN})
        assert resp.status_code == 409
        assert "data update" in resp.json()["error"].lower()
        assert captured_timers == []
    finally:
        release.set()
        worker.join(30)

    resp = await client.post("/shutdown", headers={"X-Admin-Token": _ADMIN_TOKEN})
    assert resp.status_code == 200
    assert len(captured_timers) == 1
