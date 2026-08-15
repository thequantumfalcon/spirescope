"""Path detection and state migration.

config.py resolves every directory the app touches, and it does so at import
time from the host platform. The branches for the platforms CI does not run
on are therefore invisible: a Windows-only checkout exercises the win32 leg
and nothing else, so a broken macOS or Steam Deck path ships undetected.

The private helpers are called directly here rather than re-importing the
module, because the module-level constants are computed once at import and
re-importing to observe them would leave a second copy of config in
sys.modules for every other test to trip over.
"""
import sys
from pathlib import Path

import pytest

from sts2 import config


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Detection reads the environment first; a real STS2_* var on the dev
    machine would mask every branch below."""
    for var in ("STS2_DATA_DIR", "STS2_STATE_DIR", "STS2_SAVE_DIR",
                "STS2_MODS_DIR", "STS2_GAME_DIR", "STS2_PORT",
                "XDG_DATA_HOME", "APPDATA"):
        monkeypatch.delenv(var, raising=False)


def _home(monkeypatch, path):
    monkeypatch.setattr(Path, "home", classmethod(lambda _cls: path))


# --------------------------------------------------------------- data dir

def test_data_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STS2_DATA_DIR", str(tmp_path / "elsewhere"))
    assert config._find_data_dir() == tmp_path / "elsewhere"


def test_data_dir_of_a_frozen_build_sits_next_to_the_executable(monkeypatch, tmp_path):
    """A frozen build unpacks to a temp dir that is discarded on exit, so
    installed data updates have to live beside the exe or they vanish."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "Spirescope.exe"))
    assert config._find_data_dir() == tmp_path / "app" / "data"


def test_data_dir_of_a_source_checkout_is_the_bundled_one(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert config._find_data_dir() == config.BUNDLED_DATA_DIR


def test_ensure_data_dir_does_nothing_for_a_source_checkout(monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", config.BUNDLED_DATA_DIR)
    config.ensure_data_dir()          # must not raise or copy anything


def test_ensure_data_dir_seeds_an_empty_frozen_data_dir(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "cards.json").write_text("[]", encoding="utf-8")
    target = tmp_path / "beside-exe"
    monkeypatch.setattr(config, "BUNDLED_DATA_DIR", bundled)
    monkeypatch.setattr(config, "DATA_DIR", target)
    config.ensure_data_dir()
    assert (target / "cards.json").read_text(encoding="utf-8") == "[]"


def test_ensure_data_dir_leaves_an_already_seeded_dir_alone(monkeypatch, tmp_path):
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    (bundled / "cards.json").write_text("[]", encoding="utf-8")
    target = tmp_path / "beside-exe"
    target.mkdir()
    (target / "cards.json").write_text('["installed update"]', encoding="utf-8")
    monkeypatch.setattr(config, "BUNDLED_DATA_DIR", bundled)
    monkeypatch.setattr(config, "DATA_DIR", target)
    config.ensure_data_dir()
    assert "installed update" in (target / "cards.json").read_text(encoding="utf-8")


def test_ensure_data_dir_survives_an_unwritable_target(monkeypatch, tmp_path, caplog):
    """Knowledge loading tolerates missing files, so a failed seed must log
    and continue rather than take the whole app down at startup."""
    bundled = tmp_path / "bundled"
    bundled.mkdir()
    monkeypatch.setattr(config, "BUNDLED_DATA_DIR", bundled)
    monkeypatch.setattr(config, "DATA_DIR", tmp_path / "target")

    def boom(*_a, **_kw):
        raise OSError("read-only file system")

    monkeypatch.setattr("shutil.copytree", boom)
    config.ensure_data_dir()
    assert "Failed to seed data dir" in caplog.text


# -------------------------------------------------------------- state dir

def test_state_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STS2_STATE_DIR", str(tmp_path / "state"))
    assert config._find_state_dir() == tmp_path / "state"


@pytest.mark.parametrize("platform, expected_parts", [
    ("win32", ("Roaming", "SpireScope")),
    ("darwin", ("Library", "Application Support", "SpireScope")),
    ("linux", (".local", "share", "SpireScope")),
])
def test_state_dir_follows_each_platform_convention(
        monkeypatch, tmp_path, platform, expected_parts):
    monkeypatch.setattr(sys, "platform", platform)
    _home(monkeypatch, tmp_path)
    result = config._find_state_dir()
    assert result.parts[-len(expected_parts):] == expected_parts


def test_state_dir_on_windows_prefers_appdata(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("APPDATA", str(tmp_path / "AppData" / "Roaming"))
    assert config._find_state_dir() == tmp_path / "AppData" / "Roaming" / "SpireScope"


def test_state_dir_on_linux_prefers_xdg_data_home(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert config._find_state_dir() == tmp_path / "xdg" / "SpireScope"


def test_state_path_creates_the_directory_on_demand(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "fresh")
    path = config.state_path("settings.json")
    assert path.parent.is_dir()
    assert path.name == "settings.json"


def test_state_path_still_returns_a_path_when_the_directory_cannot_be_made(
        monkeypatch, tmp_path, caplog):
    """Callers write through persist.py, which handles its own errors. Raising
    here would break startup on a read-only home directory instead."""
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "nope")

    def boom(*_a, **_kw):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "mkdir", boom)
    assert config.state_path("settings.json").name == "settings.json"
    assert "Could not create state directory" in caplog.text


# --------------------------------------------------------------- migration

def test_migration_moves_pre_303_state_out_of_the_data_dir(monkeypatch, tmp_path):
    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    (data / "settings.json").write_text("{}", encoding="utf-8")
    (data / "hypotheses.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    moved = config.migrate_state_from_data_dir()
    assert sorted(moved) == ["hypotheses.json", "settings.json"]
    assert (state / "settings.json").exists()
    assert not (data / "settings.json").exists()


def test_migration_never_overwrites_state_already_in_the_new_location(
        monkeypatch, tmp_path):
    """The new copy is the live one. Clobbering it with a stale pre-3.0.3 file
    would silently roll the user's settings back."""
    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    state.mkdir()
    (data / "settings.json").write_text('{"old": true}', encoding="utf-8")
    (state / "settings.json").write_text('{"current": true}', encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    assert config.migrate_state_from_data_dir() == []
    assert "current" in (state / "settings.json").read_text(encoding="utf-8")


def test_migration_also_checks_beside_a_frozen_executable(monkeypatch, tmp_path):
    data, state, exe_dir = tmp_path / "data", tmp_path / "state", tmp_path / "exe"
    data.mkdir()
    exe_dir.mkdir()
    (exe_dir / "community_aggregate.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(exe_dir / "Spirescope.exe"))
    assert config.migrate_state_from_data_dir() == ["community_aggregate.json"]
    assert (state / "community_aggregate.json").exists()


def test_migration_moves_user_mods_but_never_the_shipped_readme(
        monkeypatch, tmp_path):
    """mods/ is not purely user state -- the package ships a README in it, and
    moving that out of a source checkout deletes a tracked file."""
    data, state = tmp_path / "data", tmp_path / "state"
    mods = data / "mods"
    mods.mkdir(parents=True)
    (mods / "README.md").write_text("format docs", encoding="utf-8")
    (mods / "my_mod.json").write_text("{}", encoding="utf-8")
    (mods / "subdir").mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    assert config.migrate_state_from_data_dir() == ["mods/my_mod.json"]
    assert (mods / "README.md").exists()
    assert (state / "mods" / "my_mod.json").exists()


def test_migration_skips_a_mod_that_already_exists_in_the_new_location(
        monkeypatch, tmp_path):
    data, state = tmp_path / "data", tmp_path / "state"
    (data / "mods").mkdir(parents=True)
    (data / "mods" / "my_mod.json").write_text('{"old": 1}', encoding="utf-8")
    (state / "mods").mkdir(parents=True)
    (state / "mods" / "my_mod.json").write_text('{"new": 1}', encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    assert config.migrate_state_from_data_dir() == []
    assert "new" in (state / "mods" / "my_mod.json").read_text(encoding="utf-8")


def test_migration_reports_nothing_when_there_is_nothing_to_move(
        monkeypatch, tmp_path):
    data, state = tmp_path / "data", tmp_path / "state"
    data.mkdir()
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)
    assert config.migrate_state_from_data_dir() == []


@pytest.mark.parametrize("victim", ["settings.json", "mods/my_mod.json"])
def test_migration_logs_and_continues_when_a_move_fails(
        monkeypatch, tmp_path, caplog, victim):
    data, state = tmp_path / "data", tmp_path / "state"
    (data / "mods").mkdir(parents=True)
    (data / "settings.json").write_text("{}", encoding="utf-8")
    (data / "mods" / "my_mod.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(config, "DATA_DIR", data)
    monkeypatch.setattr(config, "STATE_DIR", state)

    def boom(*_a, **_kw):
        raise OSError("file in use")

    monkeypatch.setattr("shutil.move", boom)
    assert config.migrate_state_from_data_dir() == []
    assert "Could not migrate" in caplog.text


# --------------------------------------------------------------- save dirs

def test_save_dirs_env_override_accepts_a_list(monkeypatch, tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    import os
    monkeypatch.setenv("STS2_SAVE_DIR", f"{a}{os.pathsep}{b}")
    assert config._find_save_dirs() == [a, b]


def test_save_dirs_env_override_ignores_empty_entries(monkeypatch, tmp_path):
    import os
    monkeypatch.setenv("STS2_SAVE_DIR", f"{tmp_path}{os.pathsep}{os.pathsep}")
    assert config._find_save_dirs() == [tmp_path]


def test_save_dirs_returns_a_plausible_path_when_the_game_never_ran(
        monkeypatch, tmp_path):
    """Returning a path that does not exist yet lets the UI name the directory
    it is watching instead of showing an empty string."""
    monkeypatch.setattr(sys, "platform", "darwin")
    _home(monkeypatch, tmp_path)
    result = config._find_save_dirs()
    assert result == [tmp_path / "Library" / "Application Support"
                      / "SlayTheSpire2" / "saves"]


def test_save_dirs_falls_back_when_the_steam_tree_holds_no_profiles(
        monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    _home(monkeypatch, tmp_path)
    sts2 = tmp_path / "Library" / "Application Support" / "SlayTheSpire2"
    (sts2 / "steam" / "76561198000000000").mkdir(parents=True)
    (sts2 / "steam" / "not-a-dir.txt").write_text("x", encoding="utf-8")
    assert config._find_save_dirs() == [sts2 / "saves"]


def _make_profile(root, steam_id, profile, modded=False, run_mtime=None):
    parts = [root, "steam", steam_id] + (["modded"] if modded else []) + [profile]
    saves = Path(*[str(p) for p in parts]) / "saves"
    history = saves / "history"
    history.mkdir(parents=True)
    if run_mtime is not None:
        run = history / "1000.run"
        run.write_text("{}", encoding="utf-8")
        import os
        os.utime(run, (run_mtime, run_mtime))
    return saves


def test_save_dirs_groups_vanilla_and_modded_trees_freshest_first(
        monkeypatch, tmp_path):
    """Since game v0.108.0 a first modded launch copies vanilla saves across,
    so history lives in both trees and both must be returned."""
    monkeypatch.setattr(sys, "platform", "darwin")
    _home(monkeypatch, tmp_path)
    sts2 = tmp_path / "Library" / "Application Support" / "SlayTheSpire2"
    vanilla = _make_profile(sts2, "7656119", "profile1", run_mtime=1_000)
    modded = _make_profile(sts2, "7656119", "profile1", modded=True, run_mtime=9_000)
    assert config._find_save_dirs() == [modded, vanilla]


def test_save_dirs_picks_the_profile_with_the_freshest_run(monkeypatch, tmp_path):
    """Other profiles are other players; merging their runs would conflate
    two people's statistics."""
    monkeypatch.setattr(sys, "platform", "darwin")
    _home(monkeypatch, tmp_path)
    sts2 = tmp_path / "Library" / "Application Support" / "SlayTheSpire2"
    _make_profile(sts2, "7656119", "profile1", run_mtime=1_000)
    active = _make_profile(sts2, "7656119", "profile2", run_mtime=9_000)
    assert config._find_save_dirs() == [active]


def test_save_dirs_ignores_directories_that_are_not_profiles(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    _home(monkeypatch, tmp_path)
    sts2 = tmp_path / "Library" / "Application Support" / "SlayTheSpire2"
    real = _make_profile(sts2, "7656119", "profile1", run_mtime=1_000)
    (sts2 / "steam" / "7656119" / "screenshots").mkdir(parents=True, exist_ok=True)
    (sts2 / "steam" / "7656119" / "profile_no_saves").mkdir(parents=True)
    assert config._find_save_dirs() == [real]


def test_save_dirs_finds_the_steam_deck_proton_prefix(monkeypatch, tmp_path):
    """On a Steam Deck the saves are inside the Proton prefix, not in the
    native XDG location -- missing this makes the app look empty on Deck."""
    monkeypatch.setattr(sys, "platform", "linux")
    _home(monkeypatch, tmp_path)
    proton = (tmp_path / ".local" / "share" / "Steam" / "steamapps" / "compatdata"
              / "2868840" / "pfx" / "drive_c" / "users" / "steamuser"
              / "AppData" / "Local" / "SlayTheSpire2")
    saves = _make_profile(proton, "7656119", "profile1", run_mtime=5_000)
    assert config._find_save_dirs() == [saves]


def test_find_save_dir_returns_the_freshest_of_the_group(monkeypatch, tmp_path):
    import os
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    monkeypatch.setenv("STS2_SAVE_DIR", f"{a}{os.pathsep}{b}")
    assert config._find_save_dir() == a


# --------------------------------------------------------------- freshness

def test_freshness_of_a_directory_without_history_is_zero(tmp_path):
    assert config._save_dir_freshness(tmp_path) == 0.0


def test_freshness_is_the_newest_run_file(tmp_path):
    import os
    history = tmp_path / "history"
    history.mkdir()
    for name, mtime in (("1.run", 1_000), ("2.run", 5_000), ("notes.txt", 9_000)):
        f = history / name
        f.write_text("{}", encoding="utf-8")
        os.utime(f, (mtime, mtime))
    assert config._save_dir_freshness(tmp_path) == 5_000


def test_freshness_of_an_unreadable_history_is_zero(tmp_path, monkeypatch):
    (tmp_path / "history").mkdir()

    def boom(*_a, **_kw):
        raise OSError("permission denied")

    monkeypatch.setattr(Path, "iterdir", boom)
    assert config._save_dir_freshness(tmp_path) == 0.0


# ------------------------------------------------------------- steam id

@pytest.mark.parametrize("parts, expected", [
    (("SlayTheSpire2", "steam", "76561198000000000", "profile1", "saves"),
     "76561198000000000"),
    (("SlayTheSpire2", "steam", "modded", "profile1", "saves"), ""),
    (("custom", "saves"), ""),
    (("SlayTheSpire2", "steam"), ""),
])
def test_local_steam_id_is_read_from_the_save_path(parts, expected):
    assert config.local_steam_id(Path(*parts)) == expected


def test_local_steam_id_defaults_to_the_detected_save_dir(monkeypatch):
    monkeypatch.setattr(config, "SAVE_DIR",
                        Path("root", "steam", "76561198000000001", "profile1"))
    assert config.local_steam_id() == "76561198000000001"


# --------------------------------------------------------------- mods dir

def test_mods_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STS2_MODS_DIR", str(tmp_path / "mods"))
    assert config._find_mods_dir() == tmp_path / "mods"


def test_mods_dir_of_a_frozen_build_sits_next_to_the_executable(
        monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(tmp_path / "app" / "Spirescope.exe"))
    assert config._find_mods_dir() == tmp_path / "app" / "mods"


def test_mods_dir_of_a_source_checkout_lives_with_user_state(monkeypatch, tmp_path):
    """Not in the data dir: `sts2 update` replaces that wholesale and would
    take the user's mods with it."""
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    assert config._find_mods_dir() == tmp_path / "state" / "mods"


# --------------------------------------------------------------- game dir

def test_game_dir_honours_the_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("STS2_GAME_DIR", str(tmp_path / "game"))
    assert config._find_game_dir() == tmp_path / "game"


def test_game_dir_falls_back_to_the_working_directory(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    monkeypatch.setattr(Path, "exists", lambda _self: False)
    assert config._find_game_dir() == Path(".")


def test_game_dir_scans_every_drive_letter_on_windows(monkeypatch):
    """A Steam library on D: or E: is the common case on Windows, and only
    the win32 leg looks past C:."""
    monkeypatch.setattr(sys, "platform", "win32")
    # Safe off Windows: _find_game_dir builds this same literal, so the two
    # Paths compare equal however the host platform parses the separators.
    target = Path(r"E:\SteamLibrary\steamapps\common\Slay the Spire 2")
    monkeypatch.setattr(Path, "exists", lambda self: self == target)
    assert config._find_game_dir() == target


# ------------------------------------------------------------------- port

@pytest.mark.parametrize("raw, expected", [
    ("9000", 9000),
    ("1", 1),
    ("65535", 65535),
    ("not-a-number", 8000),     # unparseable falls back
    ("", 8000),
    ("0", 8000),                # out of range falls back
    ("65536", 8000),
    ("-1", 8000),
])
def test_port_parsing_rejects_anything_outside_the_valid_range(
        monkeypatch, raw, expected):
    monkeypatch.setenv("STS2_PORT", raw)
    assert config._parse_port() == expected


def test_port_defaults_when_unset(monkeypatch):
    monkeypatch.delenv("STS2_PORT", raising=False)
    assert config._parse_port() == 8000
