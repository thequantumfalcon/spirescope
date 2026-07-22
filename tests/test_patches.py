"""Schema v2 + patch manifest (patches.json) tests."""
import json
import re

import pytest

from sts2 import patches as patch_manifest
from sts2.models import Badge, Card, Enemy, Epoch, Potion, Relic, RunHistory


@pytest.fixture(autouse=True)
def _fresh_cache():
    patch_manifest.invalidate_cache()
    yield
    patch_manifest.invalidate_cache()


# ── schema v2 model migration ──

def test_v1_card_record_loads_unchanged():
    """v1 data (no schema-v2 fields) must load with defaults."""
    card = Card(id="CARD.X", name="X", character="Ironclad", cost="1",
                type="Attack", rarity="Common")
    assert card.mp_only is False
    assert card.branch == ""
    assert card.introduced == ""
    assert card.last_changed == ""
    assert card.tags == []


def test_v2_fields_round_trip():
    card = Card(id="CARD.X", name="X", character="Ironclad", cost="1",
                type="Attack", rarity="Common", mp_only=True, branch="beta",
                introduced="v0.109.0", last_changed="v0.109.0", tags=["enchant"])
    dumped = card.model_dump()
    assert Card(**dumped) == card
    for model, extra in ((Relic, {"rarity": "Rare"}), (Potion, {}),
                         (Enemy, {})):
        obj = model(id="E.X", name="X", branch="main",
                    introduced="v0.107.0", last_changed="v0.109.0", **extra)
        assert model(**obj.model_dump()) == obj


def test_epoch_status_defaults_active():
    e = Epoch(id="EPOCH.X", name="X")
    assert e.status == "active"
    assert Epoch(id="EPOCH.Y", name="Y", status="deprecated").status == "deprecated"


def test_badge_model():
    b = Badge(id="BADGE.X", name="X", requirement="Win a run")
    assert Badge(**b.model_dump()) == b


# ── shipped manifest validates ──

def test_shipped_manifest_schema():
    patches = patch_manifest.load_patches()
    assert len(patches) >= 5
    dates = []
    for p in patches:
        assert isinstance(p["patch"], str) and p["patch"]
        assert re.fullmatch(r"\d{4}(-\d{2}(-\d{2})?)?|", p.get("date", ""))
        assert p["branch"] in ("main", "beta")
        assert isinstance(p["build_ids"], list)
        changed = p["changed"]
        for kind in ("cards", "relics", "enemies"):
            assert isinstance(changed[kind], list)
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", p.get("date", "")):
            dates.append(p["date"])
    # List order is the chronology source of truth; fully-dated entries
    # must be non-decreasing (partial dates like "2026-06" are exempt).
    assert dates == sorted(dates)


def test_shipped_manifest_ids_exist_in_data():
    """Every changed-entity id in the manifest must exist in the data files."""
    from sts2.config import DATA_DIR
    known = set()
    for fname in ("cards.json", "relics.json", "enemies.json"):
        known |= {i["id"] for i in json.loads((DATA_DIR / fname).read_text())}
    for p in patch_manifest.load_patches():
        for kind in ("cards", "relics", "enemies"):
            for eid in p["changed"][kind]:
                assert eid in known, f"{eid} in {p['patch']} not in data"


# ── resolution + unmapped flow ──

def _fake_manifest(tmp_path, monkeypatch):
    manifest = [
        {"patch": "v0.108.0", "date": "2026-07-03", "branch": "beta",
         "build_ids": ["v0.108.0"], "changed": {"cards": ["CARD.A"], "relics": [], "enemies": []}},
        {"patch": "v0.109.0", "date": "2026-07-17", "branch": "beta",
         "build_ids": ["v0.109.0"], "changed": {"cards": ["CARD.A", "CARD.B"], "relics": [], "enemies": []}},
    ]
    (tmp_path / "patches.json").write_text(json.dumps(manifest))
    monkeypatch.setattr(patch_manifest, "DATA_DIR", tmp_path)
    patch_manifest.invalidate_cache()
    return manifest


def _run(build_id):
    return RunHistory(id="1", character="Ironclad", win=False, build_id=build_id)


def test_resolve_build(tmp_path, monkeypatch):
    _fake_manifest(tmp_path, monkeypatch)
    assert patch_manifest.resolve_build("v0.109.0")["patch"] == "v0.109.0"
    assert patch_manifest.resolve_build("v0.98.2") is None
    assert patch_manifest.resolve_build("") is None


def test_unmapped_builds_counts(tmp_path, monkeypatch):
    _fake_manifest(tmp_path, monkeypatch)
    runs = [_run("v0.109.0"), _run("v0.98.2"), _run("v0.98.2"), _run("")]
    unmapped = patch_manifest.unmapped_builds(runs)
    assert unmapped == [{"build_id": "v0.98.2", "count": 2}]


def test_assign_build_persists_and_resolves(tmp_path, monkeypatch):
    _fake_manifest(tmp_path, monkeypatch)
    assert patch_manifest.assign_build("v0.109.1", "v0.109.0") is True
    # persisted to disk, not just cache
    on_disk = json.loads((tmp_path / "patches.json").read_text())
    entry = next(p for p in on_disk if p["patch"] == "v0.109.0")
    assert "v0.109.1" in entry["build_ids"]
    assert patch_manifest.resolve_build("v0.109.1")["patch"] == "v0.109.0"


def test_assign_build_rejects_unknown_patch(tmp_path, monkeypatch):
    _fake_manifest(tmp_path, monkeypatch)
    assert patch_manifest.assign_build("v0.110.0", "nope") is False
    assert patch_manifest.assign_build("", "v0.109.0") is False


def test_changed_in_returns_latest_patch(tmp_path, monkeypatch):
    _fake_manifest(tmp_path, monkeypatch)
    assert patch_manifest.changed_in("CARD.A") == "v0.109.0"
    assert patch_manifest.changed_in("CARD.B") == "v0.109.0"
    assert patch_manifest.changed_in("CARD.NOPE") == ""


def test_missing_manifest_is_tolerated(tmp_path, monkeypatch):
    monkeypatch.setattr(patch_manifest, "DATA_DIR", tmp_path)
    patch_manifest.invalidate_cache()
    assert patch_manifest.load_patches() == []
    assert patch_manifest.resolve_build("v0.109.0") is None
    assert patch_manifest.changed_in("CARD.A") == ""


def test_knowledge_base_loads_v2_data():
    """The shipped (stamped) data files load into the KB without loss."""
    from sts2.knowledge import KnowledgeBase
    kb = KnowledgeBase()
    assert len(kb.cards) > 600
    tutor = next(c for c in kb.cards if c.id == "CARD.TUTOR")
    assert tutor.mp_only is True and tutor.introduced == "v0.109.0"
    taunt = next(c for c in kb.cards if c.id == "CARD.TAUNT")
    assert taunt.last_changed == "v0.109.0"
    diadem = next(r for r in kb.relics if r.id == "RELIC.DIAMOND_DIADEM")
    assert diadem.last_changed == "v0.109.0"
    assert isinstance(kb.badges, list)


def test_mod_namespace_plumbing(tmp_path, monkeypatch):
    """A mod file declaring mod_id gets namespaced entity ids (P7)."""
    import sts2.knowledge as knowledge
    (tmp_path / "spicy.json").write_text(json.dumps({
        "mod_name": "Spicy Mod", "mod_id": "spicy",
        "cards": [{"id": "CARD.HOT", "name": "Hot", "character": "Ironclad",
                    "cost": "1", "type": "Attack", "rarity": "Common"}],
        "relics": [{"id": "RELIC.PEPPER", "name": "Pepper"}],
    }))
    monkeypatch.setattr(knowledge, "MODS_DIR", tmp_path)
    kb = knowledge.KnowledgeBase()
    assert kb.get_card_by_id("mod:spicy:CARD.HOT").name == "Hot"
    assert kb.get_card_by_id("mod:spicy:CARD.HOT").source == "mod"
    assert kb.get_relic_by_id("mod:spicy:RELIC.PEPPER").name == "Pepper"
