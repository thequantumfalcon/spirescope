"""Shared test configuration and fixtures."""
import json
import pytest
from pathlib import Path

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
