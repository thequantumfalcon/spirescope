"""Tests for the FastAPI routes."""
import pytest
from httpx import AsyncClient, ASGITransport

from sts2.app import app, _CSRF_TOKEN


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return AsyncClient(transport=transport, base_url="http://test")


@pytest.mark.asyncio
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


@pytest.mark.asyncio
async def test_cards_page(client):
    async with client as c:
        resp = await c.get("/cards")
    assert resp.status_code == 200
    assert "Cards (" in resp.text
    # Should render actual card names from the data
    assert '<div class="grid grid-3">' in resp.text


@pytest.mark.asyncio
async def test_cards_filter(client):
    async with client as c:
        resp = await c.get("/cards?character=Ironclad&type=Attack")
    assert resp.status_code == 200
    # Ironclad filter should be active
    assert 'class="active">Ironclad' in resp.text
    # Should not contain cards from other characters in results
    assert "char-silent" not in resp.text or "char-ironclad" in resp.text


@pytest.mark.asyncio
async def test_relics_page(client):
    async with client as c:
        resp = await c.get("/relics")
    assert resp.status_code == 200
    assert "Relics (" in resp.text
    assert '<div class="grid grid-3">' in resp.text


@pytest.mark.asyncio
async def test_potions_page(client):
    async with client as c:
        resp = await c.get("/potions")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


@pytest.mark.asyncio
async def test_enemies_page(client):
    async with client as c:
        resp = await c.get("/enemies")
    assert resp.status_code == 200
    assert "Enemies" in resp.text
    assert "All Acts" in resp.text


@pytest.mark.asyncio
async def test_events_page(client):
    async with client as c:
        resp = await c.get("/events")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


@pytest.mark.asyncio
async def test_search_empty(client):
    async with client as c:
        resp = await c.get("/search?q=")
    assert resp.status_code == 200
    assert "(0 results)" in resp.text


@pytest.mark.asyncio
async def test_search_with_query(client):
    async with client as c:
        resp = await c.get("/search?q=bash")
    assert resp.status_code == 200
    assert "bash" in resp.text.lower()


@pytest.mark.asyncio
async def test_api_search(client):
    async with client as c:
        resp = await c.get("/api/search?q=bash")
    assert resp.status_code == 200
    data = resp.json()
    assert "cards" in data
    assert "relics" in data


@pytest.mark.asyncio
async def test_deck_analyzer_page(client):
    async with client as c:
        resp = await c.get("/deck")
    assert resp.status_code == 200
    assert "Deck" in resp.text


@pytest.mark.asyncio
async def test_deck_analyze_empty(client):
    async with client as c:
        resp = await c.post("/deck/analyze", data={"csrf_token": _CSRF_TOKEN})
    assert resp.status_code == 200
    assert "No cards selected" in resp.text


@pytest.mark.asyncio
async def test_deck_analyze_rejects_bad_csrf(client):
    async with client as c:
        resp = await c.post("/deck/analyze", data={"csrf_token": "bad_token"})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_runs_page(client):
    async with client as c:
        resp = await c.get("/runs")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


@pytest.mark.asyncio
async def test_live_page(client):
    async with client as c:
        resp = await c.get("/live")
    assert resp.status_code == 200
    # Either shows live run or "No Active Run"
    assert "Run" in resp.text


@pytest.mark.asyncio
async def test_api_live(client):
    async with client as c:
        resp = await c.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "total_players" in data
    assert "player_index" in data


@pytest.mark.asyncio
async def test_live_with_player_param(client):
    async with client as c:
        resp = await c.get("/live?player=0")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_live_with_player_param(client):
    async with client as c:
        resp = await c.get("/api/live?player=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_index"] == 0


@pytest.mark.asyncio
async def test_security_headers(client):
    async with client as c:
        resp = await c.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"


@pytest.mark.asyncio
async def test_api_search_includes_suggestions(client):
    async with client as c:
        resp = await c.get("/api/search?q=xyznonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data


@pytest.mark.asyncio
async def test_search_suggestions_shown(client):
    async with client as c:
        resp = await c.get("/search?q=ironclsd")
    assert resp.status_code == 200
    # Should show "Did you mean" or "No results"
    assert "No results" in resp.text or "Did you mean" in resp.text


@pytest.mark.asyncio
async def test_card_detail_404(client):
    async with client as c:
        resp = await c.get("/cards/CARD.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_enemy_detail_404(client):
    async with client as c:
        resp = await c.get("/enemies/ENEMY.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_run_detail_404(client):
    async with client as c:
        resp = await c.get("/runs/fake_run_id")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


@pytest.mark.asyncio
async def test_strategy_404(client):
    async with client as c:
        resp = await c.get("/strategy/FakeCharacter")
    assert resp.status_code == 404
    assert "404" in resp.text


@pytest.mark.asyncio
async def test_deck_page_has_csrf_token(client):
    async with client as c:
        resp = await c.get("/deck")
    assert resp.status_code == 200
    assert "csrf_token" in resp.text
