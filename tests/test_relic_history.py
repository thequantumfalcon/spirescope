"""Relic acquisition floors survive parsing, export, and run-history views."""
import json
from unittest.mock import AsyncMock, Mock, patch

import pytest

from sts2.drift import compute_archetype_drift
from sts2.models import RunFloor, RunHistory
from sts2.saves import get_current_run, get_run_history


@pytest.fixture
def relic_save():
    return {
        "players": [{
            "id": 1, "character": "CHARACTER.IRONCLAD",
            "deck": [{"id": "CARD.STRIKE"}] * 5,
            "relics": [{"id": "RELIC.BURNING_BLOOD"}, {"id": "RELIC.POTION_BELT"}],
        }],
        "map_point_history": [[{
            "map_point_type": "shop",
            "player_stats": [{
                "player_id": 2,
                "relic_choices": [{"choice": "RELIC.ANCHOR", "was_picked": True}],
            }, {
                "player_id": 1, "current_hp": 70, "max_hp": 80,
                "relic_choices": [
                    {"choice": "RELIC.MEAL_TICKET", "was_picked": True},
                    {"choice": "RELIC.POTION_BELT", "was_picked": True},
                    {"choice": "RELIC.ANCHOR", "was_picked": False},
                    {"choice": "", "was_picked": True},
                ],
                "bought_relics": ["RELIC.POTION_BELT", "RELIC.BAG_OF_PREPARATION", ""],
                "relics_removed": ["RELIC.MEAL_TICKET", ""],
            }],
        }, {
            "map_point_type": "monster",
            "player_stats": [{"player_id": 1, "current_hp": 65, "max_hp": 80}],
        }]],
    }


@pytest.mark.parametrize("live", [False, True])
def test_parser_preserves_relic_events_for_the_selected_player(tmp_path, relic_save, live):
    if live:
        (tmp_path / "current_run.save").write_text(json.dumps(relic_save), encoding="utf-8")
    else:
        (tmp_path / "history").mkdir()
        (tmp_path / "history" / "123.run").write_text(json.dumps(relic_save), encoding="utf-8")
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        run = get_current_run() if live else get_run_history()[0]
    assert run.floors[0].relics_gained == [
        "RELIC.MEAL_TICKET", "RELIC.POTION_BELT", "RELIC.BAG_OF_PREPARATION",
    ]
    assert run.floors[0].relics_removed == ["RELIC.MEAL_TICKET"]
    assert run.floors[1].relics_gained == []
    assert run.floors[1].relics_removed == []


def test_old_exports_do_not_invent_relic_floors():
    run = RunHistory(id="old", character="Ironclad", win=True,
                     relics=["RELIC.ANCHOR"], floors=[RunFloor(floor=1)])
    assert run.floors[0].relics_gained == []


def _run():
    return RunHistory(
        id="relic-history", character="Ironclad", win=True,
        deck=["CARD.STRIKE"] * 5 + ["CARD.BASH", "CARD.ANGER"],
        relics=["RELIC.POTION_BELT"],
        floors=[RunFloor(
            floor=1, type="shop", current_hp=70, max_hp=80,
            cards_picked=["CARD.BASH", "CARD.ANGER"],
            relics_gained=["RELIC.MEAL_TICKET", "RELIC.POTION_BELT"],
            relics_removed=["RELIC.MEAL_TICKET"],
        ), RunFloor(floor=2, current_hp=65, max_hp=80)],
    )


def test_drift_records_all_picks_and_relic_changes_without_changing_classification():
    kb = Mock()
    kb.classify_archetype.return_value = {"name": "Custom", "confidence": 0}
    trajectory = compute_archetype_drift(_run(), kb)
    assert trajectory[0]["cards_added"] == ["CARD.BASH", "CARD.ANGER"]
    assert trajectory[0]["card_added"] == "CARD.ANGER"
    assert trajectory[0]["deck_size"] == 7
    assert trajectory[0]["relics_gained"] == ["RELIC.MEAL_TICKET", "RELIC.POTION_BELT"]
    assert trajectory[0]["relics_removed"] == ["RELIC.MEAL_TICKET"]
    assert trajectory[1]["relics_gained"] == []
    kb.classify_archetype.assert_called_with(_run().deck, "Ironclad")


async def test_relic_events_render_in_all_history_views_and_exports(client):
    import sts2.app

    run = _run()
    names = [sts2.app.kb.id_to_name(r) for r in run.floors[0].relics_gained]
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
        page = await client.get(f"/runs/{run.id}")
        exported = await client.get(f"/runs/{run.id}/export")
        html_export = await client.get(f"/runs/{run.id}/export/html")
    assert page.status_code == exported.status_code == html_export.status_code == 200
    timeline = page.text.split("<h2>Run Timeline</h2>")[1].split("<h2>Floor by Floor</h2>")[0]
    floors = page.text.split("<h2>Floor by Floor</h2>")[1].split("Archetype Drift")[0]
    drift = page.text.split("Archetype Drift")[1].split("</table>")[0]
    assert 'class="timeline-marker timeline-relic"' in timeline
    for name in names:
        assert f"obtained relic {name}" in timeline
        assert f"Relic obtained: {name}" in floors
        assert name in drift
        assert f"Relic obtained: {name}" in html_export.text
    assert f"Relic removed: {names[0]}" in floors
    assert "Relics Obtained" in drift
    assert "Relics Removed" in drift
    payload = exported.json()["run"]
    assert payload["floors"][0]["relics_gained"] == run.floors[0].relics_gained
    assert RunHistory(**payload) == run
    imported = await client.post(
        "/runs/import",
        files={"file": ("run.json", exported.content, "application/json")},
        data={"csrf_token": sts2.app.generate_csrf_token()},
    )
    assert imported.status_code == 200
    assert "matches the checksum" in imported.text
    assert f"Relic obtained: {names[0]}" in imported.text


@pytest.mark.parametrize("field", ["relics_gained", "relics_removed"])
async def test_import_bounds_relic_event_lists(client, field):
    from sts2.app import generate_csrf_token

    payload = {"format_version": 1, "run": _run().model_dump()}
    payload["run"]["floors"][0][field] = ["RELIC.ANCHOR"] * 101
    response = await client.post(
        "/runs/import",
        files={"file": ("run.json", json.dumps(payload).encode(), "application/json")},
        data={"csrf_token": generate_csrf_token()},
    )
    assert response.status_code == 400
    assert "unreasonable per-floor list sizes" in response.text
