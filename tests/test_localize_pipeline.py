"""The text pipeline behind `python -m sts2 localize`.

Everything here runs on fixture strings rather than an installed game. That
is deliberate: the alignment and rendering logic is pure text -> text, and
the only test that drove it before (test_localize_against_real_game) skips
wherever the game is absent -- which includes CI, so none of it was checked
there.

The failure this guards is silent for the person maintaining the app: English
descriptions never pass through this pipeline at all. A game patch reshapes a
template, alignment stops recovering the numbers, and every non-English player
gets half-rendered markup or a wrong number while the suite stays green.

Template shapes used below were taken from the shipped English card, relic and
potion descriptions of game build 0.107.1, so the fixtures exercise the forms
that actually occur (NUM and PLURAL dominate, then ENERGY, SHOW, STAR).
"""
import json

import pytest

from sts2 import localize

# ---------------------------------------------------------------- normalising

@pytest.mark.parametrize("raw, expected", [
    ("[gold]5[/gold] Gold", "5 Gold"),
    ("[color=red]Vulnerable[/color]", "Vulnerable"),
    ("no markup at all", "no markup at all"),
    # braces are NOT tags -- they are template syntax and must survive, which
    # is what lets render_text's residue check spot an unrendered token
    ("{Damage} damage", "{Damage} damage"),
])
def test_strip_tags_removes_colour_markup_but_never_template_braces(raw, expected):
    assert localize.strip_tags(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    ("  lots   of\n space  ", "lots of space"),
    ("", ""),
    ("\t\n", ""),
])
def test_norm_ws_collapses_all_whitespace(raw, expected):
    assert localize.norm_ws(raw) == expected


@pytest.mark.parametrize("raw, expected", [
    # the wiki bakes star costs as repeated icon markers
    ("@ST", "1 Star"),
    ("@ST@ST@ST", "3 Star"),
    ("Costs @ST@ST to play", "Costs 2 Star to play"),
    ("@Gold", "Gold"),
    # templates use the plural after a count, the wiki uses the singular tag
    ("play 3 type:Attack", "play 3 Attacks"),
    ("play 2 type:Skill", "play 2 Skills"),
    ("a type:Attack card", "a Attack card"),
    ("color:red text", "red text"),
    ("line<br>break", "line break"),
    ("line<br />break", "line break"),
])
def test_norm_shipped_rewrites_wiki_icon_warts_before_alignment(raw, expected):
    """Alignment matches a template against wiki-derived English. Every wart
    left in here becomes an alignment failure and an entity stuck in English."""
    assert localize.norm_shipped(raw) == expected


# ------------------------------------------------------------------- parsing

@pytest.mark.parametrize("s, start, expected", [
    ("{a}", 0, 2),
    ("{a{b}c}tail", 0, 6),          # nested braces
    ("{unterminated", 0, -1),
    ("xx{a}", 2, 4),
])
def test_find_close_matches_the_outermost_brace(s, start, expected):
    assert localize.find_close(s, start) == expected


@pytest.mark.parametrize("s, expected", [
    ("a|b|c", ["a", "b", "c"]),
    ("single", ["single"]),
    ("", [""]),
    ("a||c", ["a", "", "c"]),
    # a '|' inside a nested token belongs to that token, not to this split
    ("a{x|y}b|c", ["a{x|y}b", "c"]),
])
def test_split_top_ignores_separators_inside_nested_tokens(s, expected):
    assert localize.split_top(s) == expected


def _tok(spec):
    t = localize.parse_token(spec)
    if t is None:
        return None
    return (t.name, t.kind, t.fixed, t.branches, t.cond)


@pytest.mark.parametrize("spec, expected", [
    # plain value
    ("Damage", ("Damage", "NUM", None, None, None)),
    ("Damage:diff()", ("Damage", "NUM", None, None, None)),
    ("Damage:inverseDiff()", ("Damage", "NUM", None, None, None)),
    ("Damage:percentMore()", ("Damage", "NUM", None, None, None)),
    ("Damage:diff)", ("Damage", "NUM", None, None, None)),   # mangled by a translator
    # bare {} inside a branch refers to the enclosing token's value
    ("", ("", "INNER", None, None, None)),
    (":diff()", ("", "INNER", None, None, None)),
    # icons
    ("singleStarIcon", ("singleStarIcon", "STAR", 1, None, None)),
    ("Cost:energyIcons(2)", ("Cost", "ENERGY", 2, None, None)),
    ("Cost:energyIcons()", ("Cost", "ENERGY", None, None, None)),
    ("S:starIcons(3)", ("S", "STAR", 3, None, None)),
    ("S:starIcons()", ("S", "STAR", None, None, None)),
    # enchantment names resolve through a separate lookup table
    ("EnchantmentName", ("EnchantmentName", "ENCH", None, None, None)),
    ("Enchantment", ("Enchantment", "ENCH", None, None, None)),
    # plurals, including the translator-mangled "diff():plural" spelling
    ("N:plural:card|cards", ("N", "PLURAL", None, ["card", "cards"], None)),
    ("N:diff():plural:card|cards", ("N", "PLURAL", None, ["card", "cards"], None)),
    ("N:plural(ru):a|b|c", ("N", "PLURAL_RU", None, ["a", "b", "c"], None)),
    ("N:diff():plural(ru):a|b|c", ("N", "PLURAL_RU", None, ["a", "b", "c"], None)),
    # show / choose / operator-less cond all collapse to a branch choice, and a
    # one-branch show gains an implicit empty alternative
    ("X:show:yes|no", ("X", "SHOW", None, ["yes", "no"], None)),
    ("X:show:yes", ("X", "SHOW", None, ["yes", ""], None)),
    ("X:choose(a|b):p|q", ("X", "SHOW", None, ["p", "q"], None)),
    ("V.StringValue:cond:A|B", ("V.StringValue", "SHOW", None, ["A", "B"], None)),
    ("A:b|c", ("A", "SHOW", None, ["b", "c"], None)),
    # comparison cond keeps its operator and threshold
    ("N:cond:>1?many|one", ("N", "COND", None, ["many", "one"], (">", 1))),
    ("N:cond:<=3?few|lots", ("N", "COND", None, ["few", "lots"], ("<=", 3))),
    ("N:cond:==0?none|some", ("N", "COND", None, ["none", "some"], ("==", 0))),
    # single-branch fallback is a translator artifact and is left unresolvable
    ("Chaos:only", ("Chaos", "TEXT", None, ["only"], None)),
])
def test_parse_token_covers_every_shipped_template_form(spec, expected):
    assert _tok(spec) == expected


@pytest.mark.parametrize("spec", [
    "Weird?",                # name followed by something that is not ':'
    "X:choose(a|b)nope",     # choose(...) not followed by ':'
])
def test_parse_token_refuses_what_it_cannot_read(spec):
    """Returning None makes the whole template unparseable, which drops the
    entity back to English -- far better than guessing at its structure."""
    assert localize.parse_token(spec) is None


def test_parse_template_splits_literals_from_tokens():
    elems = localize.parse_template("Gain {Block} Block and draw {N}.")
    assert [k for k, _ in elems] == ["lit", "tok", "lit", "tok", "lit"]
    assert [v for k, v in elems if k == "lit"] == ["Gain ", " Block and draw ", "."]
    assert [(v.name, v.kind) for k, v in elems if k == "tok"] == [
        ("Block", "NUM"), ("N", "NUM")]


def test_parse_template_handles_text_with_no_tokens():
    assert localize.parse_template("Just words.") == [("lit", "Just words.")]


@pytest.mark.parametrize("text", [
    "Deal {Damage damage",     # never closed
    "Deal {Weird?} damage.",   # token body unparseable
])
def test_parse_template_returns_none_on_malformed_input(text):
    assert localize.parse_template(text) is None


# --------------------------------------------------------- English alignment

def test_extract_english_recovers_a_plain_number():
    assert localize.extract_english("Deal {Damage} damage.", "Deal 9 damage.") == (
        {"Damage": ["9"]}, {}, {})


def test_extract_english_tolerates_a_dropped_trailing_period():
    """Wiki-derived text routinely loses the final period; without this the
    entity would fail alignment for punctuation alone."""
    assert localize.extract_english("Deal {Damage} damage.", "Deal 9 damage") == (
        {"Damage": ["9"]}, {}, {})


def test_extract_english_tolerates_a_stray_space_before_punctuation():
    assert localize.extract_english("Deal {D} damage.", "Deal 9 damage .") == (
        {"D": ["9"]}, {}, {})


def test_extract_english_accepts_singular_where_the_template_says_attacks():
    """lit_pattern relaxes Attack/Skill/Power plurals because the wiki writes
    the singular where the template writes the plural."""
    assert localize.extract_english("Play {N} Attacks.", "Play 2 Attack.") == (
        {"N": ["2"]}, {}, {})


def test_extract_english_reads_wiki_type_tags_through_norm_shipped():
    got = localize.extract_english("Whenever you play {N} Attacks, gain {B} Block.",
                                   "Whenever you play 3 type:Attack, gain 5 Block.")
    assert got == ({"N": ["3"], "B": ["5"]}, {}, {})


@pytest.mark.parametrize("shipped, expected_value", [
    ("Costs 2 Energy.", "2"),
    # the wiki bakes an icon run as a repeated "1 Energy"
    ("Costs 1 Energy 1 Energy 1 Energy.", "3"),
])
def test_extract_english_collapses_energy_icon_runs(shipped, expected_value):
    got = localize.extract_english("Costs {C:energyIcons()}.", shipped)
    assert got == ({"C": [expected_value]}, {}, {})


def test_extract_english_rejects_an_ambiguous_energy_run():
    """"2 Energy 3 Energy" is neither a single value nor a run of ones, so the
    cost cannot be recovered and the entity must stay English."""
    assert localize.extract_english("Costs {C:energyIcons()}.",
                                    "Costs 2 Energy 3 Energy.") is None


def test_extract_english_reads_a_star_cost():
    assert localize.extract_english("Spend {S:starIcons()}.", "Spend 3 Stars.") == (
        {"S": ["3"]}, {}, {})


def test_extract_english_reads_star_costs_written_as_icon_markers():
    assert localize.extract_english("Spend {S:starIcons()}.", "Spend @ST@ST.") == (
        {"S": ["2"]}, {}, {})


def test_fixed_icons_need_no_value():
    assert localize.extract_english("Fixed {X:energyIcons(2)} cost.",
                                    "Fixed 2 Energy cost.") == ({}, {}, {})


def test_extract_english_records_which_show_branch_the_english_took():
    tpl = "{X:show:Exhaust.|Retain.}"
    assert localize.extract_english(tpl, "Exhaust.") == ({}, {"X": [0]}, {})
    assert localize.extract_english(tpl, "Retain.") == ({}, {"X": [1]}, {})


def test_extract_english_infers_one_from_a_matched_singular_branch():
    """"Draw 1 card" carries the count only in the word "card"; recording that
    the singular branch matched is how the value 1 is recovered at all."""
    values, branches, hints = localize.extract_english(
        "Draw {N} {N:diff():plural:card|cards}.", "Draw 1 card.")
    assert values["N"][0] == "1"
    assert branches["N"] == [0]
    assert hints == {}


def test_extract_english_marks_a_plural_match_as_many():
    values, branches, hints = localize.extract_english(
        "Draw {N} {N:diff():plural:card|cards}, then discard {N}.",
        "Draw 2 cards, then discard 2.")
    assert values["N"] == ["2", "2"]
    assert branches["N"] == [1]
    assert hints["N"] == "many"


def test_extract_english_recovers_a_cond_threshold_from_the_else_branch():
    """The ">1" else-branch can only have been taken when the value is 1, so
    the number is recoverable even though it never appears in the text."""
    values, branches, hints = localize.extract_english(
        "Deal {D} damage {N:cond:>1?{} times|once}.", "Deal 5 damage once.")
    assert values == {"D": ["5"], "N": ["1"]}
    assert branches["N"] == [1]
    assert hints == {}


def test_extract_english_reads_a_value_from_inside_a_cond_branch():
    values, branches, hints = localize.extract_english(
        "Deal {D} damage {N:cond:>1?{} times|once}.", "Deal 5 damage 3 times.")
    assert values == {"D": ["5"], "N": ["3"]}
    assert hints["N"] == "many"


def test_extract_english_captures_an_enchantment_name():
    got = localize.extract_english("Enchant with {EnchantmentName}.",
                                   "Enchant with Tezcatara's Ember.")
    assert got == ({"EnchantmentName": ["Tezcatara's Ember"]}, {}, {})


def test_extract_english_on_a_template_with_no_tokens_yields_nothing_to_fill():
    assert localize.extract_english("Exhaust.", "Exhaust.") == ({}, {}, {})


@pytest.mark.parametrize("template, shipped", [
    # wording simply does not correspond
    ("Deal {Damage} damage.", "Heal 9 health."),
    # unparseable template
    ("Deal {Damage damage.", "Deal 9 damage."),
    # a TEXT token has no pattern, so the whole alignment is abandoned
    ("Gain {Chaos:only} Block.", "Gain 5 Block."),
    # unparseable body nested inside a branch
    ("{X:show:{Weird?}|B} thing.", "B thing."),
])
def test_extract_english_fails_closed(template, shipped):
    """Every failure here means "leave this entity in English". Guessing would
    ship a wrong number to every translated player."""
    assert localize.extract_english(template, shipped) is None


def test_extract_english_rejects_a_degenerate_all_empty_match():
    """A template of nothing but optional branches can match the empty string
    anywhere; accepting that would "translate" an entity into blank text."""
    assert localize.extract_english("{X:show:|}", "anything at all") is None


# ------------------------------------------------------- single-number fallback

def test_fallback_recovers_the_number_when_only_the_wording_drifted():
    assert localize.fallback_single_number("Deal {Damage} damage.",
                                           "Deals 7 damage to ALL enemies.") == (
        {"Damage": ["7"]}, {}, {})


def test_fallback_ignores_ordinals_when_counting_numbers():
    """"the 3rd turn" is prose, not a value; counting it would make the text
    look ambiguous and lose an otherwise recoverable number."""
    assert localize.fallback_single_number("Deal {D} damage on the 3rd turn.",
                                           "Deal 9 damage on the 3rd turn.") == (
        {"D": ["9"]}, {}, {})


def test_fallback_fills_every_occurrence_of_the_single_name():
    got = localize.fallback_single_number("Deal {D} damage. Block {D}.",
                                          "Deal 6 damage and block the same.")
    assert got == ({"D": ["6", "6"]}, {}, {})


@pytest.mark.parametrize("template, shipped, why", [
    ("Deal {D} damage.", "Deals 7 damage 3 times.", "two numbers: ambiguous"),
    ("Deal {D} damage.", "Deals damage.", "no number at all"),
    ("Deal {D} damage, gain {B} Block.", "Something with 7 in it", "two names"),
    ("{X:show:A|B}", "1", "a branch choice cannot be guessed"),
    ("{N:cond:>1?a|b}", "1", "a cond cannot be guessed"),
    ("{Chaos:only}", "1", "TEXT is unresolvable"),
    ("{EnchantmentName}", "1", "a name is not a number"),
    ("{}", "1", "a bare inner token has no owner here"),
    ("Draw {N} {N:plural:{} card|{} cards}.", "Draw 4 cards.",
     "nested tokens inside branches are too risky to guess"),
    ("Deal {D} damage.", "Deal {broken", "unparseable shipped is still one number"),
])
def test_fallback_refuses_every_ambiguous_case(template, shipped, why):
    assert localize.fallback_single_number(template, shipped) is None, why


def test_fallback_allows_a_plural_with_plain_branches():
    """The plural word carries no value of its own, so a lone {N} is still an
    unambiguous assignment."""
    assert localize.fallback_single_number(
        "Draw {N} {N:diff():plural:card|cards}.", "Draw 4 cards.") == (
        {"N": ["4"]}, {}, {})


def test_fallback_ignores_fixed_icons_when_counting_names():
    assert localize.fallback_single_number("Costs {X:energyIcons(1)}. Deal {D}.",
                                           "Costs 1 Energy. Deal 8.") is None


# ---------------------------------------------------------- Russian plurals

@pytest.mark.parametrize("n, form", [
    # form 0 = nominative singular (1 карта), 1 = genitive singular (2 карты),
    # 2 = genitive plural (5 карт). Anchors are real Russian agreement.
    (1, 0), (21, 0), (101, 0), (1001, 0),
    (2, 1), (3, 1), (4, 1), (22, 1), (24, 1), (104, 1),
    (0, 2), (5, 2), (9, 2), (10, 2),
    (11, 2), (12, 2), (13, 2), (14, 2),   # the teens are the exception
    (25, 2), (111, 2), (112, 2),
])
def test_plural_index_ru_follows_russian_agreement(n, form):
    assert localize.plural_index_ru(n, 3) == form


def test_plural_index_ru_is_sign_insensitive():
    assert localize.plural_index_ru(-21, 3) == localize.plural_index_ru(21, 3)


@pytest.mark.parametrize("n, expected", [(1, 0), (0, 1), (2, 1), (5, 1)])
def test_plural_index_ru_degrades_to_english_rules_for_two_branches(n, expected):
    assert localize.plural_index_ru(n, 2) == expected


@pytest.mark.parametrize("n", [0, 1, 2, 7])
def test_plural_index_ru_with_one_branch_always_picks_it(n):
    assert localize.plural_index_ru(n, 1) == 0


# ------------------------------------------------------------ needs_alignment

@pytest.mark.parametrize("template, expected", [
    ("Exhaust.", False),
    ("Costs {X:energyIcons(2)}.", False),      # fixed icon needs no value
    ("{singleStarIcon}", False),
    ("Deal {D} damage.", True),
    ("Costs {X:energyIcons()}.", True),
    ("{X:show:A|B}", True),
    ("Broken {", True),                        # unparseable: will fail anyway
])
def test_needs_alignment_identifies_templates_that_need_english_values(template, expected):
    assert localize.needs_alignment(template) is expected


# ------------------------------------------------------------------ rendering

def _render(template, values=None, branches=None, hints=None, lang="de",
            energy="Energie", star="Stern", ench_lookup=None):
    r = localize.Renderer(values or {}, branches or {}, lang, energy, star,
                          hints or {}, ench_lookup)
    return r.render(template)


def test_render_substitutes_values_into_a_translated_template():
    assert _render("Verursache {D} Schaden.", {"D": ["9"]}) == "Verursache 9 Schaden."


def test_render_strips_markup_from_translated_literals():
    assert _render("Gewinne [gold]{B}[/gold] Block.", {"B": ["5"]}) == "Gewinne 5 Block."


def test_render_consumes_repeated_values_in_order():
    assert _render("{D} dann {D}.", {"D": ["3", "7"]}) == "3 dann 7."


def test_render_reuses_the_last_value_when_a_template_repeats_a_token():
    """A translation may mention a value more often than English did. Reusing
    the last known value beats failing the whole entity."""
    assert _render("{D} {D} {D}", {"D": ["4"]}) == "4 4 4"


def test_render_places_the_icon_word_after_the_number():
    assert _render("Kostet {C:energyIcons()}.", {"C": ["2"]}) == "Kostet 2 Energie."
    assert _render("Kostet {S:starIcons()}.", {"S": ["3"]}) == "Kostet 3 Stern."


def test_render_omits_the_space_before_icon_words_in_cjk():
    """CJK_NOSPACE is keyed by the game's own locale folder ("jpn"), which is
    what _build_all passes -- not the app locale code ("ja"). Feeding the app
    code in would silently put a space back into every Japanese cost."""
    assert _render("{C:energyIcons()}", {"C": ["2"]}, lang="jpn",
                   energy="エナジー") == "2エナジー"
    assert _render("{C:energyIcons()}", {"C": ["2"]}, lang="zhs",
                   energy="能量") == "2能量"


def test_render_treats_an_icon_after_a_digit_as_a_unit_not_a_second_number():
    """The game writes "0[energy icon]" meaning "0 Energy". Rendering the icon
    as its own "1" would turn a zero cost into "01 Energie"."""
    assert _render("0{X:energyIcons(1)}", {}) == "0 Energie"
    assert _render("0 {X:energyIcons(1)}", {}) == "0 Energie"
    assert _render("0{X:energyIcons(1)}", {}, lang="jpn", energy="エナジー") == "0エナジー"


def test_render_a_fixed_icon_greater_than_one_keeps_its_number():
    assert _render("Kostet {X:energyIcons(2)}.", {}) == "Kostet 2 Energie."


def test_render_single_star_icon_is_one_star():
    assert _render("{singleStarIcon}", {}) == "1 Stern"


def test_render_picks_the_plural_branch_from_the_number_not_from_english():
    """The recorded English branch is a fallback only. German, Russian and the
    rest must agree with the *value*, or "2 Karte" ships."""
    tpl = "Ziehe {N} {N:diff():plural:Karte|Karten}."
    assert _render(tpl, {"N": ["1"]}) == "Ziehe 1 Karte."
    assert _render(tpl, {"N": ["2"]}) == "Ziehe 2 Karten."
    assert _render(tpl, {"N": ["7"]}) == "Ziehe 7 Karten."


def test_render_uses_russian_agreement_for_a_three_branch_plural():
    tpl = "{N} {N:plural(ru):карта|карты|карт}"
    assert _render(tpl, {"N": ["1"]}, lang="ru") == "1 карта"
    assert _render(tpl, {"N": ["3"]}, lang="ru") == "3 карты"
    assert _render(tpl, {"N": ["5"]}, lang="ru") == "5 карт"


def test_a_three_branch_plural_uses_russian_rules_even_without_the_ru_marker():
    tpl = "{N:plural:a|b|c}"
    assert _render(tpl, {"N": ["1"]}) == "a"
    assert _render(tpl, {"N": ["3"]}) == "b"
    assert _render(tpl, {"N": ["5"]}) == "c"


def test_render_treats_an_x_valued_plural_as_plural():
    """X is the game's "variable amount" marker; it is never exactly one."""
    assert _render("{N:plural:Karte|Karten}", {"N": ["X"]}) == "Karten"


def test_render_falls_back_to_the_english_branch_when_there_is_no_number():
    assert _render("{N:plural:Karte|Karten}", {}, {"N": [1]}) == "Karten"


def test_render_expands_a_bare_inner_token_to_the_owning_value():
    assert _render("{N:plural:eine Karte|{} Karten}", {"N": ["4"]}) == "4 Karten"


def test_render_follows_the_recorded_branch_for_a_show_token():
    tpl = "{X:show:Verbannen.|Behalten.}"
    assert _render(tpl, {}, {"X": [0]}) == "Verbannen."
    assert _render(tpl, {}, {"X": [1]}) == "Behalten."


def test_render_consumes_show_branches_in_order_then_reuses_the_last():
    """Once the recorded choices run out the last one repeats, so a translation
    that mentions the token more often than English did still renders."""
    assert _render("{X:show:a|b}{X:show:a|b}{X:show:a|b}", {}, {"X": [0, 1]}) == "abb"


@pytest.mark.parametrize("op, thr, value, expected", [
    (">", 1, "3", "viele"), (">", 1, "1", "eine"),
    (">=", 2, "2", "viele"), (">=", 2, "1", "eine"),
    ("<", 2, "1", "viele"), ("<", 2, "5", "eine"),
    ("<=", 1, "1", "viele"), ("<=", 1, "9", "eine"),
    ("==", 3, "3", "viele"), ("==", 3, "4", "eine"),
])
def test_render_evaluates_every_cond_operator(op, thr, value, expected):
    tpl = "{N:cond:%s%d?viele|eine}" % (op, thr)
    assert _render(tpl, {"N": [value]}) == expected


def test_render_resolves_a_cond_from_the_many_hint_when_no_number_survived():
    """English matched the plural branch, so the value is known to exceed one
    even though the digit itself never appeared in the text."""
    assert _render("{N:cond:>1?viele|eine}", {}, {}, {"N": "many"}) == "viele"


def test_render_resolves_an_enchantment_name_through_the_lookup():
    assert _render("Verzaubere mit {EnchantmentName}.",
                   {"EnchantmentName": ["Ember"]},
                   ench_lookup={"Ember": "Glut"}.get) == "Verzaubere mit Glut."


@pytest.mark.parametrize("template, values, branches, hints, message", [
    ("Deal {D}.", {}, {}, {}, "no value for D"),
    ("{X:show:A|B}", {}, {}, {}, "no branch for X"),
    ("{}", {}, {}, {}, "bare {} outside branch"),
    ("{N:plural:a|b}", {}, {}, {}, "plural unresolved for N"),
    ("{N:cond:>1?a|b}", {}, {}, {}, "cond unresolved for N"),
    # a "many" hint only helps the > and >= directions
    ("{N:cond:<5?a|b}", {}, {}, {"N": "many"}, "cond unresolved for N"),
    ("{Chaos:only}", {}, {}, {}, "kind TEXT"),
    ("{X:show:A|B}", {}, {"X": [5]}, {}, "branch idx out of range for X"),
    ("{N:cond:<1?only}", {"N": ["9"]}, {}, {}, "cond branches"),
    ("Broken {", {}, {}, {}, "parse"),
])
def test_render_fails_loudly_rather_than_emitting_broken_text(
        template, values, branches, hints, message):
    with pytest.raises(localize.RenderFail, match=message):
        _render(template, values, branches, hints)


def test_render_fails_when_an_enchantment_cannot_be_resolved():
    with pytest.raises(localize.RenderFail, match="unresolved"):
        _render("{EnchantmentName}", {"EnchantmentName": ["Unknown"]},
                ench_lookup=lambda _t: None)


def test_render_fails_when_an_inner_token_has_no_value():
    with pytest.raises(localize.RenderFail, match="no inner value"):
        _render("{N:plural:a|{} b}", {}, {"N": [1]})


# ------------------------------------------------------------- render_text

def test_render_text_collapses_newlines_and_whitespace():
    assert localize.render_text("Zeile\neins   {D}", ({"D": ["2"]}, {}, {}),
                                "de", "Energie", "Stern") == "Zeile eins 2"


def test_render_text_rejects_an_empty_result():
    """An empty overlay string would blank the description in the UI; failing
    means the entity keeps its English text instead."""
    with pytest.raises(localize.RenderFail, match="empty render"):
        localize.render_text("", ({}, {}, {}), "de", "Energie", "Stern")


@pytest.mark.parametrize("template", ["Gewinne @ Block.", "Gewinne [ Block."])
def test_render_text_rejects_leftover_game_markup(template):
    """This is the last line of defence: anything still carrying {}[]@ means a
    token was not understood, and shipping it shows raw markup to the player."""
    with pytest.raises(localize.RenderFail, match="residue"):
        localize.render_text(template, ({}, {}, {}), "de", "Energie", "Stern")


# ------------------------------------------------------------- resolve_key

@pytest.mark.parametrize("key, catalog, expected", [
    ("BASH", {"BASH"}, "BASH"),
    ("BOTTLED_FLAME_EVENT", {"BOTTLED_FLAME"}, "BOTTLED_FLAME"),
    ("SOME_QUEST", {"SOME"}, "SOME"),
    ("SOME_TOKEN", {"SOME"}, "SOME"),
    # an exact hit wins over stripping a suffix
    ("SOME_EVENT", {"SOME_EVENT", "SOME"}, "SOME_EVENT"),
    ("MISSING", {"BASH"}, None),
    ("BASH_OTHER", {"BASH"}, None),
])
def test_resolve_key_falls_back_through_the_dual_suffixes(key, catalog, expected):
    assert localize.resolve_key(key, catalog) == expected


def test_load_returns_an_empty_table_when_the_game_lacks_it(monkeypatch):
    monkeypatch.setattr(localize, "_LOC_DATA", {"deu": {"cards": {"A.title": "B"}}})
    assert localize.load("deu", "cards") == {"A.title": "B"}
    assert localize.load("deu", "relics") == {}
    assert localize.load("klingon", "cards") == {}


# ------------------------------------------------- full build, no game needed

def _filler_cards(n=20):
    """_build_all spot-checks 20 random cards, so the fixture needs at least
    that many before any of the interesting ones are added."""
    out = {}
    for i in range(n):
        out[f"FILLER_{i}.title"] = f"Filler {i}"
        out[f"FILLER_{i}.description"] = "Gain {Block} Block."
    return out


ENG_CARDS = {
    **_filler_cards(),
    "BASH.title": "Bash",
    "BASH.description": "Deal {Damage} damage. Apply {Vuln} Vulnerable.",
    "STATIC.title": "Static",
    "STATIC.description": "Exhaust.",                     # no alignment needed
    "NOTRANS.title": "Untranslated",
    "NOTRANS.description": "Deal {Damage} damage.",
    "RESIDUE.title": "Residue",
    "RESIDUE.description": "Deal {Damage} damage.",
    "DRIFTED.title": "Drifted",
    "DRIFTED.description": "Deal {Damage} damage.",       # wording drifted -> fallback
    "MISALIGNED.title": "Misaligned",
    "MISALIGNED.description": "Deal {Damage} damage and {Other} more.",
    "RENDERFAIL.title": "Render Fail",
    "RENDERFAIL.description": "Deal {Damage} damage.",
    "NODESC.title": "No Description",                     # title only, no template
    "PLAINNAME.title": "Plain Name",
    "PLAINNAME.description": "Deal {Damage} damage.",     # no shipped English text
    "SUFFIXED.title": "Suffixed",
    "SUFFIXED.description": "Gain {Block} Block.",
}

DEU_CARDS = {
    **{f"FILLER_{i}.title": f"Fuller {i}" for i in range(20)},
    **{f"FILLER_{i}.description": "Gewinne {Block} Block." for i in range(20)},
    "BASH.title": "Schmettern",
    "BASH.description": "Verursache {Damage} Schaden. Wende {Vuln} Verwundbar an.",
    "STATIC.title": "Statisch",
    "STATIC.description": "Verbannen.",
    # NOTRANS deliberately absent: not yet translated
    "RESIDUE.title": "Kaputt {Damage}",                   # unrendered markup in a name
    "RESIDUE.description": "Verursache {Damage} Schaden.",
    "DRIFTED.title": "Abgewichen",
    "DRIFTED.description": "Verursache {Damage} Schaden.",
    "MISALIGNED.title": "Fehlausrichtung",
    "MISALIGNED.description": "Verursache {Damage} Schaden.",
    "RENDERFAIL.title": "Render Fehler",
    "RENDERFAIL.description": "Verursache {Nirgends} Schaden.",   # unknown token
    "NODESC.title": "Keine Beschreibung",
    "PLAINNAME.title": "Schlichter Name",
    "PLAINNAME.description": "Verursache {Damage} Schaden.",
    "SUFFIXED.title": "Mit Suffix",
    "SUFFIXED.description": "Gewinne {Block} Block.",
}

APP_CARDS = [
    {"id": "CARD.BASH", "description": "Deal 8 damage. Apply 2 Vulnerable.",
     "description_upgraded": "Deal 10 damage. Apply 3 Vulnerable."},
    {"id": "CARD.STATIC", "description": "Exhaust."},
    {"id": "CARD.NOTRANS", "description": "Deal 5 damage."},
    {"id": "CARD.RESIDUE", "description": "Deal 5 damage."},
    {"id": "CARD.DRIFTED", "description": "Deals 6 damage to ALL enemies."},
    {"id": "CARD.MISALIGNED", "description": "Completely different wording."},
    {"id": "CARD.RENDERFAIL", "description": "Deal 7 damage."},
    {"id": "CARD.NODESC", "description": ""},
    {"id": "CARD.PLAINNAME", "description": ""},
    {"id": "CARD.SUFFIXED_EVENT", "description": "Gain 4 Block."},
    {"id": "CARD.NOT_IN_CATALOG", "description": "Deal 1 damage."},
]


def _write_app_data(tmp_path):
    """Write the shipped-English data files the builder aligns against.

    These carry *rendered* English (what the wiki scrape produced); the
    templates with the {tokens} live in the localization tables instead.
    """
    d = tmp_path / "data"
    d.mkdir(parents=True)
    payloads = {
        "cards": APP_CARDS,
        "relics": [
            {"id": "RELIC.BURNING_BLOOD", "description": "Heal 3 HP."},
            {"id": "RELIC.PLAIN", "description": "Does a thing."},
        ],
        "potions": [{"id": "POTION.FIRE", "description": "Deal 9 damage."}],
        "enemies": [
            {"id": "MONSTER.JAW_WORM"},
            {"id": "BOSS.HEXAGHOST"},
            {"id": "ENCOUNTER.THREE_LOUSE"},
            {"id": "CREATURE.CULTIST"},        # no prefix match, bare name hit
            {"id": "MONSTER.BROKEN"},          # localized name carries residue
            {"id": "MONSTER.UNKNOWN"},         # not in the game's tables at all
        ],
        "events": [{"id": "EVENT.NEOW"}, {"id": "EVENT.MYSTERY"}],
    }
    for name, payload in payloads.items():
        (d / f"{name}.json").write_text(json.dumps(payload), encoding="utf-8")
    return d


LOC_DATA = {
    "eng": {
        "cards": ENG_CARDS,
        "relics": {"BURNING_BLOOD.title": "Burning Blood",
                   "BURNING_BLOOD.description": "Heal {Heal} HP.",
                   "PLAIN.title": "Plain", "PLAIN.description": "Does a thing."},
        "potions": {"FIRE.title": "Fire Potion",
                    "FIRE.description": "Deal {Dmg} damage."},
        "monsters": {"JAW_WORM.name": "Jaw Worm", "HEXAGHOST.name": "Hexaghost",
                     "CULTIST.name": "Cultist", "BROKEN.name": "Broken"},
        "encounters": {"THREE_LOUSE.title": "Three Louses"},
        "events": {"NEOW.title": "Neow"},
        "static_hover_tips": {"ENERGY.title": "Energy", "STAR_COUNT.title": "Star"},
        "enchantments": {"EMBER.title": "Ember", "EMBER.body": "not a title"},
    },
    "deu": {
        "cards": DEU_CARDS,
        "relics": {"BURNING_BLOOD.title": "Brennendes Blut",
                   "BURNING_BLOOD.description": "Heile {Heal} LP.",
                   "PLAIN.title": "Schlicht", "PLAIN.description": "Tut etwas."},
        "potions": {"FIRE.title": "Feuertrank",
                    "FIRE.description": "Verursache {Dmg} Schaden."},
        "monsters": {"JAW_WORM.name": "Kieferwurm", "HEXAGHOST.name": "Hexageist",
                     "CULTIST.name": "Kultist", "BROKEN.name": "Kaputt {X}"},
        "encounters": {"THREE_LOUSE.title": "Drei Läuse"},
        "events": {"NEOW.title": "Neow"},
        "static_hover_tips": {"ENERGY.title": "Energie", "STAR_COUNT.title": "Stern"},
        "enchantments": {"EMBER.title": "Glut"},
    },
}


@pytest.fixture
def built(tmp_path, monkeypatch):
    """Run the whole overlay builder against fixtures, with no game present."""
    monkeypatch.setattr(localize, "APP", _write_app_data(tmp_path))
    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    monkeypatch.setattr(localize, "LANGS", ["deu"])
    monkeypatch.setattr(localize, "_LOC_DATA", LOC_DATA)
    report = localize._build_all()
    overlay = json.loads((tmp_path / "content" / "deu.json").read_text(encoding="utf-8"))
    return report, overlay


def test_build_writes_an_overlay_with_metadata(built):
    _report, overlay = built
    assert overlay["_meta"]["language_native"] == "Deutsch"
    assert overlay["_meta"]["source"] == "official game localization"
    assert set(overlay) >= {"cards", "relics", "potions", "enemies", "events"}


def test_build_renders_a_card_with_values_recovered_from_english(built):
    _report, overlay = built
    entry = overlay["cards"]["CARD.BASH"]
    assert entry["name"] == "Schmettern"
    assert entry["description"] == "Verursache 8 Schaden. Wende 2 Verwundbar an."


def test_build_renders_the_upgraded_description_from_its_own_english(built):
    """Upgraded text is aligned separately; sharing the base values would ship
    the unupgraded numbers on every upgraded card."""
    _report, overlay = built
    assert overlay["cards"]["CARD.BASH"]["description_upgraded"] == (
        "Verursache 10 Schaden. Wende 3 Verwundbar an.")


def test_build_translates_a_template_that_needs_no_alignment(built):
    entry = built[1]["cards"]["CARD.STATIC"]
    assert entry["name"] == "Statisch"
    assert entry["description"] == "Verbannen."


def test_build_uses_the_single_number_fallback_when_wording_drifted(built):
    _report, overlay = built
    assert overlay["cards"]["CARD.DRIFTED"]["description"] == "Verursache 6 Schaden."


def test_build_resolves_a_suffixed_id_back_to_its_catalog_entry(built):
    _report, overlay = built
    assert overlay["cards"]["CARD.SUFFIXED_EVENT"]["description"] == "Gewinne 4 Block."


@pytest.mark.parametrize("card_id, why", [
    ("CARD.NOTRANS", "no localized title yet"),
    ("CARD.RESIDUE", "localized name still carries template markup"),
    ("CARD.MISALIGNED", "English could not be aligned"),
    ("CARD.RENDERFAIL", "translated template needs a value English never gave"),
    ("CARD.NOT_IN_CATALOG", "shipped id is not in this game build"),
])
def test_build_leaves_unresolvable_cards_in_english(built, card_id, why):
    """Absence from the overlay is the fallback: knowledge.py then keeps the
    English entity. Emitting a partial entry would show raw markup instead."""
    _report, overlay = built
    assert card_id not in overlay["cards"], why


@pytest.mark.parametrize("card_id", ["CARD.NODESC", "CARD.PLAINNAME"])
def test_build_ships_a_name_only_entry_when_the_description_cannot_be_built(
        built, card_id):
    _report, overlay = built
    assert set(overlay["cards"][card_id]) == {"name"}


def test_build_translates_relics_and_potions_too(built):
    _report, overlay = built
    assert overlay["relics"]["RELIC.BURNING_BLOOD"]["description"] == "Heile 3 LP."
    assert overlay["relics"]["RELIC.PLAIN"]["description"] == "Tut etwas."
    assert overlay["potions"]["POTION.FIRE"]["description"] == "Verursache 9 Schaden."


@pytest.mark.parametrize("enemy_id, name", [
    ("MONSTER.JAW_WORM", "Kieferwurm"),
    ("BOSS.HEXAGHOST", "Hexageist"),
    ("ENCOUNTER.THREE_LOUSE", "Drei Läuse"),
    ("CREATURE.CULTIST", "Kultist"),
])
def test_build_maps_enemies_through_every_id_shape(built, enemy_id, name):
    _report, overlay = built
    assert overlay["enemies"][enemy_id] == {"name": name}


def test_build_drops_enemies_whose_localized_name_has_residue(built):
    _report, overlay = built
    assert "MONSTER.BROKEN" not in overlay["enemies"]
    assert "MONSTER.UNKNOWN" not in overlay["enemies"]


def test_build_maps_events_and_skips_unknown_ones(built):
    _report, overlay = built
    assert overlay["events"] == {"EVENT.NEOW": {"name": "Neow"}}


def test_build_report_counts_match_the_overlay(built):
    report, overlay = built
    counts, size, fail_ids = report["deu"]
    assert counts["cards_ok"] == len(
        [c for c in overlay["cards"].values() if "description" in c])
    assert counts["cards_name_only"] == 2
    assert counts["cards_upgraded"] == len(
        [c for c in overlay["cards"].values() if "description_upgraded" in c])
    assert counts["enemies_ok"] == 4
    assert counts["events_ok"] == 1
    assert size > 0
    # each failure is reported with the reason it failed, not just an id
    assert any("untranslated" in f for f in fail_ids)
    assert any("name residue" in f for f in fail_ids)
    assert any("eng align" in f for f in fail_ids)
    assert any("render:" in f for f in fail_ids)


def test_build_is_deterministic(tmp_path, monkeypatch):
    """The builder seeds its own sampler; two runs of the same inputs must
    produce byte-identical overlays or the data-release diff is noise."""
    outputs = []
    for run in ("a", "b"):
        monkeypatch.setattr(localize, "APP", _write_app_data(tmp_path / run))
        monkeypatch.setattr(localize, "OUT", tmp_path / run / "content")
        monkeypatch.setattr(localize, "LANGS", ["deu"])
        monkeypatch.setattr(localize, "_LOC_DATA", LOC_DATA)
        localize._build_all()
        outputs.append((tmp_path / run / "content" / "deu.json").read_bytes())
    assert outputs[0] == outputs[1]


def test_enchantment_names_are_localized_through_the_english_title_index(
        tmp_path, monkeypatch):
    """The lookup goes localized-title <- key <- English-title, so a card that
    names an enchantment only renders when the whole chain resolves."""
    app = _write_app_data(tmp_path)
    (app / "cards.json").write_text(json.dumps([
        {"id": "CARD.ENCHANTED", "description": "Enchant with Ember."},
        {"id": "CARD.MISSING_ENCH", "description": "Enchant with Nowhere."},
    ]), encoding="utf-8")
    loc = json.loads(json.dumps(LOC_DATA))  # deep copy
    for lang, name in (("eng", "Enchant with {EnchantmentName}."),
                       ("deu", "Verzaubere mit {EnchantmentName}.")):
        loc[lang]["cards"]["ENCHANTED.title"] = "Enchanted"
        loc[lang]["cards"]["ENCHANTED.description"] = name
        loc[lang]["cards"]["MISSING_ENCH.title"] = "Missing"
        loc[lang]["cards"]["MISSING_ENCH.description"] = name
    monkeypatch.setattr(localize, "APP", app)
    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    monkeypatch.setattr(localize, "LANGS", ["deu"])
    monkeypatch.setattr(localize, "_LOC_DATA", loc)
    localize._build_all()
    overlay = json.loads((tmp_path / "content" / "deu.json").read_text(encoding="utf-8"))
    assert overlay["cards"]["CARD.ENCHANTED"]["description"] == "Verzaubere mit Glut."
    # an enchantment the game has no name for must not ship a half-rendered card
    assert "CARD.MISSING_ENCH" not in overlay["cards"]


def test_build_falls_back_to_english_icon_words(tmp_path, monkeypatch):
    """A language whose static_hover_tips lack the icon titles still has to
    render costs; falling back to "Energy"/"Star" beats failing every card."""
    loc = json.loads(json.dumps(LOC_DATA))
    del loc["deu"]["static_hover_tips"]
    app = _write_app_data(tmp_path)
    (app / "cards.json").write_text(json.dumps(
        [{"id": "CARD.COSTLY", "description": "Costs 2 Energy."}]), encoding="utf-8")
    for lang, tpl in (("eng", "Costs {C:energyIcons()}."),
                      ("deu", "Kostet {C:energyIcons()}.")):
        loc[lang]["cards"]["COSTLY.title"] = "Costly"
        loc[lang]["cards"]["COSTLY.description"] = tpl
    monkeypatch.setattr(localize, "APP", app)
    monkeypatch.setattr(localize, "OUT", tmp_path / "content")
    monkeypatch.setattr(localize, "LANGS", ["deu"])
    monkeypatch.setattr(localize, "_LOC_DATA", loc)
    localize._build_all()
    overlay = json.loads((tmp_path / "content" / "deu.json").read_text(encoding="utf-8"))
    assert overlay["cards"]["CARD.COSTLY"]["description"] == "Kostet 2 Energy."
