"""Multi-save-dir merge + dedupe (v0.108.0 modded save-copy support)."""
import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

from sts2.config import _find_save_dirs
from sts2.routes import _filter_runs
from sts2.saves import get_run_history


def _run_json(marker: str) -> str:
    """Minimal valid run-history JSON; marker makes content distinguishable."""
    return json.dumps({
        "win": False,
        "ascension": 1,
        "seed": marker,
        "build_id": "v0.109.0",
        "players": [{"character": "CHAR.IRONCLAD", "deck": [], "relics": []}],
        "map_point_history": [],
    })


def _make_tree(root: Path, modded: bool) -> Path:
    """Create a save tree; returns its saves/ dir."""
    sub = ("steam", "1", "modded", "profile1", "saves") if modded else \
          ("steam", "1", "profile1", "saves")
    saves = root.joinpath(*sub)
    (saves / "history").mkdir(parents=True)
    return saves


def _write_runs(saves: Path, runs: dict[str, str]):
    for stem, content in runs.items():
        (saves / "history" / f"{stem}.run").write_text(content)


def _patch_dirs(vanilla: Path, modded: Path):
    return (
        patch("sts2.saves.SAVE_DIRS", [vanilla, modded]),
        patch("sts2.saves.SAVE_DIR", vanilla),
    )


def test_sc3_merged_history_exactly_seven(tmp_path):
    """SC3 fixture: 3 stems copied between trees + 2 unique per tree -> 7 runs."""
    vanilla = _make_tree(tmp_path, modded=False)
    modded = _make_tree(tmp_path, modded=True)
    shared = {f"100{i}": _run_json(f"shared-{i}") for i in range(3)}
    _write_runs(vanilla, {**shared, "2001": _run_json("v1"), "2002": _run_json("v2")})
    _write_runs(modded, {**shared, "3001": _run_json("m1"), "3002": _run_json("m2")})

    p1, p2 = _patch_dirs(vanilla, modded)
    with p1, p2:
        runs = get_run_history()

    assert len(runs) == 7
    ids = [r.id for r in runs]
    assert len(set(ids)) == 7  # zero duplicates
    assert set(ids) == {"1000", "1001", "1002", "2001", "2002", "3001", "3002"}


def test_copied_run_kept_once_with_first_tree_origin(tmp_path):
    vanilla = _make_tree(tmp_path, modded=False)
    modded = _make_tree(tmp_path, modded=True)
    _write_runs(vanilla, {"1000": _run_json("same")})
    _write_runs(modded, {"1000": _run_json("same")})

    p1, p2 = _patch_dirs(vanilla, modded)
    with p1, p2:
        runs = get_run_history()

    assert len(runs) == 1
    assert runs[0].id == "1000"
    assert runs[0].origin == "vanilla"  # first (freshest) tree wins


def test_divergent_stem_keeps_both_with_disambiguated_id(tmp_path):
    vanilla = _make_tree(tmp_path, modded=False)
    modded = _make_tree(tmp_path, modded=True)
    _write_runs(vanilla, {"1000": _run_json("edit-a")})
    _write_runs(modded, {"1000": _run_json("edit-b")})

    p1, p2 = _patch_dirs(vanilla, modded)
    with p1, p2:
        runs = get_run_history()

    assert len(runs) == 2
    assert {r.id for r in runs} == {"1000", "1000@modded"}


def test_origin_tagging(tmp_path):
    vanilla = _make_tree(tmp_path, modded=False)
    modded = _make_tree(tmp_path, modded=True)
    _write_runs(vanilla, {"1000": _run_json("v")})
    _write_runs(modded, {"2000": _run_json("m")})

    p1, p2 = _patch_dirs(vanilla, modded)
    with p1, p2:
        runs = get_run_history()

    origins = {r.id: r.origin for r in runs}
    assert origins == {"1000": "vanilla", "2000": "modded"}


def test_single_dir_backcompat(tmp_path):
    """Patching only SAVE_DIR (the established test idiom) keeps single-dir
    semantics — SAVE_DIRS must not resurrect other directories."""
    history = tmp_path / "history"
    history.mkdir()
    (history / "1000.run").write_text(_run_json("solo"))

    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()

    assert [r.id for r in runs] == ["1000"]
    assert runs[0].origin == "vanilla"


def test_find_save_dirs_env_accepts_pathsep_list(tmp_path, monkeypatch):
    a = tmp_path / "a"
    b = tmp_path / "b"
    monkeypatch.setenv("STS2_SAVE_DIR", f"{a}{os.pathsep}{b}")
    assert _find_save_dirs() == [a, b]


def test_find_save_dirs_groups_active_profile(tmp_path, monkeypatch):
    """Vanilla+modded dirs of the freshest profile merge; other profiles are
    excluded (separate players)."""
    monkeypatch.delenv("STS2_SAVE_DIR", raising=False)
    if sys.platform == "win32":
        monkeypatch.setenv("APPDATA", str(tmp_path))
        base = tmp_path
    elif sys.platform == "darwin":
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        base = tmp_path / "Library" / "Application Support"
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        base = tmp_path

    steam_id = base / "SlayTheSpire2" / "steam" / "76561198000000000"
    p1_vanilla = steam_id / "profile1" / "saves"
    p1_modded = steam_id / "modded" / "profile1" / "saves"
    p2_vanilla = steam_id / "profile2" / "saves"
    now = time.time()
    for saves, age in ((p1_vanilla, 100), (p1_modded, 50), (p2_vanilla, 10)):
        (saves / "history").mkdir(parents=True)
        run = saves / "history" / "1000.run"
        run.write_text(_run_json(saves.parts[-2]))
        os.utime(run, (now - age, now - age))

    # profile2 is freshest overall BUT profile1's pair must stay together:
    # the active group is decided by group freshness, so profile2 wins here
    dirs = _find_save_dirs()
    assert dirs == [p2_vanilla]

    # Make profile1's modded tree the freshest -> profile1 group (both dirs)
    os.utime(p1_modded / "history" / "1000.run", (now, now))
    dirs = _find_save_dirs()
    assert dirs == [p1_modded, p1_vanilla]


def test_filter_runs_by_origin(tmp_path):
    vanilla = _make_tree(tmp_path, modded=False)
    modded = _make_tree(tmp_path, modded=True)
    _write_runs(vanilla, {"1000": _run_json("v")})
    _write_runs(modded, {"2000": _run_json("m")})

    p1, p2 = _patch_dirs(vanilla, modded)
    with p1, p2:
        runs = get_run_history()

    assert [r.id for r in _filter_runs(runs, origin="modded")] == ["2000"]
    assert [r.id for r in _filter_runs(runs, origin="vanilla")] == ["1000"]
    assert len(_filter_runs(runs, origin=None)) == 2


# ── co-op: the local player, not the host (issue #4) ──

def _coop_run(host_id: str, guest_id: str) -> str:
    """Run JSON where the HOST is players[0] and the guest played Defect."""
    return json.dumps({
        "win": True, "ascension": 3, "seed": "COOP1", "build_id": "v0.109.0",
        "players": [
            {"id": int(host_id), "character": "CHARACTER.NECROBINDER",
             "deck": [{"id": "CARD.REAP"}], "relics": [{"id": "RELIC.HOST"}]},
            {"id": int(guest_id), "character": "CHARACTER.DEFECT",
             "deck": [{"id": "CARD.ZAP"}], "relics": [{"id": "RELIC.GUEST"}]},
        ],
        "map_point_history": [],
    })


def _steam_saves(tmp_path, steam_id: str):
    saves = tmp_path / "SlayTheSpire2" / "steam" / steam_id / "profile1" / "saves"
    (saves / "history").mkdir(parents=True)
    return saves


def test_coop_history_uses_local_player_not_host(tmp_path):
    """Guest running SpireScope must see their own run, not the host's."""
    saves = _steam_saves(tmp_path, "76561190000000002")
    (saves / "history" / "1000.run").write_text(
        _coop_run("76561190000000001", "76561190000000002"))
    with patch("sts2.saves.SAVE_DIR", saves):
        runs = get_run_history()
    assert runs[0].character == "Defect"        # guest, not host's Necrobinder
    assert runs[0].deck == ["CARD.ZAP"]
    assert runs[0].relics == ["RELIC.GUEST"]
    assert runs[0].total_players == 2


def test_coop_history_when_local_player_is_host(tmp_path):
    saves = _steam_saves(tmp_path, "76561190000000001")
    (saves / "history" / "1000.run").write_text(
        _coop_run("76561190000000001", "76561190000000002"))
    with patch("sts2.saves.SAVE_DIR", saves):
        runs = get_run_history()
    assert runs[0].character == "Necrobinder"
    assert runs[0].deck == ["CARD.REAP"]


def test_unidentifiable_save_dir_falls_back_to_first_player(tmp_path):
    """No steam id in the path (custom STS2_SAVE_DIR) keeps prior behavior."""
    history = tmp_path / "history"
    history.mkdir()
    (history / "1000.run").write_text(
        _coop_run("76561190000000001", "76561190000000002"))
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert runs[0].character == "Necrobinder"


def test_local_steam_id_parsing(tmp_path):
    from sts2.config import local_steam_id
    saves = _steam_saves(tmp_path, "76561190000000009")
    assert local_steam_id(saves) == "76561190000000009"
    assert local_steam_id(tmp_path / "some" / "other" / "path") == ""
    # modded tree keeps the id in the same position
    modded = tmp_path / "steam" / "76561190000000009" / "modded" / "profile1" / "saves"
    assert local_steam_id(modded) == "76561190000000009"


def test_current_run_defaults_to_local_player(tmp_path):
    from sts2.saves import get_current_run
    saves = _steam_saves(tmp_path, "76561190000000002")
    (saves / "current_run.save").write_text(json.dumps({
        "players": [
            {"id": 76561190000000001, "character_id": "CHARACTER.NECROBINDER",
             "current_hp": 10, "max_hp": 80, "deck": [{"id": "CARD.REAP"}],
             "relics": [], "potions": []},
            {"id": 76561190000000002, "character_id": "CHARACTER.DEFECT",
             "current_hp": 55, "max_hp": 70, "deck": [{"id": "CARD.ZAP"}],
             "relics": [], "potions": []},
        ],
        "current_act_index": 0, "run_time": 100,
    }))
    with patch("sts2.saves.SAVE_DIR", saves):
        auto = get_current_run()
        explicit_host = get_current_run(player_index=0)
    assert auto.character == "Defect" and auto.current_hp == 55
    assert auto.player_index == 1
    # ?player=N still selects by seat, so co-op spectating keeps working
    assert explicit_host.character == "Necrobinder" and explicit_host.current_hp == 10
