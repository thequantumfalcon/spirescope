"""Wiki scraper to update game data files. Run: python -m sts2 update"""
import json
from pathlib import Path
from sts2.config import DATA_DIR


def run_scraper():
    """Placeholder scraper - prints instructions for updating data."""
    print("\n  STS2 Data Updater")
    print("  =================")
    print(f"  Data directory: {DATA_DIR}")
    print()
    print("  Current data files:")
    for f in sorted(DATA_DIR.glob("*.json")):
        data = json.loads(f.read_text(encoding="utf-8"))
        print(f"    {f.name}: {len(data)} entries")
    print()
    print("  To update data, edit the JSON files in the data/ directory.")
    print("  Data sources:")
    print("    - https://slaythespire2.gg/cards")
    print("    - https://slaythespire2.gg/relics")
    print("    - https://slaythespire2.gg/potions")
    print("    - https://sts2.untapped.gg/en/cards")
    print()
    print("  Automated scraping will be added in a future update.")
    print()
