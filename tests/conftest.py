"""Shared test configuration and fixtures."""
import json
import os
from pathlib import Path

# Force the rate-limiter to engage during tests. The app skips rate-limiting
# when bound to loopback (single-user dashboard, no real attack surface), but
# the rate-limit tests need the middleware active to assert on its headers.
# Set BEFORE importing sts2.app so any import-time reads see the override.
# Unconditional assignment (was setdefault): a dev shell with STS2_HOST=127.0.0.1
# would silently bypass the rate-limiter and break those tests.
os.environ["STS2_HOST"] = "0.0.0.0"

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

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
    """Clear rate limit store before every test to prevent cross-test 429s."""
    _rate_limit_store.clear()


@pytest_asyncio.fixture(scope="module")
async def client():
    """Module-scoped async HTTP client — opened once, reused across all tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
