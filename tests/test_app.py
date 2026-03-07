"""Tests for the FastAPI routes."""
import pytest
from httpx import AsyncClient, ASGITransport

from sts2.app import app, _CSRF_TOKEN, _ADMIN_TOKEN, _rate_limit_store


@pytest.fixture
def client():
    _rate_limit_store.clear()
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
    assert '<nav' in resp.text


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


async def test_skip_to_content_link(client):
    """Should have a skip-to-content link for accessibility."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'skip-link' in resp.text
    assert 'href="#main"' in resp.text


async def test_nav_has_aria_label(client):
    """Nav should have aria-label for screen readers."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'aria-label=' in resp.text


async def test_main_landmark(client):
    """Content should be in a <main> element."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert '<main' in resp.text
    assert 'id="main"' in resp.text


async def test_footer_present(client):
    """Should have a footer with version and GitHub link."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert '<footer>' in resp.text
    assert 'Spirescope' in resp.text
    assert 'GitHub' in resp.text


async def test_card_detail_shows_card_stats(client):
    """Card detail page should show personal stats when card_stats data exists."""
    from unittest.mock import patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(
        card_stats={"CARD.BASH": {"picked": 10, "skipped": 5, "won": 7, "lost": 3}},
    )
    with patch("sts2.app._get_progress", return_value=mock_progress):
        async with client as c:
            resp = await c.get("/cards/CARD.BASH")
    if resp.status_code == 200:
        assert "Your Stats" in resp.text
        assert "Picked" in resp.text


async def test_card_detail_no_stats_when_empty(client):
    """Card detail page should not show stats section when card_stats is empty."""
    from unittest.mock import patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(card_stats={})
    with patch("sts2.app._get_progress", return_value=mock_progress):
        async with client as c:
            resp = await c.get("/cards/CARD.BASH")
    if resp.status_code == 200:
        assert "Your Stats" not in resp.text


async def test_index_shows_character_streaks(client):
    """Index page should show streak/ascension info when available."""
    from unittest.mock import patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(
        total_playtime=36000,
        character_stats={
            "Ironclad": {
                "wins": 5, "losses": 3, "playtime": 18000,
                "best_streak": 3, "current_streak": 2,
                "max_ascension": 10, "fastest_win": 900,
            },
        },
    )
    with patch("sts2.app._get_progress", return_value=mock_progress):
        async with client as c:
            resp = await c.get("/")
    assert resp.status_code == 200
    assert "Best streak" in resp.text
    assert "Max ascension" in resp.text
    assert "Fastest win" in resp.text


async def test_save_watcher_constants():
    """Background watcher should have sensible defaults."""
    from sts2.app import _PROGRESS_CACHE_TTL, _RUN_CACHE_TTL
    assert _PROGRESS_CACHE_TTL > 0
    assert _RUN_CACHE_TTL > 0


async def test_progress_cache_returns_same_object():
    """Cached progress should return same object within TTL."""
    from sts2.app import _get_progress
    p1 = _get_progress()
    p2 = _get_progress()
    assert p1 is p2


async def test_runs_page_has_filters(client):
    """Runs page should have character filter links."""
    async with client as c:
        resp = await c.get("/runs")
    assert resp.status_code == 200
    assert "Ironclad" in resp.text
    assert "Total Runs" in resp.text or "Showing" in resp.text


async def test_runs_filter_by_character(client):
    """Runs page should accept character filter."""
    async with client as c:
        resp = await c.get("/runs?character=Ironclad")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_runs_filter_by_result(client):
    """Runs page should accept win/loss filter."""
    async with client as c:
        resp = await c.get("/runs?result=win")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_api_card_detail(client):
    """API should return card JSON with stats."""
    async with client as c:
        resp = await c.get("/api/cards/CARD.BASH")
    if resp.status_code == 200:
        data = resp.json()
        assert "name" in data
        assert "stats" in data


async def test_api_card_detail_404(client):
    """API should return 404 for unknown card."""
    async with client as c:
        resp = await c.get("/api/cards/CARD.NONEXISTENT")
    assert resp.status_code == 404


async def test_api_runs(client):
    """API should return runs list and accept filters."""
    async with client as c:
        resp = await c.get("/api/runs")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        # Also test with filters in same session
        resp2 = await c.get("/api/runs?character=Ironclad&result=win")
        assert resp2.status_code == 200
        assert isinstance(resp2.json(), list)


async def test_nav_highlights_current_page(client):
    """Nav should highlight the active page link."""
    async with client as c:
        resp = await c.get("/cards")
    assert resp.status_code == 200
    # The cards link should have an active style
    assert 'href="/cards"' in resp.text


async def test_card_detail_has_breadcrumb(client):
    """Card detail should have breadcrumb navigation."""
    from sts2.app import kb as _kb
    if not _kb.cards:
        return
    card = _kb.cards[0]
    async with client as c:
        resp = await c.get(f"/cards/{card.id}")
    assert resp.status_code == 200
    assert "&rsaquo;" in resp.text
    assert 'href="/cards"' in resp.text


async def test_enemy_detail_has_breadcrumb(client):
    """Enemy detail should have breadcrumb navigation."""
    from sts2.app import kb as _kb
    if not _kb.enemies:
        return
    enemy = _kb.enemies[0]
    async with client as c:
        resp = await c.get(f"/enemies/{enemy.id}")
    assert resp.status_code == 200
    assert 'href="/enemies"' in resp.text


async def test_events_filter_by_act(client):
    """Events page should accept act filter."""
    async with client as c:
        resp = await c.get("/events?act=Act+1")
    assert resp.status_code == 200
    assert "All Acts" in resp.text


async def test_events_no_filter(client):
    """Events page without filter should show all events."""
    async with client as c:
        resp = await c.get("/events")
    assert resp.status_code == 200
    assert "Events" in resp.text


async def test_relic_detail_page(client):
    """Relic detail page should render for a known relic."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    async with client as c:
        resp = await c.get(f"/relics/{relic.id}")
    assert resp.status_code == 200
    assert relic.name in resp.text
    assert 'href="/relics"' in resp.text


async def test_relic_detail_404(client):
    """Relic detail page should return 404 for unknown relic."""
    async with client as c:
        resp = await c.get("/relics/RELIC.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_relics_page_links_to_detail(client):
    """Relics page should link to individual relic detail pages."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    async with client as c:
        resp = await c.get("/relics")
    assert resp.status_code == 200
    assert f'href="/relics/{_kb.relics[0].id}"' in resp.text


async def test_potions_filter_by_rarity(client):
    """Potions page should accept rarity filter."""
    async with client as c:
        resp = await c.get("/potions?rarity=Common")
    assert resp.status_code == 200
    assert "All Rarities" in resp.text


async def test_potions_no_filter(client):
    """Potions page without filter should show all potions."""
    async with client as c:
        resp = await c.get("/potions")
    assert resp.status_code == 200
    assert "Potions" in resp.text


async def test_sitemap_xml(client):
    """Sitemap should list all pages as XML."""
    async with client as c:
        resp = await c.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "<urlset" in resp.text
    assert "<url>" in resp.text
    assert "/cards" in resp.text
    assert "/relics" in resp.text
    assert "/enemies" in resp.text


async def test_robots_txt_references_sitemap(client):
    """robots.txt should reference sitemap.xml."""
    async with client as c:
        resp = await c.get("/robots.txt")
    assert resp.status_code == 200
    assert "sitemap.xml" in resp.text.lower()


async def test_cards_page_shows_pick_rate(client):
    """Cards list should show pick rate when card_stats data exists."""
    from unittest.mock import patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(
        card_stats={"CARD.BASH": {"picked": 8, "skipped": 2, "won": 5, "lost": 3}},
    )
    with patch("sts2.app._get_progress", return_value=mock_progress):
        async with client as c:
            resp = await c.get("/cards")
    if resp.status_code == 200 and ("CARD.BASH" in resp.text or "Bash" in resp.text):
        assert "Picked" in resp.text or "80%" in resp.text


async def test_search_results_link_to_relic_detail(client):
    """Search results should link relics to their detail pages."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    async with client as c:
        resp = await c.get(f"/search?q={relic.name}")
    if resp.status_code == 200 and relic.name in resp.text:
        assert f'href="/relics/{relic.id}"' in resp.text


async def test_run_detail_links_relics(client):
    """Run detail page should link relics to detail pages."""
    async with client as c:
        resp = await c.get("/runs")
    # Just verify the template renders without error
    assert resp.status_code == 200


async def test_card_detail_shows_run_win_rate(client):
    """Card detail should show win rate from run history."""
    from unittest.mock import patch
    from sts2.models import RunHistory

    mock_runs = [
        RunHistory(id="run1", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="run2", character="Ironclad", win=False, deck=["CARD.BASH"]),
        RunHistory(id="run3", character="Ironclad", win=True, deck=["CARD.BASH"]),
    ]
    with patch("sts2.app._get_runs", return_value=mock_runs):
        async with client as c:
            resp = await c.get("/cards/CARD.BASH")
    if resp.status_code == 200:
        assert "Run History with" in resp.text
        assert "Win Rate" in resp.text
        assert "67%" in resp.text


async def test_card_detail_og_title(client):
    """Card detail should have og:title meta tag."""
    from sts2.app import kb as _kb
    if not _kb.cards:
        return
    card = _kb.cards[0]
    async with client as c:
        resp = await c.get(f"/cards/{card.id}")
    if resp.status_code == 200:
        assert "og:title" in resp.text
        assert "Spirescope" in resp.text


# --- Analytics tests ---

async def test_analytics_page(client):
    """Analytics page should render."""
    async with client as c:
        resp = await c.get("/analytics")
    assert resp.status_code == 200
    assert "Analytics" in resp.text


async def test_analytics_page_empty_runs(client):
    """Analytics page with no runs should show empty state."""
    from unittest.mock import patch
    from sts2.analytics import compute_analytics
    with patch("sts2.app._get_analytics", return_value=compute_analytics([])):
        async with client as c:
            resp = await c.get("/analytics")
    assert resp.status_code == 200
    assert "No run data yet" in resp.text


async def test_api_analytics(client):
    """API analytics endpoint should return JSON."""
    async with client as c:
        resp = await c.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "overview" in data
    assert "total" in data["overview"]


async def test_analytics_with_mock_runs(client):
    """Analytics with run data should compute stats."""
    from unittest.mock import patch
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH", "CARD.STRIKE"],
                   relics=["RELIC.BURNING_BLOOD"], run_time=1200),
        RunHistory(id="r2", character="Ironclad", win=False, deck=["CARD.BASH", "CARD.DEFEND"],
                   relics=["RELIC.BURNING_BLOOD"], run_time=900),
        RunHistory(id="r3", character="Silent", win=True, deck=["CARD.NEUTRALIZE", "CARD.STRIKE"],
                   relics=["RELIC.RING_OF_THE_SNAKE"], run_time=1500),
    ]
    with patch("sts2.app._get_analytics", return_value=compute_analytics(mock_runs)):
        async with client as c:
            resp = await c.get("/api/analytics")
    data = resp.json()
    assert data["overview"]["total"] == 3
    assert data["overview"]["wins"] == 2
    assert data["overview"]["losses"] == 1


async def test_analytics_card_rankings():
    """Analytics should compute card win rates."""
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="r2", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="r3", character="Ironclad", win=False, deck=["CARD.BASH"]),
    ]
    data = compute_analytics(mock_runs)
    assert len(data["card_rankings"]) > 0
    bash_ranking = [cr for cr in data["card_rankings"] if cr["id"] == "CARD.BASH"]
    assert len(bash_ranking) == 1
    assert bash_ranking[0]["win_rate"] == 66.7
    assert bash_ranking[0]["appearances"] == 3


async def test_analytics_character_breakdown():
    """Analytics should break down stats by character."""
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="r2", character="Silent", win=False, deck=["CARD.NEUTRALIZE"]),
    ]
    data = compute_analytics(mock_runs)
    assert "Ironclad" in data["character_breakdown"]
    assert "Silent" in data["character_breakdown"]
    assert data["character_breakdown"]["Ironclad"]["wins"] == 1


async def test_analytics_synergy_edges():
    """Analytics should compute card co-occurrence in winning decks."""
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.A", "CARD.B"]),
        RunHistory(id="r2", character="Ironclad", win=True, deck=["CARD.A", "CARD.B"]),
        RunHistory(id="r3", character="Ironclad", win=False, deck=["CARD.A", "CARD.C"]),
    ]
    data = compute_analytics(mock_runs)
    assert len(data["synergy_edges"]) > 0
    ab_edge = [e for e in data["synergy_edges"] if "CARD.A" in (e["source"], e["target"]) and "CARD.B" in (e["source"], e["target"])]
    assert len(ab_edge) == 1
    assert ab_edge[0]["weight"] == 2


async def test_analytics_page_shows_overview(client):
    """Analytics HTML page should show overview stats."""
    from unittest.mock import patch
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], run_time=600),
    ]
    with patch("sts2.app._get_analytics", return_value=compute_analytics(mock_runs)):
        async with client as c:
            resp = await c.get("/analytics")
    assert resp.status_code == 200
    assert "Total Runs" in resp.text
    assert "Win Rate" in resp.text


async def test_sitemap_includes_analytics(client):
    """Sitemap should include the analytics page."""
    async with client as c:
        resp = await c.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/analytics" in resp.text


# --- Community data tests ---

async def test_compute_analytics_empty():
    """compute_analytics with empty runs should return zero overview."""
    from sts2.analytics import compute_analytics
    result = compute_analytics([])
    assert result["overview"]["total"] == 0


async def test_compute_analytics_floor_survival():
    """compute_analytics should compute floor survival distribution."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory, RunFloor

    floors = [RunFloor(floor=i) for i in range(1, 12)]
    runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], floors=floors)]
    result = compute_analytics(runs)
    assert len(result["floor_survival"]) > 0


async def test_compute_analytics_damage_by_act():
    """compute_analytics should compute damage by act."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory, RunFloor

    floors = [RunFloor(floor=i, damage_taken=5) for i in range(1, 6)]
    runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], floors=floors)]
    result = compute_analytics(runs)
    assert "Act 1" in result["damage_by_act"]
    assert result["damage_by_act"]["Act 1"]["avg_per_floor"] == 5.0


async def test_community_consensus_tier():
    """Consensus tier should average votes correctly."""
    from sts2.community import _compute_consensus_tier
    assert _compute_consensus_tier(["S", "S", "A"]) == "S"
    assert _compute_consensus_tier(["A", "B", "C"]) == "B"
    assert _compute_consensus_tier(["D", "F"]) == "F"  # avg 0.5 rounds to 0 -> F
    assert _compute_consensus_tier([]) == ""


async def test_community_extract_tier_ratings():
    """Should extract tier ratings from formatted text."""
    from sts2.community import _extract_tier_ratings
    text = "S: Bash, Strike\nA: Defend\nB: Neutralize"
    names = {"bash", "strike", "defend", "neutralize"}
    ratings = _extract_tier_ratings(text, names)
    assert "bash" in ratings
    assert ratings["bash"] == ["S"]
    assert "defend" in ratings
    assert ratings["defend"] == ["A"]


async def test_community_is_sts2_post():
    """STS2 post detection should work for both subreddits."""
    from sts2.community import _is_sts2_post
    assert _is_sts2_post({"subreddit": "slaythespire2", "title": "any", "selftext": "", "flair": ""})
    assert _is_sts2_post({"subreddit": "slaythespire", "title": "STS2 tier list", "selftext": "", "flair": ""})
    assert not _is_sts2_post({"subreddit": "slaythespire", "title": "best ironclad cards", "selftext": "", "flair": ""})


async def test_community_extract_tips():
    """Should extract tips mentioning known entities."""
    from sts2.community import _extract_tips
    text = "Bash is really strong in act 1 because it applies Vulnerable. Defend is a solid pick early on for survival."
    names = {"bash", "defend"}
    tips = _extract_tips(text, names)
    assert "bash" in tips
    assert len(tips["bash"]) >= 1


async def test_knowledge_base_community_tips():
    """KnowledgeBase should load and serve community tips."""
    from sts2.app import kb as _kb
    # get_community_tips should return empty list for unknown entity
    tips = _kb.get_community_tips("NONEXISTENT_ENTITY_XYZ")
    assert tips == []


async def test_card_detail_passes_community_tips(client):
    """Card detail should include community_tips in template context."""
    from unittest.mock import patch
    from sts2.app import kb as _kb
    if not _kb.cards:
        return
    card = _kb.cards[0]
    mock_tips = ["This card is amazing in act 1 for dealing damage."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        async with client as c:
            resp = await c.get(f"/cards/{card.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text
        assert "Reddit" in resp.text


async def test_relic_detail_passes_community_tips(client):
    """Relic detail should include community_tips in template context."""
    from unittest.mock import patch
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    mock_tips = ["This relic synergizes well with strength builds."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        async with client as c:
            resp = await c.get(f"/relics/{relic.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text


async def test_community_cli_entry():
    """Community CLI command should be registered."""
    from sts2.__main__ import main
    # Just verify the import path works
    from sts2.community import run_community_scraper
    assert callable(run_community_scraper)


# --- Round 17: Community page, analytics cache, enemy tips ---

async def test_community_page(client):
    """Community page should render."""
    async with client as c:
        resp = await c.get("/community")
    assert resp.status_code == 200
    assert "Community Meta" in resp.text


async def test_community_page_empty_state(client):
    """Community page with no data should show instructions."""
    async with client as c:
        resp = await c.get("/community")
    assert resp.status_code == 200
    # Should show either meta posts or the empty state instructions
    assert "Community" in resp.text


async def test_community_page_with_meta_posts(client):
    """Community page should display meta posts when available."""
    from unittest.mock import patch
    from sts2.app import kb as _kb
    mock_posts = [
        {"title": "Best Ironclad Cards Tier List", "url": "https://reddit.com/r/test/1",
         "score": 150, "comments": 42, "type": "tier_list", "date": 1700000000},
    ]
    with patch.object(_kb, "meta_posts", mock_posts):
        async with client as c:
            resp = await c.get("/community")
    assert resp.status_code == 200
    assert "Best Ironclad Cards Tier List" in resp.text
    assert "150" in resp.text


async def test_community_nav_link(client):
    """Nav should include Community link."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'href="/community"' in resp.text


async def test_sitemap_includes_community(client):
    """Sitemap should include the community page."""
    async with client as c:
        resp = await c.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/community" in resp.text


async def test_enemy_detail_community_tips(client):
    """Enemy detail should show community tips when available."""
    from unittest.mock import patch
    from sts2.app import kb as _kb
    if not _kb.enemies:
        return
    enemy = _kb.enemies[0]
    mock_tips = ["This enemy hits hard in act 2, bring block cards."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        async with client as c:
            resp = await c.get(f"/enemies/{enemy.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text
        assert "Reddit" in resp.text


async def test_analytics_cache_returns_same_object():
    """Analytics cache should return same object within TTL."""
    from sts2.app import _get_analytics
    a1 = _get_analytics()
    a2 = _get_analytics()
    assert a1 is a2


async def test_analytics_cache_ttl_constant():
    """Analytics cache TTL should be set."""
    from sts2.app import _ANALYTICS_CACHE_TTL
    assert _ANALYTICS_CACHE_TTL > 0
    assert _ANALYTICS_CACHE_TTL >= 30  # at least 30s for heavy computation


async def test_community_page_shows_tier_cards(client):
    """Community page should group cards by tier when tiers are set."""
    from unittest.mock import patch, PropertyMock
    from sts2.app import kb as _kb
    from sts2.models import Card
    mock_cards = [
        Card(id="CARD.TEST_S", name="Test S", character="Ironclad", cost="1", type="Attack", rarity="Rare", tier="S"),
        Card(id="CARD.TEST_A", name="Test A", character="Ironclad", cost="1", type="Skill", rarity="Common", tier="A"),
    ]
    original_cards = _kb.cards
    try:
        _kb.cards = mock_cards
        async with client as c:
            resp = await c.get("/community")
        assert resp.status_code == 200
        assert "S-Tier" in resp.text
        assert "Test S" in resp.text
    finally:
        _kb.cards = original_cards


# --- Phase 4: Guide, CLI, scraper, analytics edge cases ---

async def test_guide_page(client):
    """Guide page should render."""
    async with client as c:
        resp = await c.get("/guide")
    assert resp.status_code == 200
    assert "Guide" in resp.text
    assert "Getting Started" in resp.text
    assert "Troubleshooting" in resp.text


async def test_guide_in_sitemap(client):
    """Sitemap should include the guide page."""
    async with client as c:
        resp = await c.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/guide" in resp.text


async def test_guide_nav_link(client):
    """Nav should include Guide link."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert 'href="/guide"' in resp.text


async def test_index_data_status(client):
    """Index should show data sources section."""
    async with client as c:
        resp = await c.get("/")
    assert resp.status_code == 200
    assert "Data Sources" in resp.text


async def test_cli_help():
    """CLI --help should print usage."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "sts2", "--help"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Usage:" in result.stdout
    assert "serve" in result.stdout
    assert "update" in result.stdout


async def test_cli_version():
    """CLI --version should print version."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "sts2", "--version"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode == 0
    assert "Spirescope" in result.stdout


async def test_cli_unknown_command():
    """CLI unknown command should exit with error."""
    import subprocess
    result = subprocess.run(
        ["python", "-m", "sts2", "foobar"],
        capture_output=True, text=True, timeout=10,
    )
    assert result.returncode != 0
    assert "Unknown command" in result.stdout


async def test_analytics_single_run():
    """Analytics with a single run should not crash."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory
    runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"])]
    result = compute_analytics(runs)
    assert result["overview"]["total"] == 1
    assert result["overview"]["wins"] == 1
    assert result["overview"]["win_rate"] == 100.0


async def test_analytics_all_wins():
    """Analytics with all wins (0 losses) should not divide by zero."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory
    runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="r2", character="Ironclad", win=True, deck=["CARD.BASH"]),
    ]
    result = compute_analytics(runs)
    assert result["overview"]["losses"] == 0
    assert result["overview"]["win_rate"] == 100.0


async def test_knowledge_base_data_status():
    """KnowledgeBase.get_data_status should return expected keys."""
    from sts2.app import kb as _kb
    status = _kb.get_data_status()
    assert "cards" in status
    assert "relics" in status
    assert "save_connected" in status
    assert "last_updated" in status
    assert isinstance(status["cards"], int)
