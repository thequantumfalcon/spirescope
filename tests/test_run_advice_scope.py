"""Run-history analysis must describe recorded data, not grade it."""
from unittest.mock import AsyncMock, patch

import pytest

from sts2.analytics import analyze_run, analyze_run_patterns
from sts2.knowledge import KnowledgeBase
from sts2.models import RunFloor, RunHistory


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(game_version="v0.107.1")


def _run(**fields):
    base = dict(id="r", character="Ironclad", win=False, deck=[], relics=[], floors=[], run_time=600)
    base.update(fields)
    return RunHistory(**base)


def _texts(run, kb=None):
    return [i["text"] for i in analyze_run(run, kb=kb)["insights"]]


@pytest.mark.parametrize("deck_size,relics", [(6, 0), (20, 1), (35, 9)])
def test_deck_and_relic_counts_are_not_graded(deck_size, relics):
    floors = [RunFloor(floor=n, type="monster") for n in range(1, 25)]
    texts = _texts(_run(deck=["CARD.STRIKE_IRONCLAD"] * deck_size,
                        relics=["RELIC.X"] * relics, floors=floors))
    assert not any(word in t for t in texts
                   for word in ("Bloated", "thin deck", "Healthy deck", "relic game", "more elites"))


def test_win_with_unrecorded_time_is_not_a_speed_run():
    texts = _texts(_run(win=True, run_time=0))
    assert "Victory; run time not recorded." in texts
    assert not any("Speed run" in t or "0 minutes" in t for t in texts)


def test_win_time_is_reported_as_recorded():
    assert "Victory after 23 min 15 s." in _texts(_run(win=True, run_time=1395))


def test_death_floor_comes_from_the_recorded_floor_number():
    # Two recorded floors: len(floors) is 2, the death floor is 17.
    floors = [RunFloor(floor=5, type="monster"), RunFloor(floor=17, type="boss", damage_taken=40)]
    texts = _texts(_run(killed_by="Guardian", floors=floors))
    assert "Killed by Guardian on floor 17." in texts
    assert not any("floor 2" in t for t in texts)


def test_death_without_floor_numbers_names_no_floor():
    floors = [RunFloor(type="monster"), RunFloor(type="monster")]
    assert "Killed by Guardian." in _texts(_run(killed_by="Guardian", floors=floors))


def test_event_damage_is_not_counted_as_combat_damage():
    floors = [RunFloor(floor=1, type="monster", damage_taken=10, encounter="Cultist"),
              RunFloor(floor=2, type="event", damage_taken=25)]
    texts = _texts(_run(floors=floors))
    assert "10 damage taken across 1 combat, plus 25 on non-combat floors." in texts
    assert "Largest single-combat damage: 10 on floor 1 (Cultist)." in texts
    assert not any("35" in t for t in texts)


def test_skipped_picks_are_a_count_not_a_verdict():
    texts = _texts(_run(floors=[RunFloor(floor=1, type="monster"), RunFloor(floor=2, type="monster")]))
    assert "No card picks recorded across 2 floors." in texts
    assert not any("weakens" in t for t in texts)


def test_unrecorded_game_version_skips_card_text_checks(kb):
    texts = _texts(_run(deck=["CARD.STRIKE_IRONCLAD"] * 5, build_id=""), kb)
    assert "Game version not recorded for this run; card text was not checked." in texts
    assert not any("Block generation" in t for t in texts)


def test_unreviewed_game_version_does_not_borrow_installed_card_text(kb):
    texts = _texts(_run(deck=["CARD.STRIKE_IRONCLAD"] * 5, build_id="v0.99.0"), kb)
    assert "Card text is not verified for game version v0.99.0; effect checks were skipped." in texts
    assert not any("No Block generation detected" in t for t in texts)


def test_death_patterns_use_recorded_acts_only():
    def loss(i, act):
        return _run(id=f"r{i}", floors=[RunFloor(floor=20, type="boss", act=act)])

    # Floor 20 would be estimated as Act 2, but nothing was recorded.
    assert analyze_run_patterns([loss(i, 0) for i in range(5)]) == []
    patterns = analyze_run_patterns([loss(i, 2) for i in range(3)] + [loss(i, 0) for i in range(3, 5)])
    assert [p["text"] for p in patterns] == [
        "Died in Act 2 in 3 of your last 5 runs. 2 losses have no recorded act and are not counted."]
    assert patterns[0]["severity"] == "info"
    assert not any("strategy" in p["text"] for p in patterns)


def test_block_pattern_excludes_runs_it_cannot_check(kb):
    checked = [_run(id=f"c{i}", deck=["CARD.STRIKE_IRONCLAD"] * 5, build_id="v0.107.1") for i in range(3)]
    unchecked = [_run(id="u1", deck=["CARD.STRIKE_IRONCLAD"] * 5, build_id=""),
                 _run(id="u2", deck=["CARD.STRIKE_IRONCLAD"] * 5, build_id="v0.99.0")]
    patterns = analyze_run_patterns(checked + unchecked, kb=kb)
    assert [p["text"] for p in patterns] == [
        "No Block generation detected in the final deck's card text in 3 of your last 5 runs. "
        "2 runs could not be checked for their recorded game version."]


@pytest.mark.asyncio
async def test_run_page_renders_information_without_loss_styling(client, kb):
    run = _run(id="obs", win=True, run_time=0, deck=["CARD.DEFEND_IRONCLAD"], build_id="")
    with patch("sts2.app.kb", kb), \
         patch("sts2.app._get_run_by_id", new_callable=AsyncMock, return_value=run):
        response = await client.get("/runs/obs")
    assert response.status_code == 200
    assert ('<div class="card  mb-sm">\n  <p>Game version not recorded for this run; '
            'card text was not checked.</p>') in response.text
    assert '<div class="card card-win mb-sm">\n  <p>Victory; run time not recorded.</p>' in response.text
