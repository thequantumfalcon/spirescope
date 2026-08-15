"""Route paths the existing suite never drove: form guards, admin actions,
one-click install, and the advanced-analytics fallbacks on a run page.

Every handler below either mutates state or degrades to a fallback when an
optional analysis module misbehaves. The fallbacks are the interesting half:
they exist so one broken analytic cannot 500 a whole run page, which also
means a regression in them is invisible until someone opens the page.
"""
from unittest.mock import patch

import pytest

from sts2.app import generate_csrf_token


def _form(**extra):
    return {"csrf_token": generate_csrf_token(), **extra}


# ------------------------------------------------------------- deck analysis

async def test_deck_analysis_rejects_a_bad_csrf_token(client):
    resp = await client.post("/deck/analyze", data={"csrf_token": "forged"})
    assert resp.status_code == 403
    assert "Invalid form submission" in resp.text


async def test_deck_analysis_with_no_cards_selected_says_so(client):
    resp = await client.post("/deck/analyze", data=_form())
    assert resp.status_code == 200
    assert "No cards selected" in resp.text


async def test_deck_analysis_returns_an_analysis_for_a_real_deck(client):
    resp = await client.post("/deck/analyze", data=_form(
        card_ids=["CARD.BASH", "CARD.STRIKE_IRONCLAD", "CARD.STRIKE_IRONCLAD"]))
    assert resp.status_code == 200
    assert "Bash" in resp.text


async def test_deck_analysis_survives_a_broken_spectral_analysis(client):
    """Deck health is one panel; if it throws, the rest of the analysis must
    still render rather than 500 the page."""
    with patch("sts2.spectral.deck_spectral_health",
               side_effect=RuntimeError("eigenvalue solver blew up")):
        resp = await client.post("/deck/analyze",
                                 data=_form(card_ids=["CARD.BASH"]))
    assert resp.status_code == 200
    assert "Bash" in resp.text


async def test_deck_analysis_caps_the_number_of_cards_accepted(client):
    """An unbounded card list is a cheap way to make the server do a lot of
    graph work; the handler truncates instead."""
    resp = await client.post("/deck/analyze",
                             data=_form(card_ids=["CARD.BASH"] * 3000))
    assert resp.status_code == 200


# ------------------------------------------------------------ patch admin

async def test_admin_patches_page_lists_unmapped_builds(client):
    """unmapped_builds returns dicts of {build_id, count}; the page has to show
    both or there is no way to tell a one-run stray from a whole era."""
    with patch("sts2.patches.unmapped_builds",
               return_value=[{"build_id": "v9.9.9-unknown", "count": 7}]):
        resp = await client.get("/admin/patches")
    assert resp.status_code == 200
    assert "v9.9.9-unknown" in resp.text
    assert ">7<" in resp.text


async def test_assigning_a_build_rejects_a_bad_csrf_token(client):
    resp = await client.post("/admin/patches/assign",
                             data={"build_id": "v1", "patch": "1.0",
                                   "csrf_token": "forged"})
    assert resp.status_code == 403


async def test_assigning_an_unknown_patch_is_a_400(client):
    with patch("sts2.patches.assign_build", return_value=False):
        resp = await client.post("/admin/patches/assign",
                                 data=_form(build_id="v1", patch="nope"))
    assert resp.status_code == 400
    assert "Unknown patch" in resp.text


async def test_assigning_a_build_redirects_back_with_a_flag(client):
    with patch("sts2.patches.assign_build", return_value=True) as assign:
        resp = await client.post("/admin/patches/assign",
                                 data=_form(build_id="  v1  ", patch="  1.0  "),
                                 follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/patches?assigned=1"
    # whitespace from the form must not become part of the stored id
    assign.assert_called_once_with("v1", "1.0")


# ------------------------------------------------------- one-click data install

async def test_data_update_install_rejects_a_bad_csrf_token(client):
    resp = await client.post("/data-update/install",
                             data={"csrf_token": "forged"})
    assert resp.status_code == 403


async def test_a_failed_data_install_reports_the_reason(client):
    """The installer returns (ok, message); the message is the only thing that
    tells the user whether it was a checksum failure or a disk problem."""
    with patch("sts2.updater.install_data_update",
               return_value=(False, "Bundle checksum did not match.")):
        resp = await client.post("/data-update/install", data=_form())
    assert resp.status_code == 500
    assert "checksum did not match" in resp.text


async def test_a_successful_data_install_reloads_and_redirects(client):
    from unittest.mock import AsyncMock

    from sts2 import app as app_module
    with patch("sts2.updater.install_data_update", return_value=(True, "ok")), \
         patch.object(app_module, "_refresh_data", new=AsyncMock()) as refresh:
        resp = await client.post("/data-update/install", data=_form(),
                                 follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/?data_updated=1"
    refresh.assert_awaited_once()


# ------------------------------------- run page: optional analytics fallbacks

@pytest.fixture
def one_lost_run():
    """A single finished loss, which is what unlocks the autopsy path."""
    from sts2.models import RunFloor, RunHistory
    return [RunHistory(
        id="fallback-run", character="Ironclad", win=False, ascension=3,
        run_time=900, deck=["CARD.BASH", "CARD.STRIKE_IRONCLAD"],
        relics=["RELIC.BURNING_BLOOD"], timestamp=1_700_000_000,
        floors=[RunFloor(floor=i, type="monster", damage_taken=5,
                         current_hp=40, max_hp=80, gold=50)
                for i in range(1, 9)])]


async def _run_page(client, runs):
    """The handler resolves the run through _get_run_by_id, then reads the
    full history separately for the comparison sets."""
    from unittest.mock import AsyncMock

    from sts2 import app as app_module
    with patch.object(app_module, "_get_run_by_id",
                      new=AsyncMock(return_value=runs[0])), \
         patch.object(app_module, "_get_runs", new=AsyncMock(return_value=runs)):
        return await client.get(f"/runs/{runs[0].id}")


async def test_a_run_page_renders_without_the_private_autopsy_module(
        client, one_lost_run):
    """sts2.diagnosis is not shipped in the public build, so the import fails
    on every clean checkout. That is the expected path, not an error."""
    import sys
    with patch.dict(sys.modules, {"sts2.diagnosis": None}):
        resp = await _run_page(client, one_lost_run)
    assert resp.status_code == 200


async def test_a_broken_autopsy_leaves_a_trace_instead_of_failing_silently(
        client, one_lost_run, caplog):
    """Swallowing this made a regression indistinguishable from the feature
    simply being absent."""
    import logging
    caplog.set_level(logging.WARNING)
    with patch("sts2.diagnosis.diagnose_run",
               side_effect=RuntimeError("model exploded"), create=True):
        resp = await _run_page(client, one_lost_run)
    assert resp.status_code == 200
    assert "Autopsy generation failed" in caplog.text


async def test_a_broken_cascade_trace_does_not_take_the_page_down(
        client, one_lost_run):
    with patch("sts2.cascade.trace_all_picks",
               side_effect=RuntimeError("bad window")):
        resp = await _run_page(client, one_lost_run)
    assert resp.status_code == 200


async def test_a_broken_drift_computation_does_not_take_the_page_down(
        client, one_lost_run):
    with patch("sts2.drift.compute_archetype_drift",
               side_effect=RuntimeError("classifier failed")):
        resp = await _run_page(client, one_lost_run)
    assert resp.status_code == 200


async def test_the_run_page_carries_a_tamper_evident_digest(
        client, one_lost_run):
    """The digest is a checksum over the run's canonical record: the same run
    must always produce the same one, or export/import verification is noise."""
    from sts2.integrity import compute_run_digest
    digest = compute_run_digest(one_lost_run[0])
    resp = await _run_page(client, one_lost_run)
    assert resp.status_code == 200
    assert digest[:16] in resp.text
