"""A newer data bundle with sections this version does not know still loads."""
import json
import logging
from pathlib import Path

import pytest

from sts2.mechanics import read_profiles

ROOT = Path(__file__).parents[1]


def _catalog_with(extra_section: dict) -> dict:
    catalog = json.loads((ROOT / "sts2/data/mechanics.json").read_text(encoding="utf-8"))
    catalog["profiles"][0].update(extra_section)
    return catalog


def test_unknown_profile_section_is_ignored_with_a_warning(tmp_path, caplog):
    newer = tmp_path / "mechanics.json"
    newer.write_text(json.dumps(_catalog_with({"powers": {"POWER.STRENGTH": {"description": "x"}}})), encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="sts2.mechanics"):
        profiles = read_profiles(newer)
    profile = profiles["v0.107.1"]
    assert len(profile.cards) == 577 and not hasattr(profile, "powers")
    assert any("powers" in record.getMessage() and "v0.107.1" in record.getMessage() for record in caplog.records)


def test_known_sections_stay_strict(tmp_path):
    catalog = _catalog_with({})
    catalog["profiles"][0]["potions"]["POTION.BLOCK_POTION"]["surprise"] = True
    broken = tmp_path / "mechanics.json"
    broken.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        read_profiles(broken)


def test_schema_version_still_gates_incompatible_shapes(tmp_path):
    catalog = _catalog_with({})
    catalog["schema_version"] = 2
    future = tmp_path / "mechanics.json"
    future.write_text(json.dumps(catalog), encoding="utf-8")
    with pytest.raises(ValueError):
        read_profiles(future)
