"""Deck analysis reads mechanics, upgrades and canonical text (audit F09-F11).

F09: display keywords are mentions, not capabilities. Body Slam and Barricade
carry the Block keyword without granting Block; Havoc's Draw keyword comes
from "Draw Pile". The spectral score measures keyword connectivity, and the
deck page must say so rather than present it as deck strength.
F10: upgraded instances in a live deck use their upgraded cost.
F11: a content overlay changes displayed text only; analysis is identical.
"""
from unittest.mock import AsyncMock, patch

import pytest

from sts2.app import generate_csrf_token
from sts2.knowledge import KnowledgeBase, draws_cards, grants_block, hits_all_enemies
from sts2.models import Card, CurrentRun


@pytest.fixture(scope="module")
def kb():
    return KnowledgeBase(language="en")


def _weak(kb, ids, upgrades=None):
    return kb.analyze_deck(ids, upgrades)["weaknesses"]


def _has(weaknesses, prefix):
    return any(w.startswith(prefix) for w in weaknesses)


# ---------------------------------------------------------------------------
# F09: mechanics from text, not keywords
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "Gain 5 Block.",
    "Lose 2 HP. Gain 16 Block.",
    "Deal 7 damage. Gain Block equal to damage dealt.",
    "ALL players gain 12 Block.",
    "Whenever a card is Exhausted, gain 3 Block.",
    "If Osty is alive, he deals 9 damage to ALL enemies and you gain 9 Block. Osty dies.",
    "Gain X Block.",
])
def test_block_generation_phrasings(text):
    assert grants_block(text)


@pytest.mark.parametrize("text", [
    "Deal damage equal to your Block.",                     # Body Slam
    "Block is not removed at the start of your turn.",      # Barricade
    "Whenever you gain Block, deal 5 damage to a random enemy.",
    "Whenever you gain Block this turn, deal 5 damage to the enemy.",
    "Double your Block.",
    "Gain an additional 4 Block from Defend cards.",
    "The first time you gain Block from a card each turn, double the amount gained.",
    "Give another player 11 Block.",
    "Remove all Artifact and Block from the enemy. Apply 2 Vulnerable. Exhaust.",
    "",
])
def test_block_non_generation_phrasings(text):
    assert not grants_block(text)


@pytest.mark.parametrize("text", [
    "Draw 2 cards.",
    "Deal 9 damage. Draw 1 card.",
    "At the start of your turn, draw 1 additional card.",
    "Draw cards until your Hand is full. Exhaust.",
    "Discard your Hand, then draw that many cards. Exhaust.",
    "ALL allies draw 2 cards. Exhaust.",
    "Put a Skill from your Draw Pile into your Hand. Exhaust.",
    "Deal 9 damage. Choose 1 of 3 cards in your Draw Pile to add into your Hand.",
])
def test_draw_phrasings(text):
    assert draws_cards(text)


@pytest.mark.parametrize("text", [
    "Play the top card of your Draw Pile and Exhaust it.",   # Havoc
    "Draw 1 fewer card each turn.",                          # Mind Rot
    "You cannot draw additional cards this turn.",
    "Whenever you draw this card, lose 1 Energy.",
    "Whenever you draw a card during your turn, deal 2 damage to ALL enemies.",
    "Another player draws 1 card, gains 1 Energy, and gains 9 Block.",
    "Deal 8 damage. Deals 4 additional damage for each card drawn during your turn.",
    "",
])
def test_draw_non_draw_phrasings(text):
    assert not draws_cards(text)


def test_body_slam_alone_is_not_a_block_generator(kb):
    assert "Block" in kb.get_card_by_id("CARD.BODY_SLAM").keywords
    assert _has(_weak(kb, ["CARD.BODY_SLAM"]), "No Block generation")


def test_barricade_alone_is_not_a_block_generator(kb):
    assert "Block" in kb.get_card_by_id("CARD.BARRICADE").keywords
    assert _has(_weak(kb, ["CARD.BARRICADE"]), "No Block generation")


def test_real_block_card_suppresses_the_warning(kb):
    assert not _has(_weak(kb, ["CARD.BODY_SLAM", "CARD.DEFEND_IRONCLAD"]),
                    "No Block generation")


def test_draw_pile_reference_is_not_card_draw(kb):
    assert "Draw" in kb.get_card_by_id("CARD.HAVOC").keywords
    assert _has(_weak(kb, ["CARD.HAVOC"]), "No card draw")


def test_real_draw_card_suppresses_the_warning(kb):
    assert not _has(_weak(kb, ["CARD.HAVOC", "CARD.POMMEL_STRIKE"]), "No card draw")


def test_every_bundled_block_generator_is_detected(kb):
    """Every card whose text opens with 'Gain N Block' counts. Guards the
    pattern against the phrasings actually shipped."""
    openers = [c for c in kb.cards
               if c.description.lower().startswith("gain ")
               and " block" in c.description.lower().split(".")[0]
               and "additional" not in c.description.lower().split(".")[0]]
    assert len(openers) > 50
    missed = [c.id for c in openers if not grants_block(c.description)]
    assert missed == []


def test_balanced_strength_needs_real_block(kb):
    """Body Slam + Inflame: Block keyword and Strength keyword, but nothing
    grants Block, so the deck is not 'balanced'."""
    result = kb.analyze_deck(["CARD.BODY_SLAM", "CARD.INFLAME"])
    assert not any(s.startswith("Balanced offense") for s in result["strengths"])


def test_five_strikes_score_is_connectivity_not_strength(kb):
    """The number the page shows for 5x Strike is 100; the label must not
    present that as a strong deck."""
    from sts2.spectral import deck_spectral_health
    health = deck_spectral_health(["CARD.STRIKE_IRONCLAD"] * 5, kb)
    assert health["health_score"] == 100


async def test_deck_page_labels_score_as_connectivity(client):
    resp = await client.post("/deck/analyze", data={
        "csrf_token": generate_csrf_token(),
        "card_ids": ["CARD.STRIKE_IRONCLAD"] * 5,
    })
    assert resp.status_code == 200
    assert "Keyword connectivity, not deck strength" in resp.text
    assert "same type and cost within 1 Energy" in resp.text
    assert "Cards sharing keywords are connected; the more" not in resp.text


# ---------------------------------------------------------------------------
# F10: upgrades flow into the cost curve
# ---------------------------------------------------------------------------

def test_upgraded_barricade_uses_upgraded_cost(kb):
    assert kb.analyze_deck(["CARD.BARRICADE"])["cost_curve"] == {"3": 1}
    assert kb.analyze_deck(["CARD.BARRICADE"], [True])["cost_curve"] == {"2": 1}
    assert kb.analyze_deck(["CARD.BARRICADE"], [False])["cost_curve"] == {"3": 1}


def test_every_cost_changing_upgrade(kb):
    changing = [c for c in kb.cards if c.cost_upgraded and c.cost_upgraded != c.cost]
    assert len(changing) >= 50
    assert any(c.cost_upgraded == "0" for c in changing), "no upgrade makes a card free"
    for c in changing:
        base = kb.analyze_deck([c.id], [False])["cost_curve"]
        upg = kb.analyze_deck([c.id], [True])["cost_curve"]
        assert base == {c.cost: 1}, c.id
        assert upg == {c.cost_upgraded: 1}, c.id


def test_upgrades_are_per_instance(kb):
    result = kb.analyze_deck(["CARD.BARRICADE", "CARD.BARRICADE"], [True, False])
    assert result["cost_curve"] == {"2": 1, "3": 1}
    assert result["avg_cost"] == 2.5


def test_short_or_missing_upgrade_list_means_not_upgraded(kb):
    ids = ["CARD.BARRICADE", "CARD.BARRICADE"]
    assert kb.analyze_deck(ids, [True])["cost_curve"] == {"2": 1, "3": 1}
    assert kb.analyze_deck(ids, [])["cost_curve"] == {"3": 2}
    assert kb.analyze_deck(ids, None)["cost_curve"] == {"3": 2}


def test_upgrade_flags_stay_aligned_past_unknown_ids(kb):
    """Flags are parallel to the raw id list; an unknown id is dropped
    without shifting the next card's flag onto it."""
    result = kb.analyze_deck(["FAKE.NOPE", "CARD.BARRICADE"], [False, True])
    assert result["cost_curve"] == {"2": 1}


def test_non_numeric_costs_do_not_crash_the_curve():
    kb = KnowledgeBase(language="en")
    for cid, cost, upg in (("TEST.X", "X", ""), ("TEST.UNPLAY", "Unplayable", ""),
                           ("TEST.X_TO_1", "X", "1"), ("TEST.Q", "?", "")):
        card = Card(id=cid, name=cid, character="Ironclad", cost=cost,
                    cost_upgraded=upg, type="Skill", rarity="Common")
        kb.cards.append(card)
        kb._cards_by_id[cid] = card
    ids = ["TEST.X", "TEST.UNPLAY", "TEST.X_TO_1", "TEST.Q", "CARD.BARRICADE"]
    result = kb.analyze_deck(ids, [True, True, True, False, True])
    assert result["cost_curve"] == {"1": 1, "2": 1, "?": 1, "Unplayable": 1, "X": 1}
    assert result["avg_cost"] == 1.5


async def test_live_route_passes_upgrades(client):
    run = CurrentRun(active=True, character="Ironclad", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=2,
                     deck=["CARD.BARRICADE", "CARD.STRIKE_IRONCLAD"],
                     deck_upgrades=[True, False])
    from sts2.app import kb as app_kb
    real = app_kb.analyze_deck
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock, return_value=run), \
         patch.object(app_kb, "analyze_deck", side_effect=real) as spy:
        resp = await client.get("/live")
    assert resp.status_code == 200
    spy.assert_any_call(run.deck, run.deck_upgrades)


async def test_live_block_pick_hint_ignores_keyword_mentions(client):
    """Body Slam's Block keyword no longer hides the 'Any Block card' hint."""
    run = CurrentRun(active=True, character="Ironclad", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=2,
                     deck=["CARD.BODY_SLAM", "CARD.STRIKE_IRONCLAD", "CARD.BASH"])
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock, return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    assert "Any Block card" in resp.text


# ---------------------------------------------------------------------------
# F11: analysis ignores the display language
# ---------------------------------------------------------------------------

def _translated_kb():
    """A KnowledgeBase whose content overlay rewrites every card's text into
    stand-in 'translated' strings that contain none of the English phrases."""
    english = KnowledgeBase(language="en")
    overlay = {"cards": {
        c.id: {"name": f"Karte {i}",
               "description": f"Übersetzter Text {i}.",
               "description_upgraded": f"Übersetzter Text {i}+."}
        for i, c in enumerate(english.cards)
    }}
    with patch("sts2.i18n.load_content_overlay", return_value=overlay):
        return english, KnowledgeBase(language="de")


def test_overlay_changes_display_but_keeps_canonical_text():
    english, translated = _translated_kb()
    en_card = english.get_card_by_id("CARD.WHIRLWIND")
    de_card = translated.get_card_by_id("CARD.WHIRLWIND")
    assert de_card.description.startswith("Übersetzter Text")
    assert hits_all_enemies(en_card.description)
    assert translated.card_text_en(de_card) == en_card.description
    assert translated.card_text_en(de_card, upgraded=True) == (
        en_card.description_upgraded or en_card.description)


def test_analysis_is_identical_under_a_translated_overlay():
    english, translated = _translated_kb()
    aoe = [c.id for c in english.cards if hits_all_enemies(c.description)]
    assert len(aoe) >= 40
    decks = [
        aoe[:5],
        ["CARD.STRIKE_IRONCLAD"] * 5 + ["CARD.DEFEND_IRONCLAD"] * 4 + ["CARD.BASH"],
        ["CARD.BODY_SLAM", "CARD.HAVOC", "CARD.POMMEL_STRIKE", "CARD.SHRUG_IT_OFF"],
        ["CARD.BARRICADE", "CARD.ARMAMENTS"],
    ]
    for deck in decks:
        for ups in (None, [True] * len(deck)):
            en = english.analyze_deck(deck, ups)
            de = translated.analyze_deck(deck, ups)
            assert de["weaknesses"] == en["weaknesses"], deck
            assert de["strengths"] == en["strengths"], deck
            assert de["cost_curve"] == en["cost_curve"], deck


def test_every_aoe_card_survives_the_overlay():
    english, translated = _translated_kb()
    for c in english.cards:
        if hits_all_enemies(c.description):
            result = translated.analyze_deck([c.id])
            assert not _has(result["weaknesses"], "No AoE"), c.id


def test_uncovered_card_falls_back_to_its_own_text(kb):
    card = kb.get_card_by_id("CARD.DEFEND_IRONCLAD")
    assert kb.card_text_en(card) == card.description
    assert kb.card_text_en(card, upgraded=True) == (
        card.description_upgraded or card.description)
