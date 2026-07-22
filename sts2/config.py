"""Configuration for Spirescope."""
import os
import sys
from pathlib import Path

# Single source of truth for the version fallback (used when importlib.metadata
# can't find the package, e.g. in PyInstaller bundles). Keep in sync with
# pyproject.toml [project] version.
VERSION = "2.10.0"

# Project paths
PROJECT_ROOT = Path(__file__).parent
# Data bundled with the package/executable (read-only in frozen builds)
BUNDLED_DATA_DIR = PROJECT_ROOT / "data"


def _find_data_dir() -> Path:
    """Writable game-data directory.

    Frozen builds extract to an ephemeral dir, so installed data updates
    would vanish on restart — redirect to a dir next to the executable
    (seeded from the bundled data by ensure_data_dir()).
    """
    env = os.environ.get("STS2_DATA_DIR")
    if env:
        return Path(env)
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent / "data"
    return BUNDLED_DATA_DIR


DATA_DIR = _find_data_dir()


def ensure_data_dir() -> None:
    """Seed DATA_DIR from the bundled data on first run (frozen builds)."""
    if DATA_DIR == BUNDLED_DATA_DIR or (DATA_DIR / "cards.json").exists():
        return
    import shutil
    try:
        shutil.copytree(BUNDLED_DATA_DIR, DATA_DIR, dirs_exist_ok=True)
    except OSError as exc:
        # Fall back silently: knowledge loading tolerates missing files
        import logging
        logging.getLogger(__name__).error("Failed to seed data dir: %s", exc)


TEMPLATES_DIR = PROJECT_ROOT / "templates"
STATIC_DIR = PROJECT_ROOT / "static"


def _find_save_dirs() -> list[Path]:
    """Auto-detect ALL STS2 save directories for the active profile.

    STS2 stores modded saves in a separate directory tree:
      Vanilla: steam/<id>/profile1/saves/
      Modded:  steam/<id>/modded/profile1/saves/

    Since game v0.108.0 a first modded launch copies vanilla saves into the
    modded tree, so run history is split across both. All save dirs belonging
    to the same steam id + profile name are returned together (freshest tree
    first) so history can be merged; other profiles are excluded — they are
    separate players and merging them would conflate their stats.

    STS2_SAVE_DIR overrides detection and accepts an os.pathsep-separated
    list of directories.
    """
    # Environment variable override
    env_dir = os.environ.get("STS2_SAVE_DIR")
    if env_dir:
        return [Path(p) for p in env_dir.split(os.pathsep) if p]

    # Platform-specific AppData location
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))

    sts2_dir = base / "SlayTheSpire2"

    # Steam Deck (Proton): saves are in the Wine/Proton prefix
    if sys.platform == "linux":
        proton_base = (
            Path.home() / ".local" / "share" / "Steam" / "steamapps"
            / "compatdata" / "2832040" / "pfx" / "drive_c" / "users"
            / "steamuser" / "AppData" / "Local" / "SlayTheSpire2"
        )
        if proton_base.exists():
            sts2_dir = proton_base

    if not sts2_dir.exists():
        return [sts2_dir / "saves"]  # Return plausible path even if missing

    # Walk steam/<id>/ grouping vanilla+modded save dirs per profile
    steam_dir = sts2_dir / "steam"
    groups: dict[tuple[str, str], list[Path]] = {}
    if steam_dir.exists():
        for steam_id_dir in steam_dir.iterdir():
            if not steam_id_dir.is_dir():
                continue
            # Vanilla profiles: steam/<id>/profile*/saves/
            for profile_dir in sorted(steam_id_dir.iterdir()):
                if profile_dir.is_dir() and profile_dir.name.startswith("profile"):
                    saves = profile_dir / "saves"
                    if saves.exists():
                        groups.setdefault(
                            (steam_id_dir.name, profile_dir.name), []
                        ).append(saves)
            # Modded profiles: steam/<id>/modded/profile*/saves/
            modded_dir = steam_id_dir / "modded"
            if modded_dir.exists():
                for profile_dir in sorted(modded_dir.iterdir()):
                    if profile_dir.is_dir() and profile_dir.name.startswith("profile"):
                        saves = profile_dir / "saves"
                        if saves.exists():
                            groups.setdefault(
                                (steam_id_dir.name, profile_dir.name), []
                            ).append(saves)

    if not groups:
        return [sts2_dir / "saves"]

    # Active profile = the group holding the most recent run data
    active = max(
        groups.values(),
        key=lambda dirs: max(_save_dir_freshness(d) for d in dirs),
    )
    return sorted(active, key=_save_dir_freshness, reverse=True)


def _find_save_dir() -> Path:
    """The freshest save directory (live current_run reads come from here)."""
    return _find_save_dirs()[0]


def _save_dir_freshness(save_dir: Path) -> float:
    """Return the modification time of the newest run file, or 0."""
    history = save_dir / "history"
    if not history.exists():
        return 0.0
    newest = 0.0
    try:
        for f in history.iterdir():
            if f.suffix == ".run":
                mtime = f.stat().st_mtime
                if mtime > newest:
                    newest = mtime
    except OSError:
        pass
    return newest


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
SAVE_DIRS = _find_save_dirs()
SAVE_DIR = SAVE_DIRS[0]
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

# Community sources: "all", "reddit", "steam", or comma-separated (e.g. "reddit,steam")
COMMUNITY_SOURCES = os.environ.get("STS2_COMMUNITY_SOURCES", "all")

# Characters
CHARACTERS = ["Ironclad", "Silent", "Defect", "Necrobinder", "Regent"]
CHARACTER_IDS = {
    "CHARACTER.IRONCLAD": "Ironclad",
    "CHARACTER.SILENT": "Silent",
    "CHARACTER.DEFECT": "Defect",
    "CHARACTER.NECROBINDER": "Necrobinder",
    "CHARACTER.REGENT": "Regent",
}
