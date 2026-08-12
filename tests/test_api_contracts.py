"""Tests for the /health, /ready and /api/* JSON contracts (audit M12).

Covers: liveness/readiness split, standardized JSON error envelope on
/api/* handlers (instead of the HTML error page the app-wide exception
handler renders elsewhere), and the schema_version / response_model
additions to the versioned public contracts.
"""
from sts2.config import VERSION


async def test_health_always_200_even_with_empty_kb(client):
    """/health is pure liveness: 200 always, no data-readiness check."""
    from unittest.mock import MagicMock, patch

    with patch("sts2.app.kb", MagicMock(cards=[])):
        resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["cards"] == 0


async def test_ready_with_cards_loaded(client):
    """/ready returns 200 with the card count and app version once the
    knowledge base actually has usable data (the real test kb does)."""
    resp = await client.get("/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ready"
    assert data["cards"] > 0
    assert data["version"] == VERSION


async def test_ready_503_when_kb_has_no_cards(client):
    """/ready returns 503 when the knowledge base has no card data — the
    scenario /health used to paper over by always saying "ok"."""
    from unittest.mock import MagicMock, patch

    with patch("sts2.app.kb", MagicMock(cards=[])):
        resp = await client.get("/ready")
    assert resp.status_code == 503
    data = resp.json()
    assert data["status"] == "not_ready"
    assert "reason" in data


async def test_api_card_404_is_json_error_shape(client):
    """GET /api/cards/<unknown> returns the standardized JSON error envelope,
    not the HTML error page the app-wide exception handler renders."""
    resp = await client.get("/api/cards/CARD.DOES_NOT_EXIST_XYZ")
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["error"] == "Card not found."
    assert data["status"] == 404
    assert data["card_id"] == "CARD.DOES_NOT_EXIST_XYZ"


async def test_api_reload_bad_token_is_json_error_shape(client):
    """POST /api/reload with a bad admin token returns the JSON error shape."""
    resp = await client.post("/api/reload", headers={"X-Admin-Token": "bad_token"})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["error"] == "Unauthorized."
    assert data["status"] == 403


async def test_api_reset_stats_no_token_is_json_error_shape(client):
    """POST /api/reset/stats without a token returns the JSON error shape."""
    resp = await client.post("/api/reset/stats")
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["error"] == "Unauthorized."
    assert data["status"] == 403


async def test_api_import_stats_bad_csrf_is_json_error_shape(client):
    """POST /api/import/stats with a bad CSRF token returns the JSON error shape."""
    import json as _json

    body = _json.dumps({"run_count": 1, "character_stats": {}}).encode()
    resp = await client.post("/api/import/stats",
                             files={"file": ("s.json", body, "application/json")},
                             data={"csrf_token": "bogus"})
    assert resp.status_code == 403
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert data["error"] == "Invalid CSRF token."
    assert data["status"] == 403


async def test_api_live_stream_cap_is_json_error_shape(client):
    """GET /api/live/stream at the connection cap returns the JSON error
    shape (still containing "Too many" so the pre-existing HTML/text
    assertion in test_app.py keeps passing against the same substring)."""
    import sts2.routes as routes_mod

    original = routes_mod._sse_active
    try:
        routes_mod._sse_active = 10
        resp = await client.get("/api/live/stream")
    finally:
        routes_mod._sse_active = original
    assert resp.status_code == 429
    assert resp.headers["content-type"].startswith("application/json")
    data = resp.json()
    assert "Too many" in data["error"]
    assert data["status"] == 429


async def test_api_live_matches_current_run_shape(client):
    """/api/live is typed response_model=CurrentRun; the payload must still
    validate as one (byte-compatible with the pre-existing shape)."""
    from sts2.models import CurrentRun

    resp = await client.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    CurrentRun(**data)  # raises if the shape drifted from CurrentRun
    assert "active" in data
    assert "player_index" in data
    assert "total_players" in data


async def test_api_analytics_has_schema_version(client):
    resp = await client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == 1
    assert "overview" in data


async def test_api_runs_has_schema_version(client):
    resp = await client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == 1
    assert "runs" in data
    assert "total" in data


async def test_api_export_stats_has_schema_version(client):
    resp = await client.get("/api/export/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["schema_version"] == 1
    assert "run_count" in data


class TestErrorEnvelopeIsUniform:
    """Hand-written /api errors used the envelope, but anything raised past
    them fell through to the HTML error page — a JSON client parsing a
    failure got a document instead."""

    async def test_unknown_api_path_returns_json(self, client):
        resp = await client.get("/api/no-such-endpoint")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("application/json")
        assert resp.json()["status"] == 404
        assert "error" in resp.json()

    async def test_request_validation_error_returns_json_envelope(self, client):
        # ascension is validated 0..20 by the route signature.
        resp = await client.get("/api/analytics?ascension=999")
        assert resp.status_code == 422
        assert resp.headers["content-type"].startswith("application/json")
        body = resp.json()
        assert body["status"] == 422 and "error" in body

    async def test_page_routes_still_render_html_errors(self, client):
        resp = await client.get("/no-such-page")
        assert resp.status_code == 404
        assert resp.headers["content-type"].startswith("text/html")
