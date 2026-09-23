"""Compatibility entry point; implementation ships in sts2.corrections.rarity."""
import sys
from pathlib import Path

from sts2.corrections import rarity as implementation
from sts2.corrections.rarity import *  # noqa: F403

DATA_FILE = Path(__file__).resolve().parents[1] / "sts2/data/cards.json"

def main(dry_run=None):
    if dry_run is None:
        dry_run = "--dry-run" in sys.argv
    return implementation.main(dry_run=dry_run, data_path=DATA_FILE)

if __name__ == "__main__":
    sys.exit(main())
