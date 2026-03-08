"""Configuration for Spirescope."""
import os
import sys
from pathlib import Path

# Single source of truth for the version fallback (used when importlib.metadata
# can't find the package, e.g. in PyInstaller bundles). Keep in sync with
# pyproject.toml [project] version.
VERSION = "2.0.0"

# Project paths
PROJECT_ROOT = Path(__file__).parent
DATA_DIR = PROJECT_ROOT / "data"
TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


def _find_save_dir() -> Path:
    """Auto-detect the STS2 save directory across platforms."""
    # Environment variable override
    env_dir = os.environ.get("STS2_SAVE_DIR")
    if env_dir:
        return Path(env_dir)

    # Platform-specific AppData location
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    sts2_dir = base / "SlayTheSpire2"
    if not sts2_dir.exists():
        return sts2_dir / "saves"  # Return plausible path even if missing

    # Walk steam/<id>/profile*/saves/ to find the first valid save dir
    steam_dir = sts2_dir / "steam"
    if steam_dir.exists():
        for steam_id_dir in steam_dir.iterdir():
            if steam_id_dir.is_dir():
                for profile_dir in sorted(steam_id_dir.iterdir()):
                    saves = profile_dir / "saves"
                    if saves.exists():
                        return saves

    return sts2_dir / "saves"


def _find_mods_dir() -> Path:
    """Writable mods directory, external to frozen bundles."""
    env = os.environ.get("STS2_MODS_DIR")
    if env:
        return Path(env)
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent / "mods"
    return DATA_DIR / "mods"


def _find_game_dir() -> Path:
    """Auto-detect the STS2 game install directory."""
    env_dir = os.environ.get("STS2_GAME_DIR")
    if env_dir:
        return Path(env_dir)

    # Common Steam library locations (Windows)
    candidates = [
        Path(r"C:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2"),
        Path(r"C:\Program Files\Steam\steamapps\common\Slay the Spire 2"),
    ]
    # Check all drive letters on Windows
    if sys.platform == "win32":
        for letter in "DEFGHIJKLMNOPQRSTUVWXYZ":
            candidates.append(Path(rf"{letter}:\Program Files (x86)\Steam\steamapps\common\Slay the Spire 2"))
            candidates.append(Path(rf"{letter}:\SteamLibrary\steamapps\common\Slay the Spire 2"))

    for c in candidates:
        if c.exists():
            return c

    return Path(".")  # Fallback


# Game paths (auto-detected)
SAVE_DIR = _find_save_dir()
GAME_INSTALL_DIR = _find_game_dir()
MODS_DIR = _find_mods_dir()

# Server
HOST = os.environ.get("STS2_HOST", "127.0.0.1")


def _parse_port() -> int:
    raw = os.environ.get("STS2_PORT", "8000")
    try:
        port = int(raw)
    except ValueError:
        port = 8000
    if not (1 <= port <= 65535):
        port = 8000
    return port


PORT = _parse_port()

# Aggregate sync (opt-in, empty = disabled)
SYNC_URL = os.environ.get("STS2_SYNC_URL", "")
SYNC_API_KEY = os.environ.get("STS2_SYNC_KEY", "")

# Characters
CHARACTERS = ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent"]
CHARACTER_IDS = {
    "CHARACTER.IRONCLAD": "Ironclad",
    "CHARACTER.SILENT": "Silent",
    "CHARACTER.DEFECT": "Defect",
    "CHARACTER.NECROBINDER": "Necrobinder",
    "CHARACTER.REGENT": "Regent",
}
