"""End-to-end coverage for Rivalry Seeds: import a friend's run, then compare
it against a local run from the Runs page.

Audit finding H5: the import route rendered a friend's run transiently
("not saved locally"), /runs/compare only ever resolved ids against local
save history, and the Runs page only offered compare checkboxes for local
runs. After importing a friend's JSON there was no reachable way to select
it for anything — the only comparison possible was between two of your own
local runs. This file exercises the fix: a bounded, session-scoped store
that /runs/compare and the Runs page both know how to read.
"""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

from sts2.app import generate_csrf_token
from sts2.models import RunHistory
from sts2.routes import _IMPORTED_MAX, _IMPORTED_TTL, _imported_runs


def _run(run_id, *, seed="", win=True, character="Ironclad", ascension=5):
    return RunHistory(id=run_id, character=character, win=win, ascension=ascension,
                      seed=seed, deck=["CARD.BASH"], relics=["RELIC.BURNING_BLOOD"])


async def _post_import(client, run):
    payload = {"format_version": 1, "run": run.model_dump()}
    return await client.post(
        "/runs/import",
        files={"file": (f"{run.id}.json", json.dumps(payload).encode(), "application/json")},
        data={"csrf_token": generate_csrf_token()})


@pytest.fixture(autouse=True)
def _clear_imported_store():
    """_imported_runs is a process-level global in sts2.routes, shared by
    every test module in the session. Clear it before and after each test
    here so the cap/TTL assertions below are exact regardless of import
    order or what other test files left behind."""
    _imported_runs.clear()
    yield
    _imported_runs.clear()


async def test_full_rivalry_seeds_flow(client):
    """Export a run, import it as a friend's JSON, confirm the response says
    it's kept for the session, confirm it's listed on the Runs page with a
    compare checkbox, then compare it against a local run on the same seed
    and confirm both sides render (including the seed-match diff, proving
    rivalry.compare_seed_runs works unmodified on an imported run)."""
    shared_seed = "RIVALRY-SEED-1"
    friend_run = _run("friend-run", seed=shared_seed, character="Silent",
                      win=False, ascension=10)

    # 1) Export a (mocked) local run — this is the file a friend would send.
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=friend_run)):
        export_resp = await client.get(f"/runs/{friend_run.id}/export")
    assert export_resp.status_code == 200

    # 2) Import that exact exported JSON.
    import_resp = await client.post(
        "/runs/import",
        files={"file": ("friend.json", export_resp.text.encode(), "application/json")},
        data={"csrf_token": generate_csrf_token()})
    assert import_resp.status_code == 200

    # 3) The response says it's kept for the session, with a link back to
    # the Runs page — not the old "not saved locally" dead end.
    assert "available for comparison during your session" in import_resp.text
    assert 'href="/runs"' in import_resp.text

    imported_id = "imported-friend-run"
    assert imported_id in _imported_runs

    # 4) The Runs page lists it under "Imported this session" with the same
    # compare-checkbox mechanic local runs get.
    local_run = _run("local-1", seed=shared_seed, character="Ironclad",
                     win=True, ascension=5)
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=[local_run])):
        runs_resp = await client.get("/runs")
    assert runs_resp.status_code == 200
    assert "Imported this session" in runs_resp.text
    assert f'data-run-id="{imported_id}"' in runs_resp.text
    assert "Silent" in runs_resp.text

    # 5) Compare local id + imported id -> 200, both sides render, only the
    # imported side is labeled as such.
    async def resolver(rid):
        return local_run if rid == "local-1" else None
    with patch("sts2.app._get_run_by_id", new=AsyncMock(side_effect=resolver)):
        compare_resp = await client.get(f"/runs/compare?a=local-1&b={imported_id}")
    assert compare_resp.status_code == 200
    assert "Ironclad" in compare_resp.text
    assert "Silent" in compare_resp.text
    assert compare_resp.text.count(">Imported<") == 1
    # Same seed on both sides -> the rivalry seed-match diff renders too.
    assert "Seed-Match Diff" in compare_resp.text


async def test_ttl_expiry_evicts_and_404s_on_compare(client):
    """An imported run older than the TTL is treated as gone: compare 404s
    and the entry is evicted from the store by the lookup itself."""
    run = _run("ttl-run", seed="TTL-SEED")
    imported_id = "imported-ttl-run"
    _imported_runs[imported_id] = (time.monotonic() - _IMPORTED_TTL - 1, run)
    assert imported_id in _imported_runs

    local_run = _run("local-ttl")

    async def resolver(rid):
        return local_run if rid == "local-ttl" else None
    with patch("sts2.app._get_run_by_id", new=AsyncMock(side_effect=resolver)):
        resp = await client.get(f"/runs/compare?a=local-ttl&b={imported_id}")
    assert resp.status_code == 404
    assert imported_id not in _imported_runs


async def test_cap_evicts_oldest_beyond_twenty(client):
    """Once the store holds _IMPORTED_MAX entries, importing one more evicts
    the single oldest entry (by import time) rather than growing unbounded."""
    now = time.monotonic()
    for i in range(_IMPORTED_MAX):
        _imported_runs[f"imported-seed-{i}"] = (now - (_IMPORTED_MAX - i), _run(f"seed-{i}"))
    assert len(_imported_runs) == _IMPORTED_MAX

    resp = await _post_import(client, _run("newcomer"))
    assert resp.status_code == 200

    assert len(_imported_runs) == _IMPORTED_MAX
    assert "imported-seed-0" not in _imported_runs  # oldest of the prefilled batch
    assert "imported-newcomer" in _imported_runs


async def test_unknown_imported_id_404s_cleanly(client):
    """An imported id that was never stored (typo, wrong session, whatever)
    404s the same way an unknown local id does — no 500, no leak."""
    local_run = _run("local-404")

    async def resolver(rid):
        return local_run if rid == "local-404" else None
    with patch("sts2.app._get_run_by_id", new=AsyncMock(side_effect=resolver)):
        resp = await client.get("/runs/compare?a=local-404&b=imported-does-not-exist")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


def test_imported_id_always_fits_the_compare_route_limit():
    """A long source id produced a stored id the compare route's own
    max_length would reject, so the run could be listed on the Runs page but
    never actually selected."""
    from sts2.models import RunHistory
    from sts2.routes import _IMPORTED_ID_MAX_LEN, _imported_runs, _store_imported_run

    _imported_runs.clear()
    long_id = "x" * 500
    stored = _store_imported_run(RunHistory(id=long_id, character="Ironclad",
                                            win=False))
    assert len(stored) <= 200, "stored id exceeds the compare query limit"
    assert stored.startswith("imported-")
    assert len(stored) == len("imported-") + _IMPORTED_ID_MAX_LEN
    _imported_runs.clear()


def test_imported_ids_cannot_shadow_a_local_run_id():
    """Namespacing keeps an imported run from resolving in place of a local
    one with the same id."""
    from sts2.models import RunHistory
    from sts2.routes import _get_imported_run, _imported_runs, _store_imported_run

    _imported_runs.clear()
    stored = _store_imported_run(RunHistory(id="local-1", character="Ironclad",
                                            win=False))
    assert stored != "local-1"
    assert _get_imported_run("local-1") is None
    assert _get_imported_run(stored) is not None
    _imported_runs.clear()
