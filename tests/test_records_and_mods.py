"""Personal records, mod ingestion, and build-id carry-over across a bundle.

Three things that share a property: each one degrades quietly rather than
raising, so a break shows up as a wrong number or a missing entity on a page
rather than as a failing request.

- compute_records feeds the "hall of fame" panel. Every field is a max() or
  min() over run history; picking the wrong extreme is invisible without an
  assertion on the value.
- _load_mods runs at KnowledgeBase construction, which happens at application
  import. A hand-authored mod file is exactly where malformed input arrives,
  and anything that escapes as an exception takes the whole server down before
  a page can render.
- _merge_local_build_ids protects hand-assigned patch mappings from being
  discarded by a data-bundle install, which silently changes which runs count
  as current-patch and therefore the win rates shown.
"""
import json

import pytest

from sts2.analytics import compute_records
from sts2.models import PlayerProgress, RunFloor, RunHistory
from sts2.updater import _merge_local_build_ids


def _floor(n, ftype="monster", dmg=0, gold=0):
    return RunFloor(floor=n, type=ftype, damage_taken=dmg, gold=gold,
                    current_hp=50, max_hp=80)


def _run(rid, win=False, asc=0, char="Ironclad", run_time=1200, deck=None,
         floors=None):
    return RunHistory(id=rid, character=char, win=win, ascension=asc,
                      run_time=run_time, deck=deck or ["CARD.X"] * 20,
                      floors=floors if floors is not None else [_floor(1)])


# ----------------------------------------------------------------- records

def test_no_runs_means_no_records():
    assert compute_records([]) == {}


def test_records_are_empty_but_present_without_a_single_win():
    """A player with no wins still gets a records page; the win-only entries
    are absent rather than showing a loss as a personal best."""
    records = compute_records([_run("a"), _run("b")])
    assert records["fastest_win"] is None
    assert records["highest_ascension_win"] is None
    assert records["biggest_deck"] is None
    assert records["smallest_deck"] is None


def test_fastest_win_is_the_shortest_winning_run():
    runs = [_run("slow", win=True, run_time=9000),
            _run("fast", win=True, run_time=1500),
            _run("faster_but_lost", win=False, run_time=60)]
    fastest = compute_records(runs)["fastest_win"]
    assert fastest["run_id"] == "fast"
    assert fastest["time"] == 1500


def test_highest_ascension_win_ignores_losses():
    runs = [_run("w", win=True, asc=8), _run("l", win=False, asc=20)]
    best = compute_records(runs)["highest_ascension_win"]
    assert best["ascension"] == 8 and best["run_id"] == "w"


def test_deck_size_records_come_from_wins_only():
    runs = [_run("big", win=True, deck=["CARD.X"] * 45),
            _run("small", win=True, deck=["CARD.X"] * 12),
            _run("huge_loss", win=False, deck=["CARD.X"] * 99)]
    records = compute_records(runs)
    assert records["biggest_deck"] == {"size": 45, "character": "Ironclad",
                                       "run_id": "big"}
    assert records["smallest_deck"]["size"] == 12


def test_most_gold_is_the_richest_single_floor_across_every_run():
    runs = [_run("a", floors=[_floor(1, gold=200), _floor(2, gold=50)]),
            _run("b", floors=[_floor(3, gold=999)])]
    assert compute_records(runs)["most_gold"] == {"gold": 999, "run_id": "b",
                                                  "floor": 3}


def test_most_gold_ignores_floors_that_recorded_none():
    """gold == 0 usually means the floor simply did not record it, so it must
    not win the record by being the only entry."""
    runs = [_run("a", floors=[_floor(1, gold=0)])]
    assert compute_records(runs)["most_gold"] is None


def test_most_damage_floor_is_the_worst_single_floor():
    runs = [_run("a", floors=[_floor(1, dmg=10), _floor(2, dmg=44)]),
            _run("b", floors=[_floor(3, dmg=30)])]
    worst = compute_records(runs)["most_damage_floor"]
    assert worst == {"damage": 44, "floor": 2, "run_id": "a"}


def test_flawless_bosses_counts_boss_floors_taking_no_damage():
    runs = [_run("a", floors=[_floor(16, ftype="boss", dmg=0),
                              _floor(33, ftype="boss", dmg=12),
                              _floor(50, ftype="boss", dmg=0)]),
            _run("b", floors=[_floor(5, ftype="elite", dmg=0)])]
    assert compute_records(runs)["flawless_bosses"] == 2


def test_longest_streak_comes_from_progress_not_run_history():
    progress = PlayerProgress(character_stats={
        "Ironclad": {"best_streak": 3},
        "Silent": {"best_streak": 7},
    })
    streak = compute_records([_run("a")], progress)["longest_streak"]
    assert streak == {"count": 7, "character": "Silent"}


def test_a_zero_streak_is_not_a_record():
    progress = PlayerProgress(character_stats={"Ironclad": {"best_streak": 0}})
    assert compute_records([_run("a")], progress)["longest_streak"] is None


def test_records_without_progress_report_no_streak():
    assert compute_records([_run("a")])["longest_streak"] is None


def test_per_character_breakdown_splits_wins_from_losses():
    runs = [
        _run("i1", win=True, char="Ironclad", asc=5, run_time=2000),
        _run("i2", win=False, char="Ironclad"),
        _run("s1", win=True, char="Silent", asc=12, run_time=800),
    ]
    per = compute_records(runs)["per_character"]
    assert per["Ironclad"] == {"wins": 1, "losses": 1, "best_ascension": 5,
                               "fastest": 2000}
    assert per["Silent"]["best_ascension"] == 12


def test_per_character_defaults_to_zero_for_a_character_never_won_with():
    runs = [_run("d1", win=False, char="Defect")]
    assert compute_records(runs)["per_character"]["Defect"] == {
        "wins": 0, "losses": 1, "best_ascension": 0, "fastest": 0}


# -------------------------------------------------------------------- mods

@pytest.fixture
def modded_kb(tmp_path, monkeypatch):
    """Build a KnowledgeBase with MODS_DIR pointed at a temp directory."""
    def _build(files: dict[str, str]):
        mods = tmp_path / "mods"
        mods.mkdir(exist_ok=True)
        for name, content in files.items():
            (mods / name).write_text(content, encoding="utf-8")
        monkeypatch.setattr("sts2.knowledge.MODS_DIR", mods)
        from sts2.knowledge import KnowledgeBase
        return KnowledgeBase()
    return _build


def _mod(**sections):
    return json.dumps({"mod_name": "Test Mod", **sections})


def test_a_mod_adds_entities_marked_as_mod_sourced(modded_kb):
    # deliberately not "CARD.MODDED" -- that is a real Defect card in the
    # shipped data, so a mod using it is a genuine base conflict
    kb = modded_kb({"m.json": _mod(cards=[
        {"id": "CARD.SPIRESCOPE_TEST_MOD", "name": "Test Mod Card",
         "character": "Ironclad", "cost": "1", "type": "Attack",
         "rarity": "Common"}])})
    card = next(c for c in kb.cards if c.id == "CARD.SPIRESCOPE_TEST_MOD")
    assert card.source == "mod"


def test_a_mod_cannot_overwrite_a_base_card(modded_kb, caplog):
    """A mod that reuses a base id would silently replace shipped data."""
    kb = modded_kb({"m.json": _mod(cards=[
        {"id": "CARD.BASH", "name": "Hijacked", "character": "Ironclad",
         "cost": "1", "type": "Attack", "rarity": "Common"}])})
    assert next(c for c in kb.cards if c.id == "CARD.BASH").name != "Hijacked"
    assert "conflicts with base" in caplog.text


def test_mod_id_namespaces_entity_ids_so_two_mods_cannot_collide(modded_kb):
    kb = modded_kb({
        "a.json": json.dumps({"mod_name": "A", "mod_id": "alpha", "cards": [
            {"id": "CARD.SHARED", "name": "From Alpha", "character": "Ironclad",
             "cost": "1", "type": "Attack", "rarity": "Common"}]}),
        "b.json": json.dumps({"mod_name": "B", "mod_id": "beta", "cards": [
            {"id": "CARD.SHARED", "name": "From Beta", "character": "Ironclad",
             "cost": "1", "type": "Attack", "rarity": "Common"}]}),
    })
    ids = {c.id for c in kb.cards if c.source == "mod"}
    assert ids == {"mod:alpha:CARD.SHARED", "mod:beta:CARD.SHARED"}


def test_an_already_namespaced_id_is_not_namespaced_twice(modded_kb):
    kb = modded_kb({"a.json": json.dumps({
        "mod_name": "A", "mod_id": "alpha", "cards": [
            {"id": "mod:alpha:CARD.X", "name": "X", "character": "Ironclad",
             "cost": "1", "type": "Attack", "rarity": "Common"}]})})
    assert any(c.id == "mod:alpha:CARD.X" for c in kb.cards)


def test_mods_add_relics_potions_and_enemies_too(modded_kb):
    kb = modded_kb({"m.json": _mod(
        relics=[{"id": "RELIC.MODDED", "name": "Modded Relic",
                 "character": "Shared", "rarity": "Common"}],
        potions=[{"id": "POTION.MODDED", "name": "Modded Potion",
                  "rarity": "Common"}],
        enemies=[{"id": "MONSTER.MODDED", "name": "Modded Monster",
                  "act": ["1"], "type": "normal"}],
    )})
    assert any(r.id == "RELIC.MODDED" for r in kb.relics)
    assert any(p.id == "POTION.MODDED" for p in kb.potions)
    assert any(e.id == "MONSTER.MODDED" for e in kb.enemies)


def test_a_duplicate_relic_or_potion_or_enemy_is_skipped(modded_kb, caplog):
    base = modded_kb({})
    existing_relic = base.relics[0].id
    existing_potion = base.potions[0].id
    kb = modded_kb({"m.json": _mod(
        relics=[{"id": existing_relic, "name": "Hijacked",
                 "character": "Shared", "rarity": "Common"}],
        potions=[{"id": existing_potion, "name": "Hijacked",
                  "rarity": "Common"}],
    )})
    assert next(r for r in kb.relics if r.id == existing_relic).name != "Hijacked"
    assert next(p for p in kb.potions if p.id == existing_potion).name != "Hijacked"


@pytest.mark.parametrize("content, why", [
    ("{ not json", "unparseable"),
    ("[1, 2, 3]", "valid JSON but a list, not an object"),
    ('"just a string"', "valid JSON but a bare string"),
    ("null", "valid JSON null"),
])
def test_a_malformed_mod_file_never_stops_startup(modded_kb, content, why):
    """KnowledgeBase() runs at application import, so anything escaping here
    takes the server down before a single page can render."""
    kb = modded_kb({"bad.json": content})
    assert kb.cards, why


@pytest.mark.parametrize("section_value", ['"a string"', "123", "null", "{}"])
def test_a_section_of_the_wrong_shape_is_ignored(modded_kb, section_value):
    """A string here would iterate character by character and hand each one to
    the namespacing helper, which then fails on .get()."""
    kb = modded_kb({"m.json": '{"mod_name": "T", "cards": %s}' % section_value})
    assert kb.cards


def test_non_object_entries_inside_a_section_are_dropped(modded_kb, caplog):
    kb = modded_kb({"m.json": json.dumps({"mod_name": "T", "cards": [
        "not an object",
        {"id": "CARD.GOOD", "name": "Good", "character": "Ironclad",
         "cost": "1", "type": "Attack", "rarity": "Common"},
    ]})})
    assert any(c.id == "CARD.GOOD" for c in kb.cards)
    assert "dropped 1 non-object" in caplog.text


def test_a_malformed_record_is_skipped_without_losing_the_good_ones(
        modded_kb, caplog):
    kb = modded_kb({"m.json": json.dumps({"mod_name": "T", "cards": [
        {"id": "CARD.NO_REQUIRED_FIELDS"},
        {"id": "CARD.FINE", "name": "Fine", "character": "Ironclad",
         "cost": "1", "type": "Attack", "rarity": "Common"},
    ]})})
    assert any(c.id == "CARD.FINE" for c in kb.cards)
    assert not any(c.id == "CARD.NO_REQUIRED_FIELDS" for c in kb.cards)
    assert "skipping malformed card" in caplog.text


def test_no_mods_directory_is_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setattr("sts2.knowledge.MODS_DIR", tmp_path / "absent")
    from sts2.knowledge import KnowledgeBase
    assert KnowledgeBase().cards


# ------------------------------------------------ build-id carry-over

def _patches(path, entries):
    path.write_text(json.dumps(entries), encoding="utf-8")
    return path


def test_hand_assigned_build_ids_survive_a_bundle_install(tmp_path):
    """The bundle ships patches.json and wins for its own files, so without
    this the /admin/patches assignments were discarded on every data update --
    silently changing which runs count as current-patch."""
    local = _patches(tmp_path / "local.json",
                     [{"patch": "1.0", "build_ids": ["mine-1", "mine-2"]}])
    staged = _patches(tmp_path / "staged.json",
                      [{"patch": "1.0", "build_ids": ["official"]}])
    _merge_local_build_ids(local, staged)
    merged = json.loads(staged.read_text(encoding="utf-8"))
    assert merged[0]["build_ids"] == ["official", "mine-1", "mine-2"]


def test_a_build_id_already_in_the_bundle_is_not_duplicated(tmp_path):
    local = _patches(tmp_path / "local.json",
                     [{"patch": "1.0", "build_ids": ["shared"]}])
    staged = _patches(tmp_path / "staged.json",
                      [{"patch": "1.0", "build_ids": ["shared"]}])
    _merge_local_build_ids(local, staged)
    assert json.loads(staged.read_text(encoding="utf-8"))[0]["build_ids"] == ["shared"]


def test_a_patch_with_no_local_assignments_is_left_alone(tmp_path):
    local = _patches(tmp_path / "local.json", [{"patch": "1.0", "build_ids": []}])
    staged = _patches(tmp_path / "staged.json",
                      [{"patch": "2.0", "build_ids": ["official"]}])
    _merge_local_build_ids(local, staged)
    assert json.loads(staged.read_text(encoding="utf-8"))[0]["build_ids"] == ["official"]


def test_a_bundle_entry_without_build_ids_gains_the_local_ones(tmp_path):
    local = _patches(tmp_path / "local.json",
                     [{"patch": "1.0", "build_ids": ["mine"]}])
    staged = _patches(tmp_path / "staged.json", [{"patch": "1.0"}])
    _merge_local_build_ids(local, staged)
    assert json.loads(staged.read_text(encoding="utf-8"))[0]["build_ids"] == ["mine"]


def test_non_string_build_ids_are_not_carried(tmp_path):
    local = _patches(tmp_path / "local.json",
                     [{"patch": "1.0", "build_ids": [1, None, "good"]}])
    staged = _patches(tmp_path / "staged.json",
                      [{"patch": "1.0", "build_ids": []}])
    _merge_local_build_ids(local, staged)
    assert json.loads(staged.read_text(encoding="utf-8"))[0]["build_ids"] == ["good"]


def test_non_dict_entries_on_either_side_are_skipped(tmp_path):
    local = _patches(tmp_path / "local.json",
                     ["junk", {"patch": "1.0", "build_ids": ["mine"]}])
    staged = _patches(tmp_path / "staged.json",
                      ["junk", {"patch": "1.0", "build_ids": []}])
    _merge_local_build_ids(local, staged)
    assert json.loads(staged.read_text(encoding="utf-8"))[1]["build_ids"] == ["mine"]


@pytest.mark.parametrize("local_body, staged_body", [
    ("{ not json", '[{"patch": "1.0"}]'),
    ('[{"patch": "1.0"}]', "{ not json"),
    ('{"not": "a list"}', '[{"patch": "1.0"}]'),
    ('[{"patch": "1.0"}]', '{"not": "a list"}'),
])
def test_unreadable_or_wrong_shaped_manifests_leave_the_bundle_untouched(
        tmp_path, local_body, staged_body):
    local = (tmp_path / "local.json")
    local.write_text(local_body, encoding="utf-8")
    staged = (tmp_path / "staged.json")
    staged.write_text(staged_body, encoding="utf-8")
    _merge_local_build_ids(local, staged)
    assert staged.read_text(encoding="utf-8") == staged_body


def test_a_missing_manifest_on_either_side_is_a_no_op(tmp_path):
    staged = _patches(tmp_path / "staged.json", [{"patch": "1.0"}])
    _merge_local_build_ids(tmp_path / "absent.json", staged)
    assert json.loads(staged.read_text(encoding="utf-8")) == [{"patch": "1.0"}]
    local = _patches(tmp_path / "local.json", [{"patch": "1.0"}])
    _merge_local_build_ids(local, tmp_path / "absent.json")   # must not raise


def test_an_unwritable_manifest_is_logged_not_raised(tmp_path, monkeypatch, caplog):
    """This runs mid-install; raising here would abort a data update that has
    already staged its files."""
    local = _patches(tmp_path / "local.json",
                     [{"patch": "1.0", "build_ids": ["mine"]}])
    staged = _patches(tmp_path / "staged.json",
                      [{"patch": "1.0", "build_ids": []}])

    real_write = type(staged).write_text

    def flaky(self, *a, **kw):
        if self == staged:
            raise OSError("read-only file system")
        return real_write(self, *a, **kw)

    monkeypatch.setattr(type(staged), "write_text", flaky)
    _merge_local_build_ids(local, staged)
    assert "Could not write merged patch manifest" in caplog.text
