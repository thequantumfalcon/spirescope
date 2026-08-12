"""Run-integrity digest: every field bound, export carries it, import checks it.

The old hash chain omitted id, win, acts, killed_by, run_time, timestamp,
origin, and enchantments — two runs differing only in victory status, killer,
and runtime produced the SAME digest while the UI promised "byte-for-byte".
It also joined fields with ':'/',' unescaped, so ['Louse,Louse'] and
['Louse','Louse'] collided. And verify_run had no callers, so nothing was
ever actually verified.
"""
import json
from unittest.mock import AsyncMock, patch

from sts2.integrity import DIGEST_VERSION, compute_run_digest, verify_run
from sts2.models import RunFloor, RunHistory


def _base_run(**overrides) -> RunHistory:
    fields = dict(
        id="run-1", character="Ironclad", win=False, ascension=5,
        seed="SEED123", killed_by="MONSTER.NEMESIS", run_time=1800,
        deck=["CARD.STRIKE", "CARD.BASH"], relics=["RELIC.BURNING_BLOOD"],
        floors=[RunFloor(floor=1, type="monster", encounter="ENCOUNTER.JAW_WORM",
                         monsters=["Jaw Worm"], turns=3, damage_taken=4,
                         current_hp=76, gold=110)],
        build_id="build-1", timestamp=1000, origin="vanilla",
    )
    fields.update(overrides)
    return RunHistory(**fields)


class TestDigestBindsEveryField:
    def test_win_status_changes_digest(self):
        """The audit's reproduced collision: win/killed_by/run_time flips
        left the old digest identical."""
        loss = _base_run()
        victory = _base_run(win=True, killed_by="", run_time=2400)
        assert compute_run_digest(loss) != compute_run_digest(victory)

    def test_each_previously_unbound_field_changes_digest(self):
        base = compute_run_digest(_base_run())
        for override in ({"id": "run-2"}, {"win": True},
                         {"acts": ["Act 1"]}, {"killed_by": "MONSTER.OTHER"},
                         {"run_time": 1}, {"timestamp": 2000},
                         {"origin": "modded"},
                         {"enchantments": {"CARD.STRIKE": "ENCH.FIRE"}}):
            assert compute_run_digest(_base_run(**override)) != base, override

    def test_separator_ambiguity_is_gone(self):
        """['Louse,Louse'] vs ['Louse','Louse'] collided under ':'/',' joins."""
        one = _base_run(floors=[RunFloor(floor=1, monsters=["Louse,Louse"])])
        two = _base_run(floors=[RunFloor(floor=1, monsters=["Louse", "Louse"])])
        assert compute_run_digest(one) != compute_run_digest(two)

    def test_digest_is_stable_for_identical_runs(self):
        assert compute_run_digest(_base_run()) == compute_run_digest(_base_run())

    def test_verify_run_round_trip(self):
        run = _base_run()
        digest = compute_run_digest(run)
        assert verify_run(run, digest) is True
        assert verify_run(_base_run(win=True), digest) is False
        assert verify_run(run, "") is False


class TestExportCarriesDigest:
    async def test_export_includes_digest_and_version(self, client):
        run = _base_run()
        with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
            resp = await client.get("/runs/run-1/export")
        assert resp.status_code == 200
        payload = json.loads(resp.text)
        assert payload["digest_version"] == DIGEST_VERSION
        assert payload["integrity_digest"] == compute_run_digest(run)
        # Round trip: the run in the file reproduces the digest in the file.
        assert verify_run(RunHistory(**payload["run"]), payload["integrity_digest"])


class TestImportVerifiesDigest:
    @staticmethod
    async def _import(client, payload: dict):
        from sts2.app import generate_csrf_token
        return await client.post(
            "/runs/import",
            files={"file": ("run.json", json.dumps(payload).encode(),
                            "application/json")},
            data={"csrf_token": generate_csrf_token()})

    async def test_untampered_import_reports_verified(self, client):
        run = _base_run()
        resp = await self._import(client, {
            "format_version": 1, "digest_version": DIGEST_VERSION,
            "integrity_digest": compute_run_digest(run),
            "run": run.model_dump()})
        assert resp.status_code == 200
        assert "matches the checksum" in resp.text

    async def test_tampered_import_reports_mismatch(self, client):
        run = _base_run()
        digest_of_loss = compute_run_digest(run)
        forged = run.model_dump()
        forged["win"] = True  # the forgery the old digest could not see
        resp = await self._import(client, {
            "format_version": 1, "digest_version": DIGEST_VERSION,
            "integrity_digest": digest_of_loss, "run": forged})
        assert resp.status_code == 200
        assert "does not match the checksum" in resp.text

    async def test_digestless_import_reports_absent(self, client):
        resp = await self._import(client, {
            "format_version": 1, "run": _base_run().model_dump()})
        assert resp.status_code == 200
        assert "no checksum" in resp.text
