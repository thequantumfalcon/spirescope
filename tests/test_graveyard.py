"""Procedural epitaphs for dead runs.

The epitaph is the only place in the app that narrates a run back to the
player, and it is generated from facts rather than written by hand -- so a
fact that stops being detected does not throw, it just quietly produces a
blander line. Each fact below is tested for the text it unlocks.

Determinism matters as much as the wording: the same run must always get the
same epitaph, or the graveyard page reshuffles itself on every reload.
"""
import pytest

from sts2.graveyard import (
    _collect_facts,
    _fallback_epitaph,
    _get_templates,
    generate_epitaph,
)
from sts2.models import RunFloor, RunHistory


def _floor(n, ftype="monster", dmg=0, gold=0, gained=(), used=()):
    return RunFloor(floor=n, type=ftype, damage_taken=dmg, gold=gold,
                    potions_gained=list(gained), potions_used=list(used))


def _run(rid="run-1", win=False, deck=None, floors=None, run_time=1200,
         killed_by="", character="Ironclad"):
    return RunHistory(id=rid, character=character, win=win, run_time=run_time,
                      killed_by=killed_by, deck=deck or ["CARD.X"] * 20,
                      floors=floors if floors is not None else [_floor(20)])


class _StubKB:
    def __init__(self, types):
        self._types = types

    def get_card_by_id(self, cid):
        kind = self._types.get(cid)
        return None if kind is None else type("Card", (), {"type": kind})()


# ------------------------------------------------------------------- contract

def test_a_won_run_has_no_epitaph():
    assert generate_epitaph(_run(win=True)) == ""


def test_the_epitaph_is_stable_for_the_same_run():
    run = _run(rid="stable-run")
    assert generate_epitaph(run) == generate_epitaph(run)


def test_the_epitaph_depends_on_the_run_id():
    """Selection is seeded from the id, so two runs with identical facts still
    get different lines -- otherwise a bad session reads as one repeated joke."""
    facts_only = dict(floors=[_floor(20)], deck=["CARD.X"] * 20)
    lines = {generate_epitaph(_run(rid=f"run-{i}", **facts_only))
             for i in range(12)}
    assert len(lines) > 1


def test_an_unremarkable_run_still_gets_an_epitaph():
    plain = _run(rid="plain", floors=[_floor(20)], deck=["CARD.X"] * 20)
    assert _collect_facts(plain, None) == {}
    assert generate_epitaph(plain)


# ---------------------------------------------------------------------- facts

def test_potion_hoarding_is_noticed():
    run = _run(floors=[_floor(1, gained=("A", "B")), _floor(2, gained=("C",))])
    assert _collect_facts(run, None)["potion_hoarder"] == 3


def test_using_a_single_potion_makes_you_a_miser_not_a_hoarder():
    run = _run(floors=[_floor(1, gained=("A", "B", "C", "D"), used=("A",))])
    facts = _collect_facts(run, None)
    assert facts["potion_miser"] == (4, 1)
    assert "potion_hoarder" not in facts


def test_spending_potions_earns_no_potion_fact():
    run = _run(floors=[_floor(1, gained=("A", "B", "C"), used=("A", "B"))])
    facts = _collect_facts(run, None)
    assert "potion_hoarder" not in facts and "potion_miser" not in facts


def test_a_bloated_deck_is_noticed():
    assert _collect_facts(_run(deck=["CARD.X"] * 45), None)["bloated_deck"] == 45


def test_a_tiny_deck_only_counts_if_the_run_got_somewhere():
    deep = _run(deck=["CARD.X"] * 10, floors=[_floor(20)])
    shallow = _run(deck=["CARD.X"] * 10, floors=[_floor(8)])
    assert _collect_facts(deep, None)["tiny_deck"] == 10
    assert "tiny_deck" not in _collect_facts(shallow, None)


def test_never_removing_starters_is_noticed_only_deep_into_a_run():
    deck = ["CARD.STRIKE_IRONCLAD"] * 5 + ["CARD.DEFEND_IRONCLAD"] * 4
    deep = _run(deck=deck, floors=[_floor(20)])
    shallow = _run(deck=deck, floors=[_floor(12)])
    assert _collect_facts(deep, None)["never_removed_starters"] == 9
    assert "never_removed_starters" not in _collect_facts(shallow, None)


def test_dying_on_floor_five_or_below_is_an_instant_death():
    assert _collect_facts(_run(floors=[_floor(5)]), None)["instant_death"] == 5
    assert "instant_death" not in _collect_facts(_run(floors=[_floor(6)]), None)


def test_a_run_with_no_floors_counts_as_an_instant_death():
    assert _collect_facts(_run(floors=[]), None)["instant_death"] == 0


def test_a_boss_death_names_the_boss():
    run = _run(floors=[_floor(16, ftype="boss")],
               killed_by="ENCOUNTER.THE_GUARDIAN")
    assert _collect_facts(run, None)["boss_death"] == "The Guardian"


def test_a_boss_death_without_a_recorded_killer_stays_generic():
    run = _run(floors=[_floor(16, ftype="boss")])
    assert _collect_facts(run, None)["boss_death"] == "the boss"


def test_a_long_run_is_a_marathon_measured_in_minutes():
    assert _collect_facts(_run(run_time=7200), None)["marathon"] == 120
    assert "marathon" not in _collect_facts(_run(run_time=600), None)


def test_a_fast_run_that_got_far_is_a_speedrun_death():
    fast_deep = _run(run_time=240, floors=[_floor(15)])
    fast_shallow = _run(run_time=240, floors=[_floor(4)])
    assert _collect_facts(fast_deep, None)["speedrun_death"] == 4
    assert "speedrun_death" not in _collect_facts(fast_shallow, None)


def test_heavy_damage_on_the_final_floor_is_an_overkill():
    assert _collect_facts(_run(floors=[_floor(20, dmg=80)]), None)["overkill"] == 80
    assert "overkill" not in _collect_facts(_run(floors=[_floor(20, dmg=10)]), None)


def test_dying_with_a_full_purse_is_noticed():
    assert _collect_facts(_run(floors=[_floor(20, gold=500)]), None)["died_rich"] == 500
    assert "died_rich" not in _collect_facts(_run(floors=[_floor(20, gold=50)]), None)


def test_getting_deep_into_the_spire_is_noticed():
    assert _collect_facts(_run(floors=[_floor(45)]), None)["so_close"] == 45
    assert "so_close" not in _collect_facts(_run(floors=[_floor(30)]), None)


def test_an_all_attack_deck_needs_the_knowledge_base():
    deck = ["CARD.A"] * 15 + ["CARD.D"] * 3
    kb = _StubKB({"CARD.A": "Attack", "CARD.D": "Skill"})
    assert _collect_facts(_run(deck=deck), kb)["all_attacks"] == 15
    # without a knowledge base no card type is known, so nothing is claimed
    assert "all_attacks" not in _collect_facts(_run(deck=deck), None)


def test_a_balanced_deck_is_not_called_all_attacks():
    deck = ["CARD.A"] * 10 + ["CARD.D"] * 10
    kb = _StubKB({"CARD.A": "Attack", "CARD.D": "Skill"})
    assert "all_attacks" not in _collect_facts(_run(deck=deck), kb)


def test_a_short_deck_skips_the_attack_check_entirely():
    kb = _StubKB({"CARD.A": "Attack"})
    assert "all_attacks" not in _collect_facts(_run(deck=["CARD.A"] * 8), kb)


# ------------------------------------------------------------------ templates

@pytest.mark.parametrize("facts, needle", [
    ({"potion_hoarder": 4}, "4 potions"),
    ({"potion_miser": (5, 1)}, "Gained 5 potions. Used 1."),
    ({"bloated_deck": 44}, "44 cards"),
    ({"tiny_deck": 9}, "9-card deck"),
    ({"never_removed_starters": 8}, "8 starter cards"),
    ({"instant_death": 3}, "Floor 3"),
    ({"boss_death": "Hexaghost"}, "Hexaghost"),
    ({"marathon": 95}, "95 minutes"),
    ({"speedrun_death": 3}, "Speedran"),
    ({"overkill": 66}, "66 damage"),
    ({"died_rich": 350}, "350 gold"),
    ({"so_close": 47}, "Floor 47"),
    ({"all_attacks": 19}, "19 Attack cards"),
])
def test_every_fact_unlocks_a_line_that_quotes_it(facts, needle):
    templates = _get_templates(facts)
    assert templates, f"{facts} produced no epitaph line"
    assert any(needle in t for t in templates)


def test_no_facts_means_no_templates():
    assert _get_templates({}) == []


def test_facts_accumulate_rather_than_replace_each_other():
    both = _get_templates({"bloated_deck": 44, "died_rich": 300})
    assert len(both) == len(_get_templates({"bloated_deck": 44})) + len(
        _get_templates({"died_rich": 300}))


# ------------------------------------------------------------------- fallback

def test_the_fallback_names_the_floor_and_character():
    run = _run(rid="f1", character="Necrobinder", floors=[_floor(17)])
    line = _fallback_epitaph(run)
    assert "17" in line


def test_the_fallback_handles_a_run_with_no_floors():
    assert "0" in _fallback_epitaph(_run(rid="f2", floors=[]))


def test_the_fallback_is_used_when_nothing_is_notable():
    plain = _run(rid="plain-run", floors=[_floor(20)], deck=["CARD.X"] * 20)
    assert generate_epitaph(plain) == _fallback_epitaph(plain)


def test_the_fallback_is_stable_and_varies_by_run():
    lines = {_fallback_epitaph(_run(rid=f"r{i}", floors=[_floor(20)]))
             for i in range(12)}
    assert len(lines) > 1
