"""Tests for the FastAPI routes."""
import pytest
from httpx import AsyncClient, ASGITransport

from sts2.app import app


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


@pytest.mark.asyncio
async def test_cards_page(client):
    async with client as c:
        resp = await c.get("/cards")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_cards_filter(client):
    async with client as c:
        resp = await c.get("/cards?character=Ironclad&type=Attack")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_relics_page(client):
    async with client as c:
        resp = await c.get("/relics")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_potions_page(client):
    async with client as c:
        resp = await c.get("/potions")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_enemies_page(client):
    async with client as c:
        resp = await c.get("/enemies")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_events_page(client):
    async with client as c:
        resp = await c.get("/events")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_empty(client):
    async with client as c:
        resp = await c.get("/search?q=")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_search_with_query(client):
    async with client as c:
        resp = await c.get("/search?q=bash")
    assert resp.status_code == 200


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


@pytest.mark.asyncio
async def test_deck_analyze_empty(client):
    async with client as c:
        resp = await c.post("/deck/analyze", data={})
    assert resp.status_code == 200
    assert "No cards selected" in resp.text


@pytest.mark.asyncio
async def test_runs_page(client):
    async with client as c:
        resp = await c.get("/runs")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_live_page(client):
    async with client as c:
        resp = await c.get("/live")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_live(client):
    async with client as c:
        resp = await c.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data


@pytest.mark.asyncio
async def test_security_headers(client):
    async with client as c:
        resp = await c.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
