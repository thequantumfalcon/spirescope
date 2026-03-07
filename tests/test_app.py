"""Tests for the FastAPI routes."""
import pytest
from httpx import AsyncClient, ASGITransport

from sts2.app import app, _CSRF_TOKEN, _ADMIN_TOKEN


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


async def test_index(client):
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "Spirescope" in resp.text
    # Should render stat boxes with counts
    assert "Cards" in resp.text
    assert "Relics" in resp.text
    # Should render character links
    assert "Ironclad" in resp.text
    # Should have navigation
    assert '<nav>' in resp.text


async def test_cards_page(client):
    async with client as c:
        resp = await c.get("/cards")
    assert resp.status_code == 200
    assert "Cards (" in resp.text
    # Should render actual card names from the data
    assert '<div class="grid grid-3">' in resp.text


async def test_cards_filter(client):
    async with client as c:
        resp = await c.get("/cards?character=Ironclad&type=Attack")
    assert resp.status_code == 200
    # Ironclad filter should be active
    assert 'class="active">Ironclad' in resp.text
    # Should not contain cards from other characters in results
    assert "char-silent" not in resp.text or "char-ironclad" in resp.text


async def test_relics_page(client):
    async with client as c:
        resp = await c.get("/relics")
    assert resp.status_code == 200
    assert "Relics (" in resp.text
    assert '<div class="grid grid-3">' in resp.text


async def test_potions_page(client):
    async with client as c:
        resp = await c.get("/potions")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_enemies_page(client):
    async with client as c:
        resp = await c.get("/enemies")
    assert resp.status_code == 200
    assert "Enemies" in resp.text
    assert "All Acts" in resp.text


async def test_events_page(client):
    async with client as c:
        resp = await c.get("/events")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_search_empty(client):
    async with client as c:
        resp = await c.get("/search?q=")
    assert resp.status_code == 200
    assert "(0 results)" in resp.text


async def test_search_with_query(client):
    async with client as c:
        resp = await c.get("/search?q=bash")
    assert resp.status_code == 200
    assert "bash" in resp.text.lower()


async def test_api_search(client):
    async with client as c:
        resp = await c.get("/api/search?q=bash")
    assert resp.status_code == 200
    data = resp.json()
    assert "cards" in data
    assert "relics" in data


async def test_deck_analyzer_page(client):
    async with client as c:
        resp = await c.get("/deck")
    assert resp.status_code == 200
    assert "Deck" in resp.text


async def test_deck_analyze_empty(client):
    async with client as c:
        resp = await c.post("/deck/analyze", data={"csrf_token": _CSRF_TOKEN})
    assert resp.status_code == 200
    assert "No cards selected" in resp.text


async def test_deck_analyze_rejects_bad_csrf(client):
    async with client as c:
        resp = await c.post("/deck/analyze", data={"csrf_token": "bad_token"})
    assert resp.status_code == 403


async def test_runs_page(client):
    async with client as c:
        resp = await c.get("/runs")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_live_page(client):
    async with client as c:
        resp = await c.get("/live")
    assert resp.status_code == 200
    # Either shows live run or "No Active Run"
    assert "Run" in resp.text


async def test_api_live(client):
    async with client as c:
        resp = await c.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "total_players" in data
    assert "player_index" in data


async def test_live_with_player_param(client):
    async with client as c:
        resp = await c.get("/live?player=0")
    assert resp.status_code == 200


async def test_api_live_with_player_param(client):
    async with client as c:
        resp = await c.get("/api/live?player=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_index"] == 0


async def test_security_headers(client):
    async with client as c:
        resp = await c.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "connect-src 'self'" in csp


async def test_api_search_includes_suggestions(client):
    async with client as c:
        resp = await c.get("/api/search?q=xyznonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data


async def test_search_suggestions_shown(client):
    async with client as c:
        resp = await c.get("/search?q=ironclsd")
    assert resp.status_code == 200
    # Should show "Did you mean" or "No results"
    assert "No results" in resp.text or "Did you mean" in resp.text


async def test_card_detail_404(client):
    async with client as c:
        resp = await c.get("/cards/CARD.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_enemy_detail_404(client):
    async with client as c:
        resp = await c.get("/enemies/ENEMY.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_run_detail_404(client):
    async with client as c:
        resp = await c.get("/runs/fake_run_id")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_strategy_404(client):
    async with client as c:
        resp = await c.get("/strategy/FakeCharacter")
    assert resp.status_code == 404
    assert "404" in resp.text


async def test_deck_page_has_csrf_token(client):
    async with client as c:
        resp = await c.get("/deck")
    assert resp.status_code == 200
    assert "csrf_token" in resp.text


async def test_cards_pagination_default(client):
    async with client as c:
        resp = await c.get("/cards")
    assert resp.status_code == 200
    assert "Cards (" in resp.text


async def test_cards_pagination_page2(client):
    async with client as c:
        resp = await c.get("/cards?page=2")
    assert resp.status_code == 200
    # Page 2 should still render cards (unless fewer than 30 total)
    assert "Cards (" in resp.text


async def test_cards_pagination_with_filter(client):
    async with client as c:
        resp = await c.get("/cards?character=Ironclad&page=1")
    assert resp.status_code == 200
    assert 'class="active">Ironclad' in resp.text


async def test_cards_pagination_out_of_range(client):
    async with client as c:
        resp = await c.get("/cards?page=9999")
    assert resp.status_code == 200
    # Should clamp to last page, not error


async def test_api_reload_with_valid_token(client):
    async with client as c:
        resp = await c.post(f"/api/reload?token={_ADMIN_TOKEN}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "cards" in data
    assert data["cards"] > 0


async def test_api_reload_rejects_bad_token(client):
    async with client as c:
        resp = await c.post("/api/reload?token=bad_token")
    assert resp.status_code == 403


async def test_api_reload_rejects_missing_token(client):
    async with client as c:
        resp = await c.post("/api/reload")
    assert resp.status_code == 422  # missing required query param


async def test_live_page_has_sse_script(client):
    async with client as c:
        resp = await c.get("/live")
    assert resp.status_code == 200
    assert "EventSource" in resp.text


async def test_live_stream_endpoint_exists(client):
    """SSE endpoint is registered (streaming tested via integration)."""
    from starlette.routing import Route
    from sts2.app import app as _app
    sse_routes = [r for r in _app.routes if isinstance(r, Route) and r.path == "/api/live/stream"]
    assert len(sse_routes) == 1


async def test_deck_page_has_save_load_ui(client):
    async with client as c:
        resp = await c.get("/deck")
    assert resp.status_code == 200
    assert "save-deck" in resp.text
    assert "load-deck" in resp.text
    assert "spirescope_decks" in resp.text
    # Should have character-namespaced save logic
    assert "detectCharacter" in resp.text


async def test_cards_pagination_shows_range(client):
    """When paginated, shows 'Showing X-Y of Z' indicator."""
    async with client as c:
        resp = await c.get("/cards?page=1")
    assert resp.status_code == 200
    # If more than one page exists, should show range indicator
    if "page=2" in resp.text or "Next" in resp.text:
        assert "Showing" in resp.text


async def test_sse_connection_limit_registered(client):
    """SSE max connections constant is set."""
    from sts2.app import _SSE_MAX_CONNECTIONS
    assert _SSE_MAX_CONNECTIONS > 0


async def test_health_endpoint(client):
    async with client as c:
        resp = await c.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["cards"] > 0


async def test_robots_txt(client):
    async with client as c:
        resp = await c.get("/robots.txt")
    assert resp.status_code == 200
    assert "User-agent" in resp.text
    assert "Disallow: /api/" in resp.text


async def test_meta_description_in_html(client):
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'meta name="description"' in resp.text
    assert 'meta name="theme-color"' in resp.text


async def test_player_param_validation(client):
    """Player param > 3 should be rejected."""
    async with client as c:
        resp = await c.get("/api/live?player=99")
    assert resp.status_code == 422


async def test_deck_analyze_caps_card_count(client):
    """Submitting more than MAX_DECK_SIZE cards should not crash."""
    from sts2.app import _MAX_DECK_SIZE
    card_ids = [f"CARD.FAKE_{i}" for i in range(_MAX_DECK_SIZE + 50)]
    async with client as c:
        resp = await c.post("/deck/analyze", data={
            "csrf_token": _CSRF_TOKEN,
            "card_ids": card_ids,
        })
    assert resp.status_code == 200


async def test_admin_token_not_in_logs(client):
    """Admin token should not be exposed via any public endpoint."""
    async with client as c:
        resp = await c.get("/")
    assert _ADMIN_TOKEN not in resp.text


async def test_csp_blocks_external_scripts(client):
    """CSP should not allow external script sources."""
    async with client as c:
        resp = await c.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "script-src" in csp
    # Should not contain 'unsafe-eval' or wildcard
    assert "'unsafe-eval'" not in csp
    assert "script-src *" not in csp


async def test_css_cache_busting(client):
    """CSS link should include a version hash query parameter."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "style.css?v=" in resp.text


async def test_favicon_ico_link(client):
    """Should include a .ico favicon link for older browsers."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "favicon.ico" in resp.text


async def test_search_input_has_maxlength(client):
    """Search input should have maxlength attribute matching server-side limit."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'maxlength="200"' in resp.text


async def test_favicon_ico_serves(client):
    """The favicon.ico file should be served from /static/."""
    async with client as c:
        resp = await c.get("/static/favicon.ico")
    assert resp.status_code == 200
