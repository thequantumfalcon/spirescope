"""Cards gained outside a reward screen still appear in floor history."""
import json
from unittest.mock import AsyncMock, patch

import pytest

from sts2.aggregate import compute_aggregate_stats
from sts2.analytics import compute_analytics
from sts2.models import RunFloor, RunHistory
from sts2.saves import get_current_run, get_run_history


@pytest.fixture
def card_save():
    return {
        "players": [{
            "id": 1, "character": "CHARACTER.SILENT",
            "deck": [{"id": "CARD.STRIKE_SILENT"}] * 5 + [
                {"id": "CARD.THRUMMING_HATCHET"}, {"id": "CARD.BLUR"},
                {"id": "CARD.BLUR"}, {"id": "CARD.ETERNAL_ARMOR"},
            ],
        }],
        "map_point_history": [[{
            "map_point_type": "ancient",
            "player_stats": [{
                "player_id": 1,
                "cards_gained": [{"id": "CARD.THRUMMING_HATCHET", "floor_added_to_deck": 1}],
            }],
        }, {
            "map_point_type": "monster",
            "player_stats": [{
                "player_id": 1,
                "card_choices": [
                    {"card": {"id": "CARD.BLUR"}, "was_picked": True},
                    {"card": {"id": "CARD.BLUR"}, "was_picked": True},
                    {"card": {"id": "CARD.RICOCHET"}, "was_picked": False},
                ],
                # The game repeats reward picks here; they must not double up.
                "cards_gained": [{"id": "CARD.BLUR"}, {"id": "CARD.BLUR"}, {}],
            }],
        }, {
            "map_point_type": "shop",
            "player_stats": [{
                "player_id": 1,
                "bought_colorless": ["CARD.ETERNAL_ARMOR"],
                "cards_gained": [{"id": "CARD.ETERNAL_ARMOR"}],
            }],
        }, {
            "map_point_type": "rest_site",
            "player_stats": [{
                "player_id": 1,
                "rest_site_choices": ["SMITH"],
                "upgraded_cards": ["CARD.ETERNAL_ARMOR", "", None],
            }],
        }]],
    }


@pytest.mark.parametrize("live", [False, True])
def test_parser_records_cards_gained_without_a_choice(tmp_path, card_save, live):
    if live:
        (tmp_path / "current_run.save").write_text(json.dumps(card_save), encoding="utf-8")
    else:
        (tmp_path / "history").mkdir()
        (tmp_path / "history" / "123.run").write_text(json.dumps(card_save), encoding="utf-8")
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        run = get_current_run() if live else get_run_history()[0]
    assert [f.cards_picked for f in run.floors] == [
        ["CARD.THRUMMING_HATCHET"], ["CARD.BLUR", "CARD.BLUR"], ["CARD.ETERNAL_ARMOR"], [],
    ]
    assert run.floors[2].card_picked == "CARD.ETERNAL_ARMOR"
    assert [f.cards_upgraded for f in run.floors] == [[], [], [], ["CARD.ETERNAL_ARMOR"]]


def test_old_exports_have_no_upgrades():
    assert RunFloor(floor=1).cards_upgraded == []


async def test_upgrades_render_in_run_views_and_exports(client):
    import sts2.app

    run = RunHistory(
        id="upgrade-history", character="Silent", win=True,
        deck=["CARD.ETERNAL_ARMOR"],
        floors=[RunFloor(floor=1, type="rest_site", current_hp=50, max_hp=70,
                         cards_upgraded=["CARD.ETERNAL_ARMOR"])],
    )
    name = sts2.app.kb.id_to_name("CARD.ETERNAL_ARMOR")
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
        page = await client.get(f"/runs/{run.id}")
        exported = await client.get(f"/runs/{run.id}/export")
        html_export = await client.get(f"/runs/{run.id}/export/html")
    assert page.status_code == exported.status_code == html_export.status_code == 200
    timeline = page.text.split("<h2>Run Timeline</h2>")[1].split("<h2>Floor by Floor</h2>")[0]
    floors = page.text.split("<h2>Floor by Floor</h2>")[1]
    assert f"upgraded {name}" in timeline
    assert f"Upgraded: {name}" in floors
    assert f"Upgraded: {name}" in html_export.text
    payload = exported.json()["run"]
    assert payload["floors"][0]["cards_upgraded"] == ["CARD.ETERNAL_ARMOR"]
    assert RunHistory(**payload) == run


async def test_import_bounds_upgrade_lists(client):
    from sts2.app import generate_csrf_token

    run = RunHistory(id="u", character="Silent", win=True,
                     floors=[RunFloor(floor=1, cards_upgraded=["CARD.BLUR"] * 101)])
    response = await client.post(
        "/runs/import",
        files={"file": ("run.json", json.dumps({"format_version": 1, "run": run.model_dump()}).encode(),
                        "application/json")},
        data={"csrf_token": generate_csrf_token()},
    )
    assert response.status_code == 400
    assert "unreasonable per-floor list sizes" in response.text


def _run(i):
    return RunHistory(
        id=f"r{i}", character="Silent", win=bool(i % 2),
        deck=["CARD.BLUR", "CARD.ETERNAL_ARMOR"],
        floors=[
            RunFloor(floor=1, type="monster",
                     cards_offered=["CARD.BLUR", "CARD.RICOCHET"],
                     cards_picked=["CARD.BLUR", "CARD.RICOCHET", "CARD.ETERNAL_ARMOR"]),
            RunFloor(floor=2, type="shop", cards_picked=["CARD.RICOCHET"]),
        ],
    )


def test_pick_rates_ignore_cards_that_were_not_offered():
    runs = [_run(i) for i in range(3)]
    rates = {r["id"]: r for r in compute_analytics(runs)["card_pick_rates"]}
    assert rates["CARD.RICOCHET"]["picked"] == 3
    assert rates["CARD.RICOCHET"]["pick_rate"] == 100.0
    assert "CARD.ETERNAL_ARMOR" not in rates

    agg = compute_aggregate_stats(runs)["card_pick_rates"]
    assert agg["CARD.RICOCHET"] == {"picked": 3, "offered": 3}
    assert "CARD.ETERNAL_ARMOR" not in agg
