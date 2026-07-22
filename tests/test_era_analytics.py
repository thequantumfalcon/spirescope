"""P4 patch-era analytics: era resolution, scope filter, pre/post split."""
import json

import pytest

from sts2 import patches as patch_manifest
from sts2.analytics import compute_era_split
from sts2.models import RunFloor, RunHistory
from sts2.routes import _filter_runs

MANIFEST = [
    {"patch": "v0.108.0", "date": "2026-07-03", "branch": "beta",
     "build_ids": ["v0.108.0"],
     "changed": {"cards": [], "relics": [], "enemies": []}},
    {"patch": "v0.109.0", "date": "2026-07-17", "branch": "beta",
     "build_ids": ["v0.109.0", "v0.109.1"],
     "changed": {"cards": ["CARD.TAUNT"], "relics": [], "enemies": []}},
]


@pytest.fixture(autouse=True)
def _manifest(tmp_path, monkeypatch):
    (tmp_path / "patches.json").write_text(json.dumps(MANIFEST))
    monkeypatch.setattr(patch_manifest, "DATA_DIR", tmp_path)
    patch_manifest.invalidate_cache()
    yield
    patch_manifest.invalidate_cache()


def _run(build_id, win=False, deck=(), offered_taunt=False, picked_taunt=False):
    floors = []
    if offered_taunt:
        floors.append(RunFloor(
            floor=1, type="MONSTER", cards_offered=["CARD.TAUNT", "CARD.X"],
            card_picked="CARD.TAUNT" if picked_taunt else "CARD.X",
        ))
    return RunHistory(id=f"r{build_id}{win}{len(deck)}", character="Ironclad",
                      win=win, build_id=build_id, deck=list(deck),
                      floors=floors)


def test_era_helpers():
    assert patch_manifest.era_of("v0.109.0") == "v0.109.0"
    assert patch_manifest.era_of("v0.109.1") == "v0.109.0"  # hotfix mapped
    assert patch_manifest.era_of("v0.98.2") == "unmapped"
    assert patch_manifest.current_patch()["patch"] == "v0.109.0"
    assert patch_manifest.era_index("v0.108.0") == 0
    assert patch_manifest.era_index("unmapped") == -1


def test_scope_filter_current_patch():
    runs = [_run("v0.108.0"), _run("v0.109.0"), _run("v0.109.1"), _run("v0.98.2")]
    current = _filter_runs(runs, scope="current")
    assert [r.build_id for r in current] == ["v0.109.0", "v0.109.1"]
    assert len(_filter_runs(runs, scope=None)) == 4
    assert len(_filter_runs(runs, scope="all")) == 4


def test_era_split_two_builds():
    """G4 fixture: runs across two build_ids split into correct eras."""
    runs = (
        # before (v0.108.0): 12 runs with Taunt, 6 wins
        [_run("v0.108.0", win=(i % 2 == 0), deck=["CARD.TAUNT"],
              offered_taunt=True, picked_taunt=True) for i in range(12)]
        # after (v0.109.0/v0.109.1): 10 with Taunt, 8 wins
        + [_run("v0.109.0", win=(i < 8), deck=["CARD.TAUNT"],
                offered_taunt=True, picked_taunt=(i < 5)) for i in range(10)]
        # unmapped era: excluded entirely
        + [_run("v0.98.2", win=True, deck=["CARD.TAUNT"])] * 5
    )
    split = compute_era_split(runs, "CARD.TAUNT", "v0.109.0")
    assert split["before"] == {"n": 12, "insufficient": False,
                               "win_rate": 50.0, "pick_rate": 100.0}
    assert split["after"]["n"] == 10
    assert split["after"]["win_rate"] == 80.0
    assert split["after"]["pick_rate"] == 50.0


def test_era_split_low_n_guard():
    runs = [_run("v0.109.0", win=True, deck=["CARD.TAUNT"])] * 3
    split = compute_era_split(runs, "CARD.TAUNT", "v0.109.0")
    assert split["after"] == {"n": 3, "insufficient": True}
    assert "win_rate" not in split["after"]


def test_era_split_unknown_patch_or_no_data():
    assert compute_era_split([_run("v0.109.0")], "CARD.TAUNT", "v9.9.9") is None
    assert compute_era_split([_run("v0.98.2", deck=["CARD.TAUNT"])],
                             "CARD.TAUNT", "v0.109.0") is None
