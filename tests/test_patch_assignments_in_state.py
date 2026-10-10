"""Build-id assignments are user state: saved under STATE_DIR, never into the
shipped data folder.

assign_build wrote patches.json in DATA_DIR, which is read-only in Docker and
Program Files installs. The failed write was then reported as "Unknown patch
or empty build id.", and the write ran on the event loop.
"""
import json
import os
import stat
import threading
from unittest.mock import patch

import pytest

from sts2 import patches as patch_manifest
from sts2.app import generate_csrf_token

MANIFEST = [
    {"patch": "v0.108.0", "date": "2026-07-03", "branch": "beta",
     "build_ids": ["v0.108.0"], "changed": {"cards": [], "relics": [], "enemies": []}},
    {"patch": "v0.109.0", "date": "2026-07-17", "branch": "beta",
     "build_ids": ["v0.109.0"], "changed": {"cards": [], "relics": [], "enemies": []}},
]


@pytest.fixture
def folders(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "patches.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    state_dir = tmp_path / "state"
    monkeypatch.setattr(patch_manifest, "DATA_DIR", data_dir)
    monkeypatch.setattr("sts2.config.STATE_DIR", state_dir)
    patch_manifest.invalidate_cache()
    yield data_dir, state_dir
    patch_manifest.invalidate_cache()


def _snapshot(folder):
    return {p.name: p.read_bytes() for p in sorted(folder.iterdir())}


def test_assigning_with_a_read_only_data_folder(folders):
    data_dir, state_dir = folders
    before = _snapshot(data_dir)
    manifest = data_dir / "patches.json"
    os.chmod(manifest, stat.S_IREAD)
    if os.name != "nt":
        os.chmod(data_dir, stat.S_IREAD | stat.S_IEXEC)
    try:
        assert patch_manifest.assign_build("v0.109.1", "v0.109.0") is True
    finally:
        os.chmod(data_dir, stat.S_IRWXU)
        os.chmod(manifest, stat.S_IREAD | stat.S_IWRITE)

    assert _snapshot(data_dir) == before
    stored = json.loads((state_dir / "patch_assignments.json").read_text(encoding="utf-8"))
    assert stored == {"v0.109.0": ["v0.109.1"]}
    assert patch_manifest.resolve_build("v0.109.1")["patch"] == "v0.109.0"


def test_an_assignment_outlives_a_replaced_manifest(folders):
    """A data-bundle install replaces patches.json wholesale."""
    data_dir, _state_dir = folders
    assert patch_manifest.assign_build("v0.109.1", "v0.109.0") is True
    (data_dir / "patches.json").write_text(json.dumps(MANIFEST), encoding="utf-8")
    patch_manifest.invalidate_cache()

    assert patch_manifest.resolve_build("v0.109.1")["patch"] == "v0.109.0"
    assert patch_manifest.resolve_build("v0.109.0")["patch"] == "v0.109.0"


def test_build_ids_already_in_patches_json_are_still_honoured(folders):
    data_dir, state_dir = folders
    legacy = json.loads(json.dumps(MANIFEST))
    legacy[0]["build_ids"].append("v0.108.5-assigned-by-an-older-version")
    (data_dir / "patches.json").write_text(json.dumps(legacy), encoding="utf-8")
    patch_manifest.invalidate_cache()

    assert patch_manifest.era_of("v0.108.5-assigned-by-an-older-version") == "v0.108.0"
    assert not (state_dir / "patch_assignments.json").exists()


def test_assigning_an_already_mapped_build_writes_nothing(folders):
    _data_dir, state_dir = folders
    assert patch_manifest.assign_build("v0.109.0", "v0.109.0") is True
    assert not (state_dir / "patch_assignments.json").exists()


def test_an_unwritable_state_folder_raises_instead_of_reporting_a_bad_request(
        folders, tmp_path, monkeypatch):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr("sts2.config.STATE_DIR", blocker / "state")

    with pytest.raises(OSError):
        patch_manifest.assign_build("v0.109.1", "v0.109.0")
    assert patch_manifest.assign_build("v0.109.1", "no-such-patch") is False


async def test_the_route_reports_an_unwritable_state_folder(client, folders, tmp_path,
                                                            monkeypatch):
    blocker = tmp_path / "not-a-folder"
    blocker.write_text("x", encoding="utf-8")
    monkeypatch.setattr("sts2.config.STATE_DIR", blocker / "state")

    resp = await client.post("/admin/patches/assign", data={
        "build_id": "v0.109.1", "patch": "v0.109.0", "csrf_token": generate_csrf_token()})

    assert resp.status_code == 503
    assert "state folder is not writable" in resp.text
    assert "Unknown patch" not in resp.text


async def test_the_route_saves_off_the_event_loop(client):
    loop_thread = threading.get_ident()
    seen = []

    def assign(build_id, patch_name):
        seen.append(threading.get_ident())
        return True

    with patch("sts2.patches.assign_build", side_effect=assign):
        resp = await client.post("/admin/patches/assign", data={
            "build_id": "v1", "patch": "1.0", "csrf_token": generate_csrf_token()},
            follow_redirects=False)

    assert resp.status_code == 303
    assert seen and seen[0] != loop_thread
