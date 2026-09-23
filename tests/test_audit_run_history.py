"""Completed-run fidelity: card instances, multi-picks, act membership,
zero gold, and impossible imported values.

Fixtures are small synthetic native-format saves. Their shape mirrors what
real history files carry: deck entries with `current_upgrade_level` and an
`enchantment` object, `map_point_history` as one list per act, several
`was_picked` choices on one floor (a shop lists every card bought), and a
`current_gold` key on every player_stats entry.
"""
import json
from unittest.mock import AsyncMock, patch

from sts2.aggregate import compute_aggregate_stats
from sts2.analytics import analyze_run, compute_analytics
from sts2.integrity import DIGEST_VERSION, compute_payload_digest, compute_run_digest
from sts2.models import RunFloor, RunHistory
from sts2.saves import get_current_run, get_run_history


def _stats(**kw):
    base = {"player_id": 1, "damage_taken": 0, "hp_healed": 0, "current_hp": 70,
            "max_hp": 80, "current_gold": 100}
    base.update(kw)
    return base


def _floor(ptype="monster", encounter="ENCOUNTER.JAW_WORM", **stats):
    return {"map_point_type": ptype,
            "rooms": [{"room_type": ptype, "model_id": encounter,
                       "monster_ids": [], "turns_taken": 3}],
            "player_stats": [_stats(**stats)]}


# Two copies of Bash: one plain with SHARP, one upgraded with SWIFT.
# Act 1 is a single floor and Act 2 two floors, so the floor-number estimate
# (floors 1-17 = Act 1) necessarily misfiles floors 2 and 3.
NATIVE_RUN = {
    "players": [{
        "id": 1, "character": "CHARACTER.IRONCLAD",
        "deck": [
            {"id": "CARD.BASH", "current_upgrade_level": 0, "enchantment": {"id": "ENCHANTMENT.SHARP", "amount": 1}},
            {"id": "CARD.BASH", "current_upgrade_level": 1,
             "enchantment": {"id": "ENCHANTMENT.SWIFT", "amount": 1}},
            {"id": "CARD.STRIKE", "current_upgrade_level": 0},
        ],
        "relics": [{"id": "RELIC.BURNING_BLOOD"}],
    }],
    "win": False, "ascension": 3, "seed": "S", "run_time": 900,
    "killed_by_encounter": "ENCOUNTER.X", "start_time": 1700000000,
    "map_point_history": [
        [_floor(damage_taken=1, current_gold=100, card_choices=[
            {"card": {"id": "CARD.ANGER"}, "was_picked": True},
            {"card": {"id": "CARD.CLEAVE"}, "was_picked": True},
            {"card": {"id": "CARD.FLEX"}, "was_picked": False},
        ])],
        [_floor("shop", "", current_gold=20, card_choices=[
            {"card": {"id": "CARD.ANGER"}, "was_picked": True},
            {"card": {"id": "CARD.ANGER"}, "was_picked": True},
         ]),
         _floor(damage_taken=23, current_gold=0)],
    ],
}


def _write_history(tmp_path, data, name="1700000000.run"):
    hist = tmp_path / "history"
    hist.mkdir(exist_ok=True)
    (hist / name).write_text(json.dumps(data), encoding="utf-8")


def _parse(tmp_path, data=NATIVE_RUN) -> RunHistory:
    _write_history(tmp_path, data)
    with patch("sts2.saves.SAVE_DIR", tmp_path):
        runs = get_run_history()
    assert len(runs) == 1
    return runs[0]


# ---------------------------------------------------------------- F01 ----

class TestCardInstances:
    def test_upgrade_levels_and_enchantments_are_per_instance(self, tmp_path):
        run = _parse(tmp_path)
        assert run.deck == ["CARD.BASH", "CARD.BASH", "CARD.STRIKE"]
        assert run.deck_upgrades == [0, 1, 0]
        assert run.deck_enchantments == ["ENCHANTMENT.SHARP", "ENCHANTMENT.SWIFT", ""]

    def test_legacy_enchantments_dict_still_populated(self, tmp_path):
        run = _parse(tmp_path)
        # Id-keyed view is lossy by construction, but still present for old readers.
        assert run.enchantments == {"CARD.BASH": "ENCHANTMENT.SWIFT"}

    def test_malformed_upgrade_level_is_unavailable(self, tmp_path):
        data = json.loads(json.dumps(NATIVE_RUN))
        data["players"][0]["deck"] = [{"id": "CARD.BASH", "current_upgrade_level": "x"},
                                      {"id": "CARD.BASH", "current_upgrade_level": -2},
                                      {"id": "CARD.BASH", "current_upgrade_level": 2}]
        assert _parse(tmp_path, data).deck_upgrades == []

    async def test_instances_survive_export_import_round_trip(self, tmp_path, client):
        from sts2.app import generate_csrf_token
        run = _parse(tmp_path)
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
            exported = await client.get(f"/runs/{run.id}/export")
        payload = json.loads(exported.text)
        assert payload["run"]["deck_upgrades"] == [0, 1, 0]
        assert payload["run"]["deck_enchantments"] == [
            "ENCHANTMENT.SHARP", "ENCHANTMENT.SWIFT", ""]
        reimported = RunHistory(**payload["run"])
        assert reimported == run
        resp = await client.post(
            "/runs/import",
            files={"file": ("run.json", exported.text.encode(), "application/json")},
            data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 200
        assert "matches the checksum" in resp.text

    async def test_run_detail_shows_each_copy(self, tmp_path, client):
        run = _parse(tmp_path)
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)), \
             patch("sts2.app._get_runs", new=AsyncMock(return_value=[run])):
            resp = await client.get(f"/runs/{run.id}")
        assert resp.status_code == 200
        text = resp.text
        assert 'title="Upgraded">+</span>' in text
        sharp = _kb_name("ENCHANTMENT.SHARP")
        swift = _kb_name("ENCHANTMENT.SWIFT")
        assert f"Enchanted: {sharp}" in text and f"Enchanted: {swift}" in text

    async def test_compare_shows_upgraded_copies(self, client):
        a_run = RunHistory(id="a", character="Ironclad", win=True,
                           deck=["CARD.BASH", "CARD.BASH"], deck_upgrades=[1, 1])
        b_run = RunHistory(id="b", character="Ironclad", win=False, deck=["CARD.BASH"])
        with patch("sts2.app._get_run_by_id",
                   new=AsyncMock(side_effect=lambda rid: a_run if rid == "a" else b_run)):
            resp = await client.get("/runs/compare?a=a&b=b")
        assert resp.status_code == 200
        assert "(2+)" in resp.text

    async def test_legacy_run_without_instance_lists_renders(self, client):
        legacy = RunHistory(id="old", character="Ironclad", win=True,
                            deck=["CARD.BASH", "CARD.STRIKE"],
                            enchantments={"CARD.BASH": "ENCHANTMENT.SHARP"})
        assert legacy.deck_upgrades == [] and legacy.deck_enchantments == []
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=legacy)), \
             patch("sts2.app._get_runs", new=AsyncMock(return_value=[legacy])):
            resp = await client.get("/runs/old")
        assert resp.status_code == 200
        assert "Enchanted: " in resp.text  # falls back to the id-keyed dict


def _kb_name(entity_id: str) -> str:
    from sts2.app import kb
    return kb.id_to_name(entity_id)


# ---------------------------------------------------------------- F12 ----

class TestMultiplePicks:
    def test_every_pick_on_a_floor_is_kept(self, tmp_path):
        run = _parse(tmp_path)
        assert run.floors[0].cards_picked == ["CARD.ANGER", "CARD.CLEAVE"]
        assert run.floors[1].cards_picked == ["CARD.ANGER", "CARD.ANGER"]
        assert run.floors[2].cards_picked == []

    def test_legacy_card_picked_is_the_last_pick(self, tmp_path):
        run = _parse(tmp_path)
        assert run.floors[0].card_picked == "CARD.CLEAVE"
        assert run.floors[2].card_picked == ""

    def test_legacy_export_card_picked_becomes_one_pick(self):
        floor = RunFloor(floor=1, cards_offered=["CARD.A", "CARD.B"], card_picked="CARD.A")
        assert floor.cards_picked == ["CARD.A"]

    def test_current_run_keeps_every_pick(self, tmp_path):
        data = json.loads(json.dumps(NATIVE_RUN))
        with open(tmp_path / "current_run.save", "w", encoding="utf-8") as f:
            json.dump(data, f)
        with patch("sts2.saves.SAVE_DIR", tmp_path):
            cur = get_current_run()
        assert cur.floors[0].cards_picked == ["CARD.ANGER", "CARD.CLEAVE"]
        assert [f.act for f in cur.floors] == [1, 2, 2]

    def test_aggregate_counts_every_pick(self, tmp_path):
        agg = compute_aggregate_stats([_parse(tmp_path)])
        rates = agg["card_pick_rates"]
        assert rates["CARD.ANGER"] == {"picked": 3, "offered": 3}
        assert rates["CARD.CLEAVE"] == {"picked": 1, "offered": 1}
        assert rates["CARD.FLEX"] == {"picked": 0, "offered": 1}

    def test_analytics_pick_and_skip_counts(self, tmp_path):
        run = _parse(tmp_path)
        other = run.model_copy(update={"id": "r2"})
        stats = compute_analytics([run, other])
        rates = {r["id"]: r for r in stats["card_pick_rates"]}
        assert rates["CARD.CLEAVE"]["picked"] == 2
        assert rates["CARD.ANGER"]["picked"] == 6
        assert rates["CARD.FLEX"]["picked"] == 0
        # 4 picks per run, 2 in each stored act (the floor-number estimate
        # would have put all of them in Act 1).
        assert stats["per_act"][1]["cards_added"] == 4
        assert stats["per_act"][2]["cards_added"] == 4

    def test_regret_splits_duplicate_offers(self):
        # Two copies offered, one taken: one pick and one skip, not two picks.
        floor = RunFloor(floor=1, type="monster", cards_offered=["CARD.A", "CARD.A"],
                         cards_picked=["CARD.A"])
        runs = [RunHistory(id=f"r{i}", character="Ironclad", win=False, floors=[floor])
                for i in range(3)]
        regret = compute_analytics(runs)["card_regret"]
        assert regret["most_picked_in_losses"][0]["pick_rate"] == 50.0

    def test_analyze_run_sees_picks_beyond_the_last(self):
        run = RunHistory(id="r", character="Ironclad", win=False,
                         floors=[RunFloor(floor=1, cards_picked=["CARD.A"])])
        texts = [i["text"] for i in analyze_run(run)["insights"]]
        assert not any("No card rewards picked" in t for t in texts)


# ---------------------------------------------------------------- F13 ----

class TestActMembership:
    def test_parser_records_native_act(self, tmp_path):
        run = _parse(tmp_path)
        assert [f.act for f in run.floors] == [1, 2, 2]

    def test_damage_by_act_follows_native_grouping(self, tmp_path):
        stats = compute_analytics([_parse(tmp_path)])
        assert stats["damage_by_act"]["Act 1"]["avg_per_floor"] == 1
        assert stats["damage_by_act"]["Act 2"]["avg_per_floor"] == 23
        assert stats["per_act"][2]["death_count"] == 1
        assert stats["per_act"][1]["death_count"] == 0

    def test_seventeen_floor_act_one_boundary(self):
        from sts2.analytics import _floor_act
        # Floor 17 in a 16-floor Act 1 belongs to Act 2; floor 18 of a
        # 17-floor Act 1 belongs to Act 2 as well.
        assert _floor_act(RunFloor(floor=17, act=2)) == 2
        assert _floor_act(RunFloor(floor=17, act=1)) == 1

    def test_legacy_floor_without_act_falls_back_to_estimate(self):
        from sts2.analytics import _floor_act
        assert _floor_act(RunFloor(floor=5)) == 1
        assert _floor_act(RunFloor(floor=20)) == 2
        assert _floor_act(RunFloor(floor=40)) == 3


# ---------------------------------------------------------------- F14 ----

class TestZeroGold:
    def _run(self, golds, win=False, rid="r"):
        return RunHistory(id=rid, character="Ironclad", win=win, floors=[
            RunFloor(floor=i + 1, gold=g) for i, g in enumerate(golds)])

    def test_spent_down_to_zero_ends_at_zero(self):
        econ = compute_analytics([self._run([100, 0])])["gold_economy"]
        assert econ["avg_gold_at_death"] == 0
        assert econ["win_vs_loss_gold"]["loss_avg"] == 0

    def test_all_zero_run_stays_in_the_denominator(self):
        econ = compute_analytics([self._run([0, 0], rid="a"),
                                  self._run([200, 200], rid="b")])["gold_economy"]
        assert econ["avg_gold_per_run"] == 100
        assert econ["avg_gold_at_death"] == 100

    def test_wins_include_zero_final_gold(self):
        econ = compute_analytics([self._run([50, 0], win=True, rid="a"),
                                  self._run([80], win=True, rid="b")])["gold_economy"]
        assert econ["win_vs_loss_gold"]["win_avg"] == 40

    def test_zero_gold_floors_count_in_curve_and_per_act(self):
        stats = compute_analytics([self._run([100, 0])])
        assert stats["gold_economy"]["gold_curve"] == [{"floor": 5, "avg_gold": 50}]
        assert stats["per_act"][1]["avg_gold"] == 50


# ---------------------------------------------------------------- F21 ----

class TestImpossibleImportValues:
    @staticmethod
    async def _import(client, run: dict):
        from sts2.app import generate_csrf_token
        return await client.post(
            "/runs/import",
            files={"file": ("run.json", json.dumps({"format_version": 1, "run": run}).encode(),
                            "application/json")},
            data={"csrf_token": generate_csrf_token()})

    @staticmethod
    def _run(**kw) -> dict:
        run = RunHistory(id="r", character="Ironclad", win=False, run_time=100,
                         deck=["CARD.BASH"],
                         floors=[RunFloor(floor=1, gold=10, damage_taken=5)]).model_dump()
        run.update(kw)
        return run

    async def test_negative_run_time_rejected(self, client):
        resp = await self._import(client, self._run(run_time=-1))
        assert resp.status_code == 400
        assert "run_time must not be negative" in resp.text

    async def test_negative_floor_fields_rejected(self, client):
        for field in ("floor", "turns", "act"):
            run = self._run()
            run["floors"][0][field] = -3
            resp = await self._import(client, run)
            assert resp.status_code == 400, field
            assert f"{field} must not be negative" in resp.text, field

    async def test_misaligned_instance_lists_rejected(self, client):
        resp = await self._import(client, self._run(deck_upgrades=[1, 0]))
        assert resp.status_code == 400
        assert "one entry per deck card" in resp.text
        resp = await self._import(client, self._run(deck_upgrades=[-1]))
        assert resp.status_code == 400

    async def test_zero_and_large_modded_values_accepted(self, client):
        run = self._run(run_time=0, ascension=99)
        run["floors"] = [RunFloor(floor=f, gold=99999, damage_taken=0, max_hp=5000).model_dump()
                         for f in range(1, 121)]
        resp = await self._import(client, run)
        assert resp.status_code == 200

    async def test_legacy_export_without_new_fields_imports_and_verifies(self, client):
        """An export written before cards_picked/act/deck_upgrades existed
        must still import, and its v2 digest must still verify: the digest is
        over the file's own mapping, so fields the file never had are not
        part of it."""
        from sts2.app import generate_csrf_token
        legacy_run = {
            "id": "old", "character": "Ironclad", "win": False, "ascension": 0,
            "seed": "", "acts": [], "killed_by": "", "run_time": 60,
            "deck": ["CARD.BASH"], "relics": [], "build_id": "", "timestamp": 1,
            "total_players": 1, "origin": "vanilla", "enchantments": {},
            "floors": [{"floor": 1, "type": "monster", "encounter": "", "monsters": [],
                        "turns": 1, "damage_taken": 2, "hp_healed": 0, "current_hp": 1,
                        "max_hp": 2, "gold": 0, "cards_offered": ["CARD.A"],
                        "card_picked": "CARD.A", "potions_used": [], "potions_gained": []}],
        }
        body = {"format_version": 1, "digest_version": DIGEST_VERSION,
                "integrity_digest": compute_payload_digest(legacy_run), "run": legacy_run}
        resp = await client.post(
            "/runs/import",
            files={"file": ("run.json", json.dumps(body).encode(), "application/json")},
            data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 200
        assert "matches the checksum" in resp.text
        parsed = RunHistory(**legacy_run)
        assert parsed.floors[0].cards_picked == ["CARD.A"]
        assert parsed.floors[0].act == 0


class TestDigestCoversNewFields:
    def test_each_new_field_changes_digest(self):
        base_run = RunHistory(id="r", character="Ironclad", win=False, deck=["CARD.BASH"],
                              floors=[RunFloor(floor=1)])
        base = compute_run_digest(base_run)
        variants = [
            base_run.model_copy(update={"deck_upgrades": [1]}),
            base_run.model_copy(update={"deck_enchantments": ["ENCHANTMENT.SHARP"]}),
            base_run.model_copy(update={"floors": [RunFloor(floor=1, act=2)]}),
            base_run.model_copy(update={"floors": [RunFloor(floor=1, cards_picked=["CARD.A", "CARD.B"])]}),
        ]
        for v in variants:
            assert compute_run_digest(v) != base
