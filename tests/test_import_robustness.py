"""Valid-but-wrong input must degrade, never 500 — and never persist.

json.loads succeeding is not validation: a top-level array, an Infinity
counter, or an impossible wins>total pair are all valid JSON. Each case here
either broke application import, returned a 500, or silently persisted
corrupt state before the guards existed.
"""
import json
import os

import pytest

# ---------------------------------------------------------------------------
# Shape guards: top-level JSON type other than the expected object
# ---------------------------------------------------------------------------

class TestNonObjectJson:
    def test_get_language_survives_array_settings(self, tmp_path, monkeypatch):
        """settings.json=[] used to raise during application import."""
        import sts2.i18n as i18n
        path = tmp_path / "settings.json"
        path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(i18n, "_settings_path", lambda: path)
        monkeypatch.delenv("STS2_LANG", raising=False)
        assert i18n.get_language() == "en"

    def test_set_language_replaces_array_settings(self, tmp_path, monkeypatch):
        """settings.json=[] made the language POST a TypeError 500."""
        import sts2.i18n as i18n
        path = tmp_path / "settings.json"
        path.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(i18n, "_settings_path", lambda: path)
        assert i18n.set_language("en") is True
        assert json.loads(path.read_text(encoding="utf-8"))["language"] == "en"

    def test_knowledge_base_survives_array_community_json(self, tmp_path, monkeypatch):
        """community.json=[] used to break KnowledgeBase construction."""
        import sts2.knowledge as knowledge
        bad = tmp_path / "community.json"
        bad.write_text("[]", encoding="utf-8")
        kb = knowledge.KnowledgeBase.__new__(knowledge.KnowledgeBase)
        kb.community_tips = {}
        kb.meta_posts = []
        monkeypatch.setattr(knowledge, "DATA_DIR", tmp_path)
        kb._load_community_data()
        assert kb.community_tips == {}
        assert kb.meta_posts == []

    def test_load_hypotheses_rejects_array(self, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        (tmp_path / "hypotheses.json").write_text("[1, 2]", encoding="utf-8")
        from sts2.hypothesis import load_hypotheses
        assert load_hypotheses() == {}

    def test_load_aggregate_rejects_array(self, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        (tmp_path / "community_aggregate.json").write_text("[]", encoding="utf-8")
        from sts2.aggregate import load_aggregate
        assert load_aggregate() == {}

    async def test_run_import_rejects_json_array(self, client):
        from sts2.app import generate_csrf_token
        resp = await client.post(
            "/runs/import",
            files={"file": ("run.json", b"[1, 2, 3]", "application/json")},
            data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Aggregate sanitisation: non-finite numbers and impossible counters
# ---------------------------------------------------------------------------

class TestAggregateSanitisation:
    def test_infinity_run_count_raises_value_error_not_overflow(self):
        from sts2.aggregate import merge_aggregate
        imported = json.loads('{"run_count": Infinity}')
        with pytest.raises(ValueError):
            merge_aggregate({}, imported)

    def test_nan_run_count_raises_value_error(self):
        from sts2.aggregate import merge_aggregate
        imported = json.loads('{"run_count": NaN}')
        with pytest.raises(ValueError):
            merge_aggregate({}, imported)

    def test_nested_infinity_counters_are_dropped(self):
        from sts2.aggregate import _sanitise_import
        clean = _sanitise_import(json.loads(
            '{"run_count": 5, "card_win_rates": '
            '{"CARD.X": {"wins": Infinity, "total": 10}}}'))
        assert clean["card_win_rates"].get("CARD.X", {}).get("wins") is None

    def test_wins_cannot_exceed_total(self):
        from sts2.aggregate import _sanitise_import
        clean = _sanitise_import(
            {"run_count": 5,
             "character_stats": {"Ironclad": {"wins": 99, "total": 10}}})
        assert clean["character_stats"]["Ironclad"]["wins"] == 10

    def test_picked_cannot_exceed_offered(self):
        from sts2.aggregate import _sanitise_import
        clean = _sanitise_import(
            {"run_count": 5,
             "card_pick_rates": {"CARD.X": {"picked": 7, "offered": 3}}})
        assert clean["card_pick_rates"]["CARD.X"]["picked"] == 3

    async def test_import_route_returns_400_for_infinity(self, client):
        from sts2.app import generate_csrf_token
        body = b'{"run_count": Infinity}'
        resp = await client.post(
            "/api/import/stats",
            files={"file": ("stats.json", body, "application/json")},
            data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 400

    async def test_import_route_reports_persistence_failure(self, client, monkeypatch):
        """A skipped write must not be reported as success."""
        import sts2.routes as routes  # noqa: F401  (patch target is aggregate)
        monkeypatch.setattr("sts2.aggregate.save_aggregate", lambda data: False)
        from sts2.app import generate_csrf_token
        body = json.dumps({"run_count": 3}).encode()
        resp = await client.post(
            "/api/import/stats",
            files={"file": ("stats.json", body, "application/json")},
            data={"csrf_token": generate_csrf_token()})
        assert resp.status_code == 500

    def test_save_aggregate_refuses_non_finite(self, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        from sts2.aggregate import save_aggregate
        assert save_aggregate({"run_count": float("inf")}) is False
        assert not (tmp_path / "community_aggregate.json").exists()

    def test_save_aggregate_reports_size_skip(self, tmp_path, monkeypatch):
        import sts2.config as cfg
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path)
        from sts2.aggregate import save_aggregate
        huge = {"run_count": 1, "card_win_rates": {
            f"CARD.{i}": {"wins": 1, "total": 1} for i in range(200_000)}}
        assert save_aggregate(huge) is False


# ---------------------------------------------------------------------------
# Body size limit: enforced before parsing, not after
# ---------------------------------------------------------------------------

class TestBodySizeLimit:
    async def test_declared_oversize_body_is_rejected(self, client):
        resp = await client.post(
            "/deck/analyze", content=b"x",
            headers={"Content-Length": str(50 * 1024 * 1024),
                     "Content-Type": "application/x-www-form-urlencoded"})
        assert resp.status_code == 413

    async def test_streamed_oversize_multipart_file_is_rejected(self):
        """Chunked multipart file upload must be rejected mid-stream.

        No Content-Length header, so the declared-length check cannot fire.
        Two layers may cut this off and either is correct: Starlette >= 1.6
        caps each part at 1 MB (400) before the middleware's 2 MB request
        cap (413) is reached. What must never happen is the old behavior —
        the full body spooling to temp disk before an in-handler check.
        """
        from httpx import ASGITransport, AsyncClient

        from sts2.app import _MAX_REQUEST_BODY_BYTES, app

        boundary = b"testboundary123"

        async def chunks():
            yield (b"--" + boundary + b"\r\n"
                   b'Content-Disposition: form-data; name="file"; '
                   b'filename="r.json"\r\n'
                   b"Content-Type: application/json\r\n\r\n")
            sent = 0
            while sent <= _MAX_REQUEST_BODY_BYTES:
                yield b"x" * 65536
                sent += 65536
            yield b"\r\n--" + boundary + b"--\r\n"

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test",
                               headers={"X-Auth-Token": os.environ["STS2_AUTH_TOKEN"]}) as c:
            resp = await c.post(
                "/runs/import", content=chunks(),
                headers={"Content-Type":
                         "multipart/form-data; boundary=testboundary123"})
        assert resp.status_code in (400, 413)

    async def test_counting_path_cuts_off_undeclared_stream(self):
        """Unit test of the middleware itself: a body-reading app behind it
        never receives more than the cap from a chunked request."""
        from sts2.app import BodySizeLimitMiddleware

        async def body_reader(scope, receive, send):
            while True:
                message = await receive()
                if not message.get("more_body"):
                    break
            await send({"type": "http.response.start", "status": 200,
                        "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = BodySizeLimitMiddleware(body_reader, max_bytes=1000)
        sent_messages = []

        async def receive():
            return {"type": "http.request", "body": b"x" * 600,
                    "more_body": True}

        async def send(message):
            sent_messages.append(message)

        await app({"type": "http", "headers": []}, receive, send)
        assert sent_messages[0]["status"] == 413

    async def test_normal_sized_form_still_works(self, client):
        from sts2.app import generate_csrf_token
        resp = await client.post(
            "/deck/analyze",
            data={"csrf_token": generate_csrf_token(),
                  "card_ids": ["CARD.STRIKE"]})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Atomic persistence helper
# ---------------------------------------------------------------------------

class TestPersistHelper:
    def test_write_json_atomic_round_trip(self, tmp_path):
        from sts2.persist import write_json_atomic
        path = tmp_path / "state.json"
        assert write_json_atomic(path, {"a": 1}) is True
        assert json.loads(path.read_text(encoding="utf-8")) == {"a": 1}
        assert not path.with_suffix(".json.tmp").exists()

    def test_write_json_atomic_refuses_non_finite(self, tmp_path):
        from sts2.persist import write_json_atomic
        path = tmp_path / "state.json"
        assert write_json_atomic(path, {"x": float("nan")}) is False
        assert not path.exists()

    def test_failed_write_leaves_previous_file_intact(self, tmp_path, monkeypatch):
        from sts2 import persist
        path = tmp_path / "state.json"
        persist.write_json_atomic(path, {"kept": True})

        def boom(*args, **kwargs):
            raise OSError("disk full")

        monkeypatch.setattr(persist.os, "fsync", boom)
        assert persist.write_json_atomic(path, {"clobbered": True}) is False
        assert json.loads(path.read_text(encoding="utf-8")) == {"kept": True}
