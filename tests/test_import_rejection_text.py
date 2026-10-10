"""The stats-import route takes its rejection text from a fixed table.

It returned str(exc) for DuplicateImportError and AggregateImportError. Every
raise site used a literal message, so nothing leaked, but that rested on a
docstring alone and CodeQL reported the flow (py/stack-trace-exposure). The
messages and status codes the user sees are unchanged.
"""
import json

import pytest

from sts2 import aggregate
from sts2.app import generate_csrf_token

PRIVATE = r"C:\Users\someone-private\AppData\Roaming\SpireScope\community_aggregate.json"


async def _post(client, payload):
    return await client.post(
        "/api/import/stats",
        files={"file": ("stats.json", json.dumps(payload).encode(), "application/json")},
        data={"csrf_token": generate_csrf_token()})


@pytest.fixture
def private_state(tmp_path, monkeypatch):
    monkeypatch.setattr("sts2.config.STATE_DIR", tmp_path)
    return tmp_path


async def test_rejection_text_never_comes_from_the_exception(client, private_state,
                                                             monkeypatch):
    class Leaky(aggregate.AggregateImportError):
        def __str__(self):
            return PRIVATE

    def reject(imported):
        raise Leaky("ledger_full")

    monkeypatch.setattr("sts2.aggregate.import_aggregate", reject)
    resp = await _post(client, {"run_count": 1})

    assert resp.status_code == 400
    assert "someone-private" not in resp.text
    assert resp.json()["error"] == ("Import ledger is full. Export a backup before "
                                    "resetting community statistics.")


async def test_duplicate_text_never_comes_from_the_exception(client, private_state,
                                                             monkeypatch):
    class Leaky(aggregate.DuplicateImportError):
        def __str__(self):
            return PRIVATE

    def reject(imported):
        raise Leaky()

    monkeypatch.setattr("sts2.aggregate.import_aggregate", reject)
    resp = await _post(client, {"run_count": 1})

    assert resp.status_code == 409
    assert "someone-private" not in resp.text
    assert resp.json()["error"] == "This aggregate file has already been imported."


@pytest.mark.parametrize("payload, message", [
    ({"run_count": -1}, "run_count must be a nonnegative whole number"),
    ({"run_count": 1, "card_win_rates": []}, "Invalid aggregate counter family."),
    ({"run_count": 1, "character_stats": {"Ironclad": {"total": 1}}},
     "Invalid aggregate entry: both finite counters are required."),
    ({"run_count": 1, "card_win_rates": {"CARD.X": {"wins": 2, "total": 1}}},
     "Invalid aggregate file: an entry records more wins than runs."),
    ({"run_count": 1, "card_win_rates": {"CARD.X": {"wins": 0, "total": 2}}},
     "Invalid aggregate file: an entry appears in more runs than the file's run_count."),
    ({"run_count": 1, "character_stats": {"Ironclad": {"wins": 0, "total": 1},
                                          "Silent": {"wins": 0, "total": 1}}},
     "Invalid aggregate file: character or ascension totals add up to more runs than "
     "the file's run_count."),
    ({"run_count": 1, "card_pick_rates": {"CARD.X": {"picked": 501, "offered": 600}}},
     "Invalid aggregate file: pick counts are impossible for the file's run_count."),
])
async def test_each_rejection_keeps_its_message(client, private_state, payload, message):
    resp = await _post(client, payload)
    assert resp.status_code == 400
    assert resp.json()["error"] == message


async def test_a_repeated_import_keeps_its_message_and_status(client, private_state):
    assert (await _post(client, {"run_count": 3})).status_code == 200
    resp = await _post(client, {"run_count": 3})
    assert resp.status_code == 409
    assert resp.json()["error"] == "This aggregate file has already been imported."


def test_str_of_the_exception_is_still_the_message_for_logs():
    exc = aggregate.AggregateImportError("ledger_full")
    assert exc.reason == "ledger_full"
    assert str(exc) == aggregate.IMPORT_REJECTIONS["ledger_full"]
    assert str(aggregate.DuplicateImportError()) == ("This aggregate file has already "
                                                     "been imported.")
