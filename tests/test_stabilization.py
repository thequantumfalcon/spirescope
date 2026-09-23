"""Stateful regressions for the independently verified release blockers."""
import asyncio
import json
import os
import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from sts2.app import generate_csrf_token
from sts2.data_health import FAMILIES, inspect_dataset
from sts2.logparser import LogTailer


@pytest.fixture
def dataset(tmp_path):
    target = tmp_path / "data"
    shutil.copytree(Path(__file__).parents[1] / "sts2/data", target)
    return target


@pytest.mark.parametrize("family", list(FAMILIES))
def test_every_required_family_rejected_when_empty(dataset, family):
    (dataset / (family + ".json")).write_text("[]")
    report = inspect_dataset(dataset)
    assert not report["ok"]
    assert any(family + ".json" in e for e in report["errors"])


def test_duplicate_identity_rejected(dataset):
    cards = json.loads((dataset / "cards.json").read_text(encoding="utf-8"))
    cards.append(cards[0])
    (dataset / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    assert not inspect_dataset(dataset)["ok"]


def test_validator_isolated_from_personal_state(dataset, tmp_path):
    personal = tmp_path / "personal"
    personal.mkdir()
    sentinel = personal / "settings.json"
    sentinel.write_text('{"sentinel":true}')
    env = {**os.environ, "STS2_STATE_DIR": str(personal), "STS2_SAVE_DIR": str(personal),
           "STS2_GAME_DIR": str(personal), "STS2_MODS_DIR": str(personal)}
    result = subprocess.run([sys.executable, "-m", "sts2", "validate-data", str(dataset)],
                            env=env, capture_output=True, text=True, timeout=30)
    assert result.returncode == 0, result.stderr + result.stdout
    assert json.loads(result.stdout.splitlines()[-1])["ok"]
    assert list(personal.iterdir()) == [sentinel]
    assert sentinel.read_text() == '{"sentinel":true}'


def _sources(monkeypatch, dataset, *, missing="", changed=False):
    from sts2 import fetcher, sources
    monkeypatch.setattr(fetcher, "DATA_DIR", dataset)
    monkeypatch.setattr(fetcher, "_SCRAPE_DELAY", 0)
    for family in ("enemies", "events", "badges"):
        monkeypatch.setattr(fetcher, "_discover_" + family + "_from_saves", lambda: [])

    class Source:
        name = "fixture"

        def fetch_cards(self):
            cards = json.loads((dataset / "cards.json").read_text(encoding="utf-8"))
            if changed:
                cards[0]["description"] = "Gain 17 Block."
            return [] if missing == "cards" else cards

        def fetch_relics(self):
            return [] if missing == "relics" else json.loads((dataset / "relics.json").read_text(encoding="utf-8"))

        def fetch_potions(self):
            return [] if missing == "potions" else json.loads((dataset / "potions.json").read_text(encoding="utf-8"))

    monkeypatch.setattr(sources, "Sts2ggSource", Source)
    monkeypatch.setattr(sources, "WikiggSource", Source)


def test_partial_refresh_preserves_every_live_byte(dataset, monkeypatch):
    from sts2.fetcher import run_fetcher
    before = {p.name: p.read_bytes() for p in dataset.glob("*") if p.is_file()}
    _sources(monkeypatch, dataset, missing="potions", changed=True)
    with pytest.raises(ValueError, match="Refresh incomplete"):
        run_fetcher()
    assert before == {p.name: p.read_bytes() for p in dataset.glob("*") if p.is_file()}
    assert json.loads(dataset.with_name("data.refresh.json").read_text())["installed"] is False


def test_successful_refresh_and_save_scan_do_not_advance_bundle_date(dataset, monkeypatch):
    from sts2.fetcher import run_fetcher
    stamp = (dataset / "last_updated.txt").read_bytes()
    _sources(monkeypatch, dataset, changed=True)
    assert run_fetcher()["installed"]
    assert (dataset / "last_updated.txt").read_bytes() == stamp
    assert not run_fetcher(save_only=True)["installed"]
    assert (dataset / "last_updated.txt").read_bytes() == stamp
    assert inspect_dataset(dataset.with_name("data.backup"))["ok"]


def test_explicit_zero_false_and_clear_survive_merge(dataset, monkeypatch):
    from sts2 import fetcher
    monkeypatch.setattr(fetcher, "DATA_DIR", dataset)
    rows = [{"id": "CARD.TEST", "name": "Test", "star_cost": "2",
             "cost_upgraded": "1", "mp_only": True, "description": "Gain Block."}]
    (dataset / "cards.json").write_text(json.dumps(rows))
    merged = fetcher._merge_with_existing("cards.json", [{"id": "CARD.TEST", "star_cost": "",
        "cost_upgraded": "0", "mp_only": False}])
    assert merged[0]["star_cost"] == ""
    assert merged[0]["cost_upgraded"] == "0"
    assert merged[0]["mp_only"] is False
    assert merged[0]["description"] == "Gain Block."


def test_rsc_all_real_string_boundaries_and_braces():
    from sts2.fetcher import _extract_json_objects
    record = {"category": "CARD", "id": "example", "description": 'Draw {Cards} cards. "Test" é.'}
    raw = json.dumps(record, ensure_ascii=False)
    for split in range(len(raw)):
        html = "".join("self.__next_f.push([1," + json.dumps(chunk) + "])" for chunk in (raw[:split], raw[split:]))
        assert _extract_json_objects(html, "CARD") == [record]


def test_log_partial_line_and_replacement(tmp_path):
    path = tmp_path / "godot.log"
    ready = b"[INFO] [StartRunLobby (1)] Local player 1 is ready\n"
    play = b"[INFO] Player 1 playing card BASH\n"
    path.write_bytes(ready)
    tail = LogTailer(path)
    assert tail.poll()["active"]
    for byte in play[:-1]:
        with path.open("ab") as stream:
            stream.write(bytes([byte]))
        assert tail.poll() is None
    with path.open("ab") as stream:
        stream.write(play[-1:])
    assert tail.poll()["cards_played"] == ["CARD.BASH"]
    assert tail.poll() is None
    replacement = tmp_path / "new.log"
    replacement.write_bytes(b" " * path.stat().st_size)
    replacement.replace(path)
    assert tail.poll()["active"] is False
    assert tail.state.cards_played_by_player == {}


def test_aggregate_parallel_retries_commit_once(tmp_path, monkeypatch):
    from sts2.aggregate import DuplicateImportError, import_aggregate, load_aggregate
    monkeypatch.setattr("sts2.config.STATE_DIR", tmp_path)
    contribution = {"run_count": 2, "character_stats": {"Ironclad": {"total": 2, "wins": 1}}}

    def submit():
        try:
            import_aggregate(contribution)
            return "accepted"
        except DuplicateImportError:
            return "duplicate"

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(lambda _: submit(), range(4)))
    assert results.count("accepted") == 1
    assert load_aggregate()["run_count"] == 2
    assert len(load_aggregate()["import_digests"]) == 1


async def test_deck_copy_metadata_roundtrip(client):
    instances = [{"card_id": "CARD.BARRICADE", "upgrade_level": 0, "enchantment": ""},
                 {"card_id": "CARD.BARRICADE", "upgrade_level": 1, "enchantment": "ENCHANTMENT.TEST"}]
    response = await client.post("/deck/analyze", data={"csrf_token": generate_csrf_token(), "instances": json.dumps(instances)})
    assert response.status_code == 200
    import html
    import re
    value = re.search('id="deck-instances"[^>]*value=\'(.*?)\'', response.text).group(1)
    assert json.loads(html.unescape(value)) == instances
    assert "enchantment effects that are not modeled" in response.text


async def test_file_card_ids_rejected(client):
    response = await client.post("/deck/analyze", data={"csrf_token": generate_csrf_token()}, files={"card_ids": ("card.txt", b"CARD.BASH")})
    assert response.status_code == 400


async def test_connectivity_singleflight(monkeypatch):
    from sts2 import app, routes, spectral
    calls = []
    original = spectral.deck_spectral_health

    def compute(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)

    routes._spectral_cache.clear()
    monkeypatch.setattr(spectral, "deck_spectral_health", compute)
    results = await asyncio.gather(*(routes._deck_spectral_health_cached(["CARD.BASH"] * 3, app.kb) for _ in range(4)))
    assert len(calls) == 1
    assert all(result == results[0] for result in results)


@pytest.mark.parametrize("entry", [{"total": 1}, {"wins": 0}, {"wins": "0", "total": 1}])
async def test_incomplete_aggregate_never_persists(client, tmp_path, monkeypatch, entry):
    monkeypatch.setattr("sts2.config.STATE_DIR", tmp_path)
    response = await client.post("/api/import/stats",
        data={"csrf_token": generate_csrf_token()},
        files={"file": ("stats.json", json.dumps({"run_count": 1, "character_stats": {"Ironclad": entry}}))})
    assert response.status_code == 400
    assert not (tmp_path / "community_aggregate.json").exists()


@pytest.mark.parametrize("authority", ["[::1]junk", "[::1]:bad", "[::1]:999999", "test:wrong", "test/path"])
async def test_malformed_authority_rejected(client, authority):
    response = await client.get("/health", headers={"host": authority})
    assert response.status_code == 400


async def test_ipv6_authority_with_port(client, monkeypatch):
    monkeypatch.setenv("STS2_ALLOWED_HOSTS", "::1")
    response = await client.get("/health", headers={"host": "[::1]:8000"})
    assert response.status_code == 200


def test_aggregate_retry_across_processes(tmp_path, monkeypatch):
    from sts2.aggregate import load_aggregate
    monkeypatch.setattr("sts2.config.STATE_DIR", tmp_path)
    env = {**os.environ, "STS2_STATE_DIR": str(tmp_path)}
    code = "from sts2.aggregate import import_aggregate, DuplicateImportError\ntry:\n import_aggregate({'run_count': 3}); print('accepted')\nexcept DuplicateImportError:\n print('duplicate')"
    processes = [subprocess.Popen([sys.executable, "-c", code], env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(4)]
    outputs = []
    for process in processes:
        out, err = process.communicate(timeout=30)
        assert process.returncode == 0, err
        outputs.append(out.strip())
    assert outputs.count("accepted") == 1
    assert outputs.count("duplicate") == 3
    assert load_aggregate()["run_count"] == 3


@pytest.mark.parametrize("size", [3, 30, 100])
def test_graph_solver_against_analytic_path_spectrum(size):
    import math

    from sts2.spectral import _compute_components
    matrix = [[0.0] * size for _ in range(size)]
    for i in range(size - 1):
        matrix[i][i] += 1
        matrix[i + 1][i + 1] += 1
        matrix[i][i + 1] = matrix[i + 1][i] = -1
    original = [row[:] for row in matrix]
    actual = sorted(_compute_components(matrix, max_iter=size * size * 10))
    expected = [2 - 2 * math.cos(k * math.pi / size) for k in range(size)]
    assert actual == pytest.approx(expected, abs=1e-7)
    assert matrix == original


def test_live_native_upgrade_level_retains_boolean_contract(tmp_path, monkeypatch):
    from sts2 import saves
    monkeypatch.setattr(saves, "SAVE_DIR", tmp_path)
    (tmp_path / "current_run.save").write_text(json.dumps({"players": [{
        "character_id": "CHARACTER.IRONCLAD", "deck": [
            {"id": "CARD.BASH", "current_upgrade_level": 2, "upgrade_count": 0},
            {"id": "CARD.BASH", "upgrade_count": 1},
            {"id": "CARD.BASH", "current_upgrade_level": "invalid"}]}]}))
    assert saves.get_current_run().deck_upgrades == [True, True, False]


def test_same_seed_new_embark_clears_previous_telemetry(tmp_path):
    tail = LogTailer(log_path=tmp_path / "log")
    embark = "[INFO] Embarking on a singleplayer IRONCLAD run. Ascension: 1 Seed: REPLAY"
    tail._process_line(embark)
    tail._process_line("[INFO] Player 1 playing card BASH")
    assert tail.state.cards_played_by_player
    tail._process_line(embark)
    assert tail.state.seed == "REPLAY"
    assert not tail.state.cards_played_by_player


def test_badges_only_discovery_commits_without_timestamp_advance(dataset, monkeypatch):
    from sts2 import fetcher
    _sources(monkeypatch, dataset)
    stamp = (dataset / "last_updated.txt").read_bytes()
    monkeypatch.setattr(fetcher, "_discover_badges_from_saves", lambda: [
        {"id": "BADGE.QUALIFICATION", "name": "Fixture", "requirement": "fixture"}])
    assert fetcher.run_fetcher(save_only=True)["installed"]
    assert any(row["id"] == "BADGE.QUALIFICATION" for row in json.loads((dataset / "badges.json").read_text()))
    assert (dataset / "last_updated.txt").read_bytes() == stamp


@pytest.mark.parametrize("left,right", [({"branch": "main"}, {"branch": "beta"}),
    ({"last_changed": "v0.110.0"}, {"last_changed": "v0.111.0"})])
def test_known_incompatible_sources_reject(left, right):
    from sts2.fetcher import _check_source_compatibility
    with pytest.raises(ValueError, match="Conflicting source"):
        _check_source_compatibility({"id": "CARD.TEST", **left}, right)


def test_incompatible_installed_branch_is_not_overwritten(dataset, monkeypatch):
    from sts2 import fetcher
    monkeypatch.setattr(fetcher, "DATA_DIR", dataset)
    path = dataset / "cards.json"
    path.write_text(json.dumps([{"id": "CARD.TEST", "branch": "beta", "cost": "1"}]))
    with pytest.raises(ValueError, match="branches"):
        fetcher._merge_with_existing("cards.json", [{"id": "CARD.TEST", "branch": "main", "cost": "2"}])
    assert json.loads(path.read_text())[0]["cost"] == "1"


def test_malformed_hypothesis_conditions_do_not_break_evaluation(tmp_path, monkeypatch):
    from sts2 import hypothesis
    monkeypatch.setattr(hypothesis, "_hypotheses_file", lambda: tmp_path / "hypotheses.json")
    (tmp_path / "hypotheses.json").write_text(json.dumps({
        "missing": {}, "params": {"condition_type": "character", "params": []},
        "size": {"condition_type": "deck_size", "params": {"max_size": "many"}},
        "good": {"condition_type": "character", "params": {"character": "Ironclad"}}}))
    assert set(hypothesis.load_hypotheses()) == {"good"}
