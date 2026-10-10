"""Search runs in a worker thread, not on the event loop.

A query with no match falls through to KnowledgeBase.suggest, a pure-Python
edit distance over every entity name. On the event loop that CPU work
stalled every other request and the live streams with it.
"""
import threading

import pytest

from sts2 import app as app_module


@pytest.fixture
def search_threads(monkeypatch):
    """Record the thread every KnowledgeBase.search call runs on."""
    threads = []
    real_search = app_module.kb.search

    def recording_search(query, *args, **kwargs):
        threads.append(threading.get_ident())
        return real_search(query, *args, **kwargs)

    monkeypatch.setattr(app_module.kb, "search", recording_search)
    return threads


@pytest.mark.parametrize("path", ["/search", "/api/search"])
async def test_search_does_not_run_on_the_event_loop(client, search_threads, path):
    loop_thread = threading.get_ident()
    resp = await client.get(path, params={"q": "zzqxv wibblethorpe frobnicate"})
    assert resp.status_code == 200
    assert len(search_threads) == 1
    assert search_threads[0] != loop_thread


async def test_search_results_are_unchanged(client, search_threads):
    """Moving the call must not change what it returns."""
    resp = await client.get("/api/search", params={"q": "bash"})
    assert resp.status_code == 200
    assert any(card["id"] == "CARD.BASH" for card in resp.json()["cards"])

    resp = await client.get("/api/search", params={"q": "bassh"})
    assert resp.status_code == 200
    assert "Bash" in resp.json()["suggestions"]
