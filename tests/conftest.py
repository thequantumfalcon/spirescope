"""Shared test configuration and fixtures."""
import atexit
import json
import os
import shutil
import tempfile
from pathlib import Path

# Force the rate-limiter to engage during tests. The app skips rate-limiting
# when bound to loopback (single-user dashboard, no real attack surface), but
# the rate-limit tests need the middleware active to assert on its headers.
# Set BEFORE importing sts2.app so any import-time reads see the override.
# Unconditional assignment (was setdefault): a dev shell with STS2_HOST=127.0.0.1
# would silently bypass the rate-limiter and break those tests.
os.environ["STS2_HOST"] = "0.0.0.0"

# A non-loopback bind engages the network auth gate, so give the suite a
# token; the shared client below presents it on every request. Auth-specific
# tests build their own clients without the default header.
os.environ["STS2_AUTH_TOKEN"] = "test-auth-token"

# Admin endpoints are disabled when no token is configured (nothing is
# auto-generated any more); the admin-route tests need them enabled.
os.environ["SPIRESCOPE_ADMIN_TOKEN"] = "test-admin-token"

# Pin the suite to English: KnowledgeBase now applies the persisted UI
# language's content overlay, so without this a developer who picked German
# in Settings would fail every English-name assertion locally.
os.environ["STS2_LANG"] = "en"

# Keep the suite hermetic: without this the log tailer resolves godot.log
# under the real APPDATA and live-run tests read whatever game session this
# machine last played.
os.environ["STS2_LOG_FILE"] = str(Path(__file__).parent / "_no_such_godot.log")

# The same for the rest of this machine's game and Spirescope state. With the
# game installed, every KnowledgeBase built without an explicit version used
# the reviewed profile for the installed build, while CI (no game) used the
# bundle, so catalog assertions passed in CI and failed locally. Unpatched
# route tests read the real save history, and the import and reset routes
# wrote to and then deleted the real community_aggregate.json. The one
# end-to-end test against a real install (test_localize.py) finds the game
# itself, starting from whatever STS2_GAME_DIR said before this override.
_TEST_MACHINE = Path(tempfile.mkdtemp(prefix="spirescope-tests-"))
# setdefault: pytest-xdist workers inherit this process's environment, where
# STS2_GAME_DIR is already the hidden folder, so only the first process
# records it. "detect" rather than an empty string, because Windows drops an
# empty variable from the environment child processes inherit.
os.environ.setdefault("SPIRESCOPE_TEST_REAL_GAME_DIR", os.environ.get("STS2_GAME_DIR") or "detect")
os.environ["STS2_GAME_DIR"] = str(_TEST_MACHINE / "no-game")
os.environ["STS2_SAVE_DIR"] = str(_TEST_MACHINE / "no-saves")
os.environ["STS2_STATE_DIR"] = str(_TEST_MACHINE / "state")
os.environ["STS2_MODS_DIR"] = str(_TEST_MACHINE / "state" / "mods")

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

import sts2.app
from sts2.app import _rate_limit_store, app

DATA_DIR = Path(__file__).parent.parent / "sts2" / "data"

# Minimum data files required for tests to run meaningfully
_REQUIRED_FILES = ["cards.json", "relics.json", "potions.json", "enemies.json", "events.json"]


def pytest_configure(config):
    """Verify test data files exist before running the suite."""
    missing = [f for f in _REQUIRED_FILES if not (DATA_DIR / f).exists()]
    if missing:
        pytest.exit(
            f"Missing data files in sts2/data/: {', '.join(missing)}. "
            f"Run 'python -m sts2 update' or restore from git.",
            returncode=1,
        )
    # Also verify files aren't empty
    for f in _REQUIRED_FILES:
        path = DATA_DIR / f
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not data:
                pytest.exit(f"Data file sts2/data/{f} is empty. Run 'python -m sts2 update'.", returncode=1)
        except json.JSONDecodeError:
            pytest.exit(f"Data file sts2/data/{f} contains invalid JSON.", returncode=1)


@pytest.fixture(autouse=True)
def _clear_rate_limits():
    """Clear rate limit store and the live-run memo before every test —
    cross-test 429s and a 2.5s-stale CurrentRun both make tests flaky."""
    _rate_limit_store.clear()
    from sts2.routes import _live_memo
    _live_memo.clear()


_TEST_MACHINE_HANDLED = False


def _remove_test_machine():
    """Remove the run's private state directory, unless importing the app moved
    pre-3.0.3 state or user-added mods out of sts2/data into it: those files
    belong to the developer, so keep them and say where they went."""
    global _TEST_MACHINE_HANDLED
    if _TEST_MACHINE_HANDLED or not _TEST_MACHINE.exists():
        return
    _TEST_MACHINE_HANDLED = True
    if sts2.app._migrated:
        print(f"\nSpirescope moved {sts2.app._migrated} from sts2/data into "
              f"{_TEST_MACHINE / 'state'}; that directory was kept.")
        return
    shutil.rmtree(_TEST_MACHINE, ignore_errors=True)


def pytest_sessionfinish(session, exitstatus):
    _remove_test_machine()


# Also at interpreter exit: a tool that imports this module outside a pytest
# session never reaches pytest_sessionfinish and used to leave the folder.
atexit.register(_remove_test_machine)


@pytest_asyncio.fixture(scope="module")
async def client():
    """Module-scoped async HTTP client — opened once, reused across all tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test",
                           headers={"X-Auth-Token": os.environ["STS2_AUTH_TOKEN"]}) as c:
        yield c
