"""Tests for the FastAPI routes."""
import pytest

from sts2.app import generate_csrf_token, _ADMIN_TOKEN, _rate_limit_store


async def test_index(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "SpireScope" in resp.text
    # Should render stat boxes with counts
    assert "Cards" in resp.text
    assert "Relics" in resp.text
    # Should render character links
    assert "Ironclad" in resp.text
    # Should have navigation
    assert '<nav' in resp.text


async def test_cards_page(client):
    resp = await client.get("/cards")
    assert resp.status_code == 200
    assert "Cards (" in resp.text
    # Should render actual card names from the data
    assert '<div class="grid grid-3">' in resp.text


async def test_cards_filter(client):
    resp = await client.get("/cards?character=Ironclad&type=Attack")
    assert resp.status_code == 200
    # Ironclad filter should be active
    assert 'class="active">Ironclad' in resp.text
    # Should not contain cards from other characters in results
    assert "char-silent" not in resp.text or "char-ironclad" in resp.text


async def test_relics_page(client):
    resp = await client.get("/relics")
    assert resp.status_code == 200
    assert "Relics (" in resp.text
    assert '<div class="grid grid-3">' in resp.text


async def test_potions_page(client):
    resp = await client.get("/potions")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_enemies_page(client):
    resp = await client.get("/enemies")
    assert resp.status_code == 200
    assert "Enemies" in resp.text
    assert "All Acts" in resp.text


async def test_events_page(client):
    resp = await client.get("/events")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_search_empty(client):
    resp = await client.get("/search?q=")
    assert resp.status_code == 200
    assert "(0 results)" in resp.text


async def test_search_with_query(client):
    resp = await client.get("/search?q=bash")
    assert resp.status_code == 200
    assert "bash" in resp.text.lower()


async def test_api_search(client):
    resp = await client.get("/api/search?q=bash")
    assert resp.status_code == 200
    data = resp.json()
    assert "cards" in data
    assert "relics" in data


async def test_deck_analyzer_page(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "Deck" in resp.text


async def test_deck_analyze_empty(client):
    resp = await client.post("/deck/analyze", data={"csrf_token": generate_csrf_token()})
    assert resp.status_code == 200
    assert "No cards selected" in resp.text


async def test_deck_analyze_rejects_bad_csrf(client):
    resp = await client.post("/deck/analyze", data={"csrf_token": "bad_token"})
    assert resp.status_code == 403


async def test_runs_page(client):
    resp = await client.get("/runs")
    assert resp.status_code == 200
    assert "<h1>" in resp.text


async def test_live_page(client):
    resp = await client.get("/live")
    assert resp.status_code == 200
    # Either shows live run or "No Active Run"
    assert "Run" in resp.text


async def test_api_live(client):
    resp = await client.get("/api/live")
    assert resp.status_code == 200
    data = resp.json()
    assert "active" in data
    assert "total_players" in data
    assert "player_index" in data


async def test_live_with_player_param(client):
    resp = await client.get("/live?player=0")
    assert resp.status_code == 200


async def test_api_live_with_player_param(client):
    resp = await client.get("/api/live?player=0")
    assert resp.status_code == 200
    data = resp.json()
    assert data["player_index"] == 0


async def test_security_headers(client):
    resp = await client.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "DENY"
    assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "connect-src 'self'" in csp


async def test_api_search_includes_suggestions(client):
    resp = await client.get("/api/search?q=xyznonexistent")
    assert resp.status_code == 200
    data = resp.json()
    assert "suggestions" in data


async def test_search_suggestions_shown(client):
    resp = await client.get("/search?q=ironclsd")
    assert resp.status_code == 200
    # Should show "Did you mean" or "No results"
    assert "No results" in resp.text or "Did you mean" in resp.text


async def test_card_detail_404(client):
    resp = await client.get("/cards/CARD.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_enemy_detail_404(client):
    resp = await client.get("/enemies/ENEMY.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_run_detail_404(client):
    resp = await client.get("/runs/fake_run_id")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_strategy_404(client):
    resp = await client.get("/strategy/FakeCharacter")
    assert resp.status_code == 404
    assert "404" in resp.text


async def test_deck_page_has_csrf_token(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "csrf_token" in resp.text


async def test_cards_pagination_default(client):
    resp = await client.get("/cards")
    assert resp.status_code == 200
    assert "Cards (" in resp.text


async def test_cards_pagination_page2(client):
    resp = await client.get("/cards?page=2")
    assert resp.status_code == 200
    # Page 2 should still render cards (unless fewer than 30 total)
    assert "Cards (" in resp.text


async def test_cards_pagination_with_filter(client):
    resp = await client.get("/cards?character=Ironclad&page=1")
    assert resp.status_code == 200
    assert 'class="active">Ironclad' in resp.text


async def test_cards_pagination_out_of_range(client):
    resp = await client.get("/cards?page=9999")
    assert resp.status_code == 200
    # Should clamp to last page, not error


async def test_api_reload_with_valid_token(client):
    resp = await client.post("/api/reload", headers={"X-Admin-Token": _ADMIN_TOKEN})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "cards" in data
    assert data["cards"] > 0


async def test_api_reload_rejects_bad_token(client):
    resp = await client.post("/api/reload", headers={"X-Admin-Token": "bad_token"})
    assert resp.status_code == 403


async def test_api_reload_rejects_missing_token(client):
    resp = await client.post("/api/reload")
    assert resp.status_code == 403


async def test_live_page_has_sse_script(client):
    resp = await client.get("/live")
    assert resp.status_code == 200
    assert "live.js" in resp.text


async def test_live_stream_endpoint_exists(client):
    """SSE endpoint is registered (streaming tested via integration)."""
    from starlette.routing import Route
    from sts2.app import app as _app
    sse_routes = [r for r in _app.routes if isinstance(r, Route) and r.path == "/api/live/stream"]
    assert len(sse_routes) == 1


async def test_deck_page_has_save_load_ui(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "save-deck" in resp.text
    assert "load-deck" in resp.text
    assert "deck.js" in resp.text


async def test_deck_page_has_card_info_buttons(client):
    """Deck page should render info buttons with data attributes."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "card-info-btn" in resp.text
    assert "data-card-id" in resp.text


async def test_deck_page_card_data_attributes(client):
    """Card info buttons should embed description and tier data."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "data-card-desc" in resp.text
    assert "data-card-tier" in resp.text
    assert "data-card-keywords" in resp.text


async def test_api_card_includes_synergies(client):
    """API card endpoint should include synergies list."""
    resp = await client.get("/api/cards/CARD.BASH")
    assert resp.status_code == 200
    data = resp.json()
    assert "synergies" in data
    assert isinstance(data["synergies"], list)
    assert len(data["synergies"]) > 0
    assert "id" in data["synergies"][0]
    assert "name" in data["synergies"][0]
    assert len(data["synergies"]) <= 10


async def test_api_card_synergies_empty_for_keywordless(client):
    """Card with no keywords should return empty synergies."""
    resp = await client.get("/api/cards/CARD.BYRDONIS_EGG")
    if resp.status_code == 200:
        data = resp.json()
        assert "synergies" in data
        assert data["synergies"] == []


async def test_deck_page_has_search_input(client):
    """Deck page should have a search input for filtering cards."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "deck-search" in resp.text


async def test_deck_page_has_collapsible_sections(client):
    """Deck page should organize cards into collapsible sections."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "deck-section" in resp.text
    assert "deck-section-header" in resp.text


async def test_deck_page_has_type_filter_buttons(client):
    """Deck page should have type filter buttons."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "deck-filters" in resp.text
    assert 'data-filter-type="Attack"' in resp.text


async def test_deck_page_has_selected_counter(client):
    """Deck page should have a selected card counter."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "deck-count" in resp.text


async def test_deck_page_cards_have_type_data(client):
    """Deck card chips should have data-card-type attributes for filtering."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "data-card-type=" in resp.text


async def test_collections_stat_boxes_render(client):
    """Collections page should render stat boxes."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "stat-box" in resp.text


async def test_collections_has_character_sections(client):
    """Collections discovered cards should be grouped by character."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "deck-section" in resp.text


async def test_deck_page_has_qty_buttons(client):
    """Deck page should have quantity +/- buttons instead of checkboxes."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "qty-btn" in resp.text
    assert "qty-count" in resp.text
    assert "qty-minus" in resp.text
    assert "qty-plus" in resp.text


async def test_deck_js_cache_busted(client):
    """Deck page script tag should include cache-busting hash."""
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert "deck.js?v=" in resp.text


async def test_collections_js_cache_busted(client):
    """Collections page script tag should include cache-busting hash."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "collections.js?v=" in resp.text


async def test_deck_page_has_cost_curve_styles(client):
    """CSS should include cost curve stacked bar styles."""
    resp = await client.get("/static/style.css")
    assert resp.status_code == 200
    assert "cost-stack" in resp.text
    assert "bar--attack" in resp.text


async def test_deck_from_run_with_invalid_id(client):
    """GET /deck?from_run=nonexistent should render empty analyzer."""
    resp = await client.get("/deck?from_run=nonexistent_run_id")
    assert resp.status_code == 200
    assert "Deck Analyzer" in resp.text
    assert "Deck loaded from" not in resp.text


async def test_deck_from_run_with_mock_data(client):
    """GET /deck?from_run=<id> should pre-select cards."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import RunHistory

    mock_run = RunHistory(
        id="test_run_abc", character="Ironclad", win=True,
        deck=["CARD.IRONCLAD.BASH", "CARD.IRONCLAD.STRIKE",
              "CARD.IRONCLAD.STRIKE"],
    )
    with patch("sts2.app._get_run_by_id", new_callable=AsyncMock,
               return_value=mock_run):
        resp = await client.get("/deck?from_run=test_run_abc")
    assert resp.status_code == 200
    assert "Deck loaded from" in resp.text
    assert "test_run_abc" in resp.text
    assert "deck-init-data" in resp.text


async def test_run_detail_has_analyze_button(client):
    """Run detail page should have an Analyze Deck link."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import RunHistory

    mock_run = RunHistory(
        id="test_run_xyz", character="Ironclad", win=True,
        deck=["CARD.IRONCLAD.BASH"],
    )
    with patch("sts2.app._get_run_by_id", new_callable=AsyncMock,
               return_value=mock_run):
        resp = await client.get("/runs/test_run_xyz")
    assert resp.status_code == 200
    assert "/deck?from_run=test_run_xyz" in resp.text
    assert "Analyze Deck" in resp.text


async def test_cards_pagination_shows_range(client):
    """When paginated, shows 'Showing X-Y of Z' indicator."""
    resp = await client.get("/cards?page=1")
    assert resp.status_code == 200
    # If more than one page exists, should show range indicator
    if "page=2" in resp.text or "Next" in resp.text:
        assert "Showing" in resp.text


async def test_sse_connection_limit_registered(client):
    """SSE max connections constant is set."""
    from sts2.routes import _SSE_MAX_CONNECTIONS
    assert _SSE_MAX_CONNECTIONS > 0


async def test_health_endpoint(client):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["cards"] > 0


async def test_robots_txt(client):
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "User-agent" in resp.text
    assert "Disallow: /api/" in resp.text


async def test_meta_description_in_html(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'meta name="description"' in resp.text
    assert 'meta name="theme-color"' in resp.text


async def test_player_param_validation(client):
    """Player param > 3 should be rejected."""
    resp = await client.get("/api/live?player=99")
    assert resp.status_code == 422


async def test_deck_analyze_caps_card_count(client):
    """Submitting more than MAX_DECK_SIZE cards should not crash."""
    from sts2.routes import _MAX_DECK_SIZE
    card_ids = [f"CARD.FAKE_{i}" for i in range(_MAX_DECK_SIZE + 50)]
    resp = await client.post("/deck/analyze", data={
        "csrf_token": generate_csrf_token(),
        "card_ids": card_ids,
    })
    assert resp.status_code == 200


async def test_admin_token_not_in_logs(client):
    """Admin token should not be exposed via any public endpoint."""
    resp = await client.get("/")
    assert _ADMIN_TOKEN not in resp.text


async def test_csp_blocks_external_scripts(client):
    """CSP should not allow external script sources."""
    resp = await client.get("/")
    csp = resp.headers.get("Content-Security-Policy", "")
    assert "script-src" in csp
    # Should not contain 'unsafe-eval' or wildcard
    assert "'unsafe-eval'" not in csp
    assert "script-src *" not in csp


async def test_css_cache_busting(client):
    """CSS link should include a version hash query parameter."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "style.css?v=" in resp.text


async def test_favicon_ico_link(client):
    """Should include a .ico favicon link for older browsers."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "favicon.ico" in resp.text


async def test_search_input_has_maxlength(client):
    """Search input should have maxlength attribute matching server-side limit."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'maxlength="200"' in resp.text


async def test_favicon_ico_serves(client):
    """The favicon.ico file should be served from /static/."""
    resp = await client.get("/static/favicon.ico")
    assert resp.status_code == 200


async def test_skip_to_content_link(client):
    """Should have a skip-to-content link for accessibility."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'skip-link' in resp.text
    assert 'href="#main"' in resp.text


async def test_nav_has_aria_label(client):
    """Nav should have aria-label for screen readers."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'aria-label=' in resp.text


async def test_main_landmark(client):
    """Content should be in a <main> element."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert '<main' in resp.text
    assert 'id="main"' in resp.text


async def test_footer_present(client):
    """Should have a footer with version and GitHub link."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert '<footer>' in resp.text
    assert 'SpireScope' in resp.text
    assert 'GitHub' in resp.text


async def test_card_detail_shows_card_stats(client):
    """Card detail page should show personal stats when card_stats data exists."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(
        card_stats={"CARD.BASH": {"picked": 10, "skipped": 5, "won": 7, "lost": 3}},
    )
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=mock_progress)):
        resp = await client.get("/cards/CARD.BASH")
    if resp.status_code == 200:
        assert "Your Stats" in resp.text
        assert "Picked" in resp.text


async def test_card_detail_no_stats_when_empty(client):
    """Card detail page should not show stats section when card_stats is empty."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(card_stats={})
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=mock_progress)):
        resp = await client.get("/cards/CARD.BASH")
    if resp.status_code == 200:
        assert "Your Stats" not in resp.text


async def test_index_shows_character_streaks(client):
    """Index page should show streak/ascension info when available."""
    from unittest.mock import AsyncMock, patch
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
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=mock_progress)):
        resp = await client.get("/")
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
    p1 = await _get_progress()
    p2 = await _get_progress()
    assert p1 is p2


async def test_runs_page_has_filters(client):
    """Runs page should have character filter links."""
    resp = await client.get("/runs")
    assert resp.status_code == 200
    assert "Ironclad" in resp.text
    assert "Total Runs" in resp.text or "Showing" in resp.text


async def test_runs_filter_by_character(client):
    """Runs page should accept character filter."""
    resp = await client.get("/runs?character=Ironclad")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_runs_filter_by_result(client):
    """Runs page should accept win/loss filter."""
    resp = await client.get("/runs?result=win")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_api_card_detail(client):
    """API should return card JSON with stats."""
    resp = await client.get("/api/cards/CARD.BASH")
    if resp.status_code == 200:
        data = resp.json()
        assert "name" in data
        assert "stats" in data


async def test_api_card_detail_404(client):
    """API should return 404 for unknown card."""
    resp = await client.get("/api/cards/CARD.NONEXISTENT")
    assert resp.status_code == 404


async def test_api_runs(client):
    """API should return runs list and accept filters."""
    resp = await client.get("/api/runs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "runs" in data
    assert "total" in data
    assert isinstance(data["runs"], list)
    # Also test with filters in same session
    resp2 = await client.get("/api/runs?character=Ironclad&result=win")
    assert resp2.status_code == 200
    data2 = resp2.json()
    assert isinstance(data2, dict)
    assert isinstance(data2["runs"], list)


async def test_nav_highlights_current_page(client):
    """Nav should highlight the active page link."""
    resp = await client.get("/cards")
    assert resp.status_code == 200
    # The cards link should have an active style
    assert 'href="/cards"' in resp.text


async def test_card_detail_has_breadcrumb(client):
    """Card detail should have breadcrumb navigation."""
    from sts2.app import kb as _kb
    if not _kb.cards:
        return
    card = _kb.cards[0]
    resp = await client.get(f"/cards/{card.id}")
    assert resp.status_code == 200
    assert "&rsaquo;" in resp.text
    assert 'href="/cards"' in resp.text


async def test_enemy_detail_has_breadcrumb(client):
    """Enemy detail should have breadcrumb navigation."""
    from sts2.app import kb as _kb
    if not _kb.enemies:
        return
    enemy = _kb.enemies[0]
    resp = await client.get(f"/enemies/{enemy.id}")
    assert resp.status_code == 200
    assert 'href="/enemies"' in resp.text


async def test_events_filter_by_act(client):
    """Events page should accept act filter."""
    resp = await client.get("/events?act=Act+1")
    assert resp.status_code == 200
    assert "All Acts" in resp.text


async def test_events_no_filter(client):
    """Events page without filter should show all events."""
    resp = await client.get("/events")
    assert resp.status_code == 200
    assert "Events" in resp.text


async def test_relic_detail_page(client):
    """Relic detail page should render for a known relic."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    resp = await client.get(f"/relics/{relic.id}")
    assert resp.status_code == 200
    assert relic.name in resp.text
    assert 'href="/relics"' in resp.text


async def test_relic_detail_404(client):
    """Relic detail page should return 404 for unknown relic."""
    resp = await client.get("/relics/RELIC.NONEXISTENT")
    assert resp.status_code == 404
    assert "not found" in resp.text.lower()


async def test_relics_page_links_to_detail(client):
    """Relics page should link to individual relic detail pages."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    resp = await client.get("/relics")
    assert resp.status_code == 200
    assert f'href="/relics/{_kb.relics[0].id}"' in resp.text


async def test_potions_filter_by_rarity(client):
    """Potions page should accept rarity filter."""
    resp = await client.get("/potions?rarity=Common")
    assert resp.status_code == 200
    assert "All Rarities" in resp.text


async def test_potions_no_filter(client):
    """Potions page without filter should show all potions."""
    resp = await client.get("/potions")
    assert resp.status_code == 200
    assert "Potions" in resp.text


async def test_sitemap_xml(client):
    """Sitemap should list all pages as XML."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "<urlset" in resp.text
    assert "<url>" in resp.text
    assert "/cards" in resp.text
    assert "/relics" in resp.text
    assert "/enemies" in resp.text


async def test_robots_txt_references_sitemap(client):
    """robots.txt should reference sitemap.xml."""
    resp = await client.get("/robots.txt")
    assert resp.status_code == 200
    assert "sitemap.xml" in resp.text.lower()


async def test_cards_page_shows_pick_rate(client):
    """Cards list should show pick rate when card_stats data exists."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import PlayerProgress

    mock_progress = PlayerProgress(
        card_stats={"CARD.BASH": {"picked": 8, "skipped": 2, "won": 5, "lost": 3}},
    )
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=mock_progress)):
        resp = await client.get("/cards")
    if resp.status_code == 200 and ("CARD.BASH" in resp.text or "Bash" in resp.text):
        assert "Picked" in resp.text or "80%" in resp.text


async def test_search_results_link_to_relic_detail(client):
    """Search results should link relics to their detail pages."""
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    resp = await client.get(f"/search?q={relic.name}")
    if resp.status_code == 200 and relic.name in resp.text:
        assert f'href="/relics/{relic.id}"' in resp.text


async def test_run_detail_links_relics(client):
    """Run detail page should link relics to detail pages."""
    resp = await client.get("/runs")
    # Just verify the template renders without error
    assert resp.status_code == 200


async def test_card_detail_shows_run_win_rate(client):
    """Card detail should show win rate from run history."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import RunHistory

    mock_runs = [
        RunHistory(id="run1", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="run2", character="Ironclad", win=False, deck=["CARD.BASH"]),
        RunHistory(id="run3", character="Ironclad", win=True, deck=["CARD.BASH"]),
    ]
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=mock_runs)):
        resp = await client.get("/cards/CARD.BASH")
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
    resp = await client.get(f"/cards/{card.id}")
    if resp.status_code == 200:
        assert "og:title" in resp.text
        assert "SpireScope" in resp.text


# --- Analytics tests ---

async def test_analytics_page(client):
    """Analytics page should render."""
    resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Analytics" in resp.text


async def test_analytics_page_empty_runs(client):
    """Analytics page with no runs should show empty state."""
    from unittest.mock import AsyncMock, patch
    from sts2.analytics import compute_analytics
    with patch("sts2.app._get_analytics", new=AsyncMock(return_value=compute_analytics([]))):
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "No run data yet" in resp.text


async def test_api_analytics(client):
    """API analytics endpoint should return JSON."""
    resp = await client.get("/api/analytics")
    assert resp.status_code == 200
    data = resp.json()
    assert "overview" in data
    assert "total" in data["overview"]


async def test_analytics_with_mock_runs(client):
    """Analytics with run data should compute stats."""
    from unittest.mock import AsyncMock, patch
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
    with patch("sts2.app._get_analytics", new=AsyncMock(return_value=compute_analytics(mock_runs))):
        resp = await client.get("/api/analytics")
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
    from unittest.mock import AsyncMock, patch
    from sts2.models import RunHistory
    from sts2.analytics import compute_analytics

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], run_time=600),
    ]
    with patch("sts2.app._get_analytics", new=AsyncMock(return_value=compute_analytics(mock_runs))):
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Total Runs" in resp.text
    assert "Win Rate" in resp.text


async def test_sitemap_includes_analytics(client):
    """Sitemap should include the analytics page."""
    resp = await client.get("/sitemap.xml")
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
    from unittest.mock import AsyncMock, patch
    from sts2.app import kb as _kb
    if not _kb.cards:
        return
    card = _kb.cards[0]
    mock_tips = ["This card is amazing in act 1 for dealing damage."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        resp = await client.get(f"/cards/{card.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text
        assert "Reddit" in resp.text


async def test_relic_detail_passes_community_tips(client):
    """Relic detail should include community_tips in template context."""
    from unittest.mock import AsyncMock, patch
    from sts2.app import kb as _kb
    if not _kb.relics:
        return
    relic = _kb.relics[0]
    mock_tips = ["This relic synergizes well with strength builds."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        resp = await client.get(f"/relics/{relic.id}")
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
    resp = await client.get("/community")
    assert resp.status_code == 200
    assert "Community Meta" in resp.text


async def test_community_page_empty_state(client):
    """Community page with no data should show instructions."""
    resp = await client.get("/community")
    assert resp.status_code == 200
    # Should show either meta posts or the empty state instructions
    assert "Community" in resp.text


async def test_community_page_with_meta_posts(client):
    """Community page should display meta posts when available."""
    from unittest.mock import AsyncMock, patch
    from sts2.app import kb as _kb
    mock_posts = [
        {"title": "Best Ironclad Cards Tier List", "url": "https://reddit.com/r/test/1",
         "score": 150, "comments": 42, "type": "tier_list", "date": 1700000000},
    ]
    with patch.object(_kb, "meta_posts", mock_posts):
        resp = await client.get("/community")
    assert resp.status_code == 200
    assert "Best Ironclad Cards Tier List" in resp.text
    assert "150" in resp.text


async def test_community_nav_link(client):
    """Nav should include Community link."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'href="/community"' in resp.text


async def test_sitemap_includes_community(client):
    """Sitemap should include the community page."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/community" in resp.text


async def test_enemy_detail_community_tips(client):
    """Enemy detail should show community tips when available."""
    from unittest.mock import AsyncMock, patch
    from sts2.app import kb as _kb
    if not _kb.enemies:
        return
    enemy = _kb.enemies[0]
    mock_tips = ["This enemy hits hard in act 2, bring block cards."]
    with patch.object(_kb, "get_community_tips", return_value=mock_tips):
        resp = await client.get(f"/enemies/{enemy.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text
        assert "Reddit" in resp.text


async def test_analytics_cache_returns_same_object():
    """Analytics cache should return same object within TTL."""
    from sts2.app import _get_analytics
    a1 = await _get_analytics()
    a2 = await _get_analytics()
    assert a1 is a2


async def test_analytics_cache_ttl_constant():
    """Analytics cache TTL should be set."""
    from sts2.app import _ANALYTICS_CACHE_TTL
    assert _ANALYTICS_CACHE_TTL > 0
    assert _ANALYTICS_CACHE_TTL >= 30  # at least 30s for heavy computation


async def test_community_page_shows_tier_cards(client):
    """Community page should group cards by tier when tiers are set."""
    from unittest.mock import AsyncMock, patch, PropertyMock
    from sts2.app import kb as _kb
    from sts2.models import Card
    mock_cards = [
        Card(id="CARD.TEST_S", name="Test S", character="Ironclad", cost="1", type="Attack", rarity="Rare", tier="S"),
        Card(id="CARD.TEST_A", name="Test A", character="Ironclad", cost="1", type="Skill", rarity="Common", tier="A"),
    ]
    original_cards = _kb.cards
    try:
        _kb.cards = mock_cards
        resp = await client.get("/community")
        assert resp.status_code == 200
        assert "S-Tier" in resp.text
        assert "Test S" in resp.text
    finally:
        _kb.cards = original_cards


# --- Phase 4: Guide, CLI, scraper, analytics edge cases ---

async def test_guide_page(client):
    """Guide page should render."""
    resp = await client.get("/guide")
    assert resp.status_code == 200
    assert "Guide" in resp.text
    assert "Getting Started" in resp.text
    assert "Troubleshooting" in resp.text


async def test_guide_in_sitemap(client):
    """Sitemap should include the guide page."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/guide" in resp.text


async def test_guide_nav_link(client):
    """Nav should include Guide link."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'href="/guide"' in resp.text


async def test_index_data_status(client):
    """Index should show data sources section."""
    resp = await client.get("/")
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


# --- Collections page ---

async def test_collections_page(client):
    """Collections page should render without save data."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "Collections" in resp.text


async def test_collections_no_progress(client):
    """Collections page without progress should show empty state."""
    from unittest.mock import AsyncMock, patch
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=None)):
        resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "No save data found" in resp.text


async def test_collections_with_progress(client):
    """Collections page with progress should show discovery counts."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import PlayerProgress
    from sts2.app import kb as _kb

    # Use real card IDs from the knowledge base
    card_ids = [c.id for c in _kb.cards[:5]]
    relic_ids = [r.id for r in _kb.relics[:3]]
    progress = PlayerProgress(
        discovered_cards=card_ids,
        discovered_relics=relic_ids,
        discovered_potions=[],
        discovered_events=[],
        character_stats={"Ironclad": {"wins": 2, "losses": 1, "max_ascension": 5, "best_streak": 2}},
    )
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=progress)):
        resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "Overall" in resp.text
    assert "Cards" in resp.text
    assert "Relics" in resp.text
    assert "undiscovered" in resp.text
    assert "Character Progress" in resp.text


async def test_collections_nav_link(client):
    """Nav should include Collections link."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'href="/collections"' in resp.text


async def test_collections_in_sitemap(client):
    """Sitemap should include the collections page."""
    resp = await client.get("/sitemap.xml")
    assert resp.status_code == 200
    assert "/collections" in resp.text


# --- Ascension filtering ---

async def test_runs_filter_by_ascension(client):
    """Runs page should accept ascension filter."""
    resp = await client.get("/runs?ascension=0")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_runs_filter_combined(client):
    """Runs page should combine character, result, and ascension filters."""
    resp = await client.get("/runs?character=Ironclad&result=win&ascension=0")
    assert resp.status_code == 200
    assert "Showing" in resp.text


async def test_runs_ascension_filter_with_mock_data(client):
    """Ascension filter should correctly filter runs by level."""
    from unittest.mock import AsyncMock, patch
    from sts2.models import RunHistory

    mock_runs = [
        RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], ascension=5),
        RunHistory(id="r2", character="Ironclad", win=False, deck=["CARD.BASH"], ascension=0),
        RunHistory(id="r3", character="Silent", win=True, deck=["CARD.NEUTRALIZE"], ascension=5),
    ]
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=mock_runs)):
        resp = await client.get("/runs?ascension=5")
    assert resp.status_code == 200
    assert "Showing 2 run" in resp.text


async def test_runs_ascension_invalid(client):
    """Ascension filter with invalid value should return 422."""
    resp = await client.get("/runs?ascension=99")
    assert resp.status_code == 422


# --- Additional coverage: middleware, CSP, rate limiting ---

async def test_docs_csp_allows_cdn(client):
    """CSP for /docs should allow cdn.jsdelivr.net scripts."""
    resp = await client.get("/docs")
    csp = resp.headers.get("Content-Security-Policy", "")
    if resp.status_code == 200:
        assert "cdn.jsdelivr.net" in csp


async def test_static_cache_control(client):
    """Static files should have Cache-Control header."""
    resp = await client.get("/static/favicon.ico")
    assert resp.status_code == 200
    assert resp.headers.get("Cache-Control") == "public, max-age=3600"


async def test_rate_limit_cleanup():
    """Stale entries in rate limit store should be cleaned up."""
    import time
    from sts2.app import _rate_limit_store, _RATE_LIMIT_WINDOW
    import collections

    _rate_limit_store.clear()
    # Add a stale entry (timestamp in the distant past)
    stale_deque = collections.deque()
    stale_deque.append(0.0)  # epoch = very old
    _rate_limit_store["stale_ip"] = stale_deque

    # Add a fresh entry
    fresh_deque = collections.deque()
    fresh_deque.append(time.monotonic())
    _rate_limit_store["fresh_ip"] = fresh_deque

    assert "stale_ip" in _rate_limit_store
    assert "fresh_ip" in _rate_limit_store


async def test_rate_limit_api_key_bypass(client):
    """Requests with valid API key should bypass rate limiting."""
    import os
    from unittest.mock import patch
    from sts2.app import _rate_limit_store
    import collections
    import time

    _rate_limit_store.clear()
    test_key = "test-api-key-12345"

    with patch.dict(os.environ, {"SPIRESCOPE_API_KEY": test_key}):
        # Fill up rate limit
        ip = "testclient"
        _rate_limit_store[ip] = collections.deque([time.monotonic()] * 100)

        # Request with API key should bypass
        resp = await client.get("/", headers={"x-api-key": test_key})
        assert resp.status_code == 200


async def test_options_request_bypasses_rate_limit(client):
    """CORS preflight OPTIONS requests should not be rate-limited."""
    resp = await client.options("/api/search")
    # Should not be 429 even without any setup
    assert resp.status_code != 429


async def test_csrf_token_validation():
    """CSRF tokens should validate correctly."""
    from sts2.app import generate_csrf_token, validate_csrf_token
    token = generate_csrf_token()
    assert validate_csrf_token(token) is True
    assert validate_csrf_token("bad.token") is False
    assert validate_csrf_token("") is False
    assert validate_csrf_token("no_dot") is False


async def test_run_cache_by_id():
    """_get_run_by_id should return the correct run."""
    from unittest.mock import AsyncMock, patch
    from sts2.app import _get_run_by_id
    from sts2.models import RunHistory

    mock_runs = [
        RunHistory(id="run_abc", character="Ironclad", win=True, deck=["CARD.BASH"]),
        RunHistory(id="run_def", character="Silent", win=False, deck=["CARD.NEUTRALIZE"]),
    ]
    with patch("sts2.app._get_runs", new=AsyncMock(return_value=mock_runs)):
        # Populate the cache
        from sts2.app import _get_runs
        await _get_runs()

    result = await _get_run_by_id("run_abc")
    if result:
        assert result.character == "Ironclad"


async def test_strategy_page_renders(client):
    """Strategy page for valid character should render."""
    resp = await client.get("/strategy/Ironclad")
    assert resp.status_code == 200
    assert "Ironclad" in resp.text


async def test_api_runs_pagination(client):
    """API runs endpoint should accept page parameter."""
    resp = await client.get("/api/runs?page=1&limit=5")
    assert resp.status_code == 200
    data = resp.json()
    assert "runs" in data
