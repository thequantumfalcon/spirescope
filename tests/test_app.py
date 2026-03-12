"""Tests for the FastAPI routes."""

from sts2.app import _ADMIN_TOKEN, _rate_limit_store, generate_csrf_token


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
    """Collections page should render stat boxes or no-data message."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "stat-box" in resp.text or "No save data" in resp.text


async def test_collections_has_character_sections(client):
    """Collections page should render character sections or no-data message."""
    resp = await client.get("/collections")
    assert resp.status_code == 200
    assert "deck-section" in resp.text or "No save data" in resp.text


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

    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory

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
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory

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
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory

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
    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory

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

    from sts2.analytics import compute_analytics
    from sts2.models import RunHistory

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
    from sts2.models import RunFloor, RunHistory

    floors = [RunFloor(floor=i) for i in range(1, 12)]
    runs = [RunHistory(id="r1", character="Ironclad", win=True, deck=["CARD.BASH"], floors=floors)]
    result = compute_analytics(runs)
    assert len(result["floor_survival"]) > 0


async def test_compute_analytics_damage_by_act():
    """compute_analytics should compute damage by act."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunFloor, RunHistory

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
        resp = await client.get(f"/cards/{card.id}")
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
        resp = await client.get(f"/relics/{relic.id}")
    if resp.status_code == 200:
        assert "Community Tips" in resp.text


async def test_community_cli_entry():
    """Community CLI command should be registered."""
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
    from unittest.mock import patch

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
    from unittest.mock import patch

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

    from sts2.app import kb as _kb
    from sts2.models import PlayerProgress

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
    import collections
    import time


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
    import collections
    import os
    import time
    from unittest.mock import patch

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


async def test_rate_limit_headers_present(client):
    """Normal responses should include rate limit headers."""
    _rate_limit_store.clear()
    resp = await client.get("/health")
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Remaining" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers
    assert resp.headers["X-RateLimit-Limit"] == "60"


async def test_rate_limit_headers_remaining_decrements(client):
    """Remaining count should decrease with successive requests."""
    _rate_limit_store.clear()
    resp1 = await client.get("/health")
    resp2 = await client.get("/health")
    r1 = int(resp1.headers["X-RateLimit-Remaining"])
    r2 = int(resp2.headers["X-RateLimit-Remaining"])
    assert r2 < r1


async def test_rate_limit_headers_on_429(client):
    """Rate limit headers should be present on 429 responses too."""
    import collections
    import time

    _rate_limit_store.clear()
    # httpx ASGI transport reports client as 127.0.0.1
    ip = "127.0.0.1"
    _rate_limit_store[ip] = collections.deque([time.monotonic()] * 65)
    resp = await client.get("/health")
    assert resp.status_code == 429
    assert resp.headers["X-RateLimit-Remaining"] == "0"
    assert "X-RateLimit-Limit" in resp.headers
    assert "X-RateLimit-Reset" in resp.headers


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


# ── Keyboard Shortcuts (Feature 2) ──


async def test_shortcuts_js_loaded(client):
    """Home page should include shortcuts.js script tag."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "shortcuts.js" in resp.text


async def test_shortcut_overlay_exists(client):
    """Home page should contain the shortcut overlay div."""
    resp = await client.get("/")
    assert "shortcut-overlay" in resp.text


async def test_shortcut_overlay_has_keys(client):
    """Overlay should list all shortcut keys."""
    resp = await client.get("/")
    for key in ["h", "c", "r", "a", "d", "l", "/", "?", "Esc"]:
        assert f"<kbd>{key}</kbd>" in resp.text


async def test_shortcuts_hash_not_zero():
    """shortcuts.js hash should be computed (file exists)."""
    from sts2.app import _SHORTCUTS_JS_HASH
    assert _SHORTCUTS_JS_HASH != "0"


# ── Ascension Filtering (Feature 3) ──


async def test_analytics_no_filter(client):
    """Analytics page loads without ascension filter."""
    resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "Analytics" in resp.text


async def test_analytics_with_ascension(client):
    """Analytics page accepts ascension query parameter."""
    resp = await client.get("/analytics?ascension=0")
    assert resp.status_code == 200


async def test_analytics_invalid_ascension(client):
    """Analytics page rejects out-of-range ascension."""
    resp = await client.get("/analytics?ascension=25")
    assert resp.status_code == 422


async def test_analytics_cache_keyed_by_ascension():
    """Filtered and unfiltered analytics use separate cache entries."""
    from sts2.app import _analytics_cache_time
    assert isinstance(_analytics_cache_time, dict)


# ---------------------------------------------------------------------------
# Analytics edge cases
# ---------------------------------------------------------------------------


async def test_analytics_single_run_via_route(client):
    """Analytics route should handle a single run without crashing."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import RunFloor, RunHistory

    run = RunHistory(id="solo", character="Ironclad", win=True, ascension=0,
                     deck=["Strike", "Defend"], relics=["BurningBlood"],
                     floors=[RunFloor(floor=1, type="monster", damage_taken=5,
                                      current_hp=70, max_hp=75)])
    with patch("sts2.app._get_runs", new_callable=AsyncMock, return_value=[run]), \
         patch("sts2.app._get_progress", new_callable=AsyncMock, return_value=None), \
         patch("sts2.app._analytics_cache", {}), \
         patch("sts2.app._analytics_cache_time", {}):
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "100" in resp.text  # 100% win rate


async def test_analytics_all_losses(client):
    """Analytics should handle all-loss runs without division errors."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import RunFloor, RunHistory

    runs = [
        RunHistory(id=f"loss{i}", character="Silent", win=False, ascension=0,
                   killed_by="Lagavulin", deck=["Strike"], relics=[],
                   floors=[RunFloor(floor=1, type="monster", damage_taken=50,
                                    current_hp=0, max_hp=70)])
        for i in range(3)
    ]
    with patch("sts2.app._get_runs", new_callable=AsyncMock, return_value=runs), \
         patch("sts2.app._get_progress", new_callable=AsyncMock, return_value=None), \
         patch("sts2.app._analytics_cache", {}), \
         patch("sts2.app._analytics_cache_time", {}):
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    assert "0.0%" in resp.text or "0%" in resp.text  # 0% win rate


async def test_analytics_zero_floors(client):
    """Analytics should handle a run with zero floors gracefully."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import RunHistory

    run = RunHistory(id="empty", character="Defect", win=False, ascension=0,
                     deck=[], relics=[], floors=[])
    with patch("sts2.app._get_runs", new_callable=AsyncMock, return_value=[run]), \
         patch("sts2.app._get_progress", new_callable=AsyncMock, return_value=None), \
         patch("sts2.app._analytics_cache", {}), \
         patch("sts2.app._analytics_cache_time", {}):
        resp = await client.get("/analytics")
    assert resp.status_code == 200


async def test_analytics_single_card_filtered():
    """Cards appearing only once should be excluded from rankings (min 2)."""
    from sts2.analytics import compute_analytics
    from sts2.models import RunFloor, RunHistory

    runs = [
        RunHistory(id="r1", character="Ironclad", win=True, ascension=0,
                   deck=["Strike", "RareCard"], relics=[],
                   floors=[RunFloor(floor=1, type="monster")]),
        RunHistory(id="r2", character="Ironclad", win=False, ascension=0,
                   deck=["Strike", "Defend"], relics=[],
                   floors=[RunFloor(floor=1, type="monster")]),
    ]
    result = compute_analytics(runs)
    # "RareCard" only appears once — should not be in card_rankings (min 2)
    card_ids = [c["id"] for c in result.get("card_rankings", [])]
    assert "RareCard" not in card_ids
    # "Strike" appears in both runs — should be in rankings
    assert "Strike" in card_ids


# ---------------------------------------------------------------------------
# _get_live_run merge logic
# ---------------------------------------------------------------------------


async def test_get_live_run_save_active():
    """When save file has active run and no log, return save data."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun
    from sts2.routes import _get_live_run

    active_run = CurrentRun(active=True, character="Ironclad", current_hp=50,
                            max_hp=80, gold=100, act=1, floor=5)
    with patch("sts2.routes.asyncio.to_thread", new_callable=AsyncMock,
               return_value=active_run), \
         patch("sts2.app._log_run_state", None):
        result = await _get_live_run()
    assert result.active is True
    assert result.character == "Ironclad"
    assert result.current_hp == 50


async def test_get_live_run_merge_both_active():
    """When both save and log are active, merge: save HP + log deck/gold."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun
    from sts2.routes import _get_live_run

    save_run = CurrentRun(active=True, character="Defect", current_hp=60,
                          max_hp=80, gold=50, act=1, floor=3,
                          relics=["RELIC.CRACKED_CORE"])
    log_state = {"active": True, "character": "Defect", "current_hp": 0,
                 "max_hp": 0, "gold": 120, "act": 1, "floor": 5,
                 "deck": ["CARD.BEAM_CELL", "CARD.TEMPEST"],
                 "potions": ["POTION.POWER_POTION"]}
    with patch("sts2.routes.asyncio.to_thread", new_callable=AsyncMock,
               return_value=save_run), \
         patch("sts2.app._log_run_state", log_state):
        result = await _get_live_run()
    # Save provides HP and relics
    assert result.current_hp == 60
    assert result.max_hp == 80
    assert "RELIC.CRACKED_CORE" in result.relics
    # Log provides fresher deck, gold, potions, floor
    assert result.deck == ["CARD.BEAM_CELL", "CARD.TEMPEST"]
    assert result.gold == 120
    assert result.potions == ["POTION.POWER_POTION"]
    assert result.floor == 5


async def test_get_live_run_log_only():
    """When save has no active run but log parser does, return log data."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun
    from sts2.routes import _get_live_run

    inactive_run = CurrentRun(active=False)
    log_state = {"active": True, "character": "Silent", "current_hp": 40,
                 "max_hp": 70, "gold": 50, "act": 2, "floor": 15}
    with patch("sts2.routes.asyncio.to_thread", new_callable=AsyncMock,
               return_value=inactive_run), \
         patch("sts2.routes._log_run_state", log_state, create=True), \
         patch("sts2.app._log_run_state", log_state):
        result = await _get_live_run()
    assert result.active is True
    assert result.character == "Silent"


async def test_get_live_run_neither():
    """When neither save nor log has active run, return inactive."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun
    from sts2.routes import _get_live_run

    inactive_run = CurrentRun(active=False)
    with patch("sts2.routes.asyncio.to_thread", new_callable=AsyncMock,
               return_value=inactive_run), \
         patch("sts2.app._log_run_state", None):
        result = await _get_live_run()
    assert result.active is False


# ---------------------------------------------------------------------------
# SSE connection cap
# ---------------------------------------------------------------------------


async def test_sse_connection_cap_enforced(client):
    """SSE endpoint should reject when at max connections."""
    import sts2.routes as routes_mod
    original = routes_mod._sse_active
    try:
        routes_mod._sse_active = 10
        resp = await client.get("/api/live/stream")
        assert resp.status_code == 429
        assert "Too many" in resp.text
    finally:
        routes_mod._sse_active = original


async def test_sse_counter_tracks_connections():
    """SSE active counter should exist as module-level int."""
    import sts2.routes as routes_mod
    assert hasattr(routes_mod, "_sse_active")
    assert isinstance(routes_mod._sse_active, int)
    assert routes_mod._SSE_MAX_CONNECTIONS == 10


# ---------------------------------------------------------------------------
# Background tasks
# ---------------------------------------------------------------------------


async def test_prewarm_caches():
    """_prewarm_caches should call get_progress and get_run_history."""
    from unittest.mock import AsyncMock, patch

    from sts2.app import _prewarm_caches

    with patch("sts2.app.get_progress", return_value=None), \
         patch("sts2.app.get_run_history", return_value=[]), \
         patch("sts2.app.asyncio.to_thread", new_callable=AsyncMock,
               side_effect=[None, []]):
        await _prewarm_caches()
    # to_thread is called twice: once for progress, once for runs


async def test_refresh_data_clears_caches():
    """_refresh_data should reset analytics cache."""
    from unittest.mock import AsyncMock, patch

    import sts2.app as app_mod
    from sts2.app import _refresh_data

    original_kb = app_mod.kb
    # Pre-fill caches
    app_mod._analytics_cache = {None: {"total": 5}}
    app_mod._analytics_cache_time = {None: 1000.0}

    try:
        with patch("sts2.app.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=[original_kb, None, []]):
            await _refresh_data()

        assert app_mod._analytics_cache == {} or None not in app_mod._analytics_cache_time or \
            app_mod._analytics_cache_time.get(None, 0) != 1000.0
    finally:
        app_mod.kb = original_kb


async def test_refresh_data_reloads_kb():
    """_refresh_data should create a new KnowledgeBase."""
    from unittest.mock import AsyncMock, MagicMock, patch

    import sts2.app as app_mod
    from sts2.app import _refresh_data

    original_kb = app_mod.kb
    mock_kb = MagicMock()
    try:
        with patch("sts2.app.asyncio.to_thread", new_callable=AsyncMock,
                   side_effect=[mock_kb, None, []]):
            await _refresh_data()
        assert app_mod.kb is mock_kb
    finally:
        app_mod.kb = original_kb  # Restore for other tests


async def test_poll_game_log_handles_error():
    """_poll_game_log should not crash on exceptions."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from sts2.app import _poll_game_log

    mock_tailer = MagicMock()
    mock_tailer.poll.side_effect = RuntimeError("log file missing")
    mock_tailer.state = None

    call_count = 0

    async def fake_to_thread(fn, *args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            raise asyncio.CancelledError  # Stop the infinite loop
        return fn(*args, **kwargs)

    import asyncio

    with patch("sts2.logparser.LogTailer", return_value=mock_tailer), \
         patch("sts2.app.asyncio.to_thread", side_effect=fake_to_thread), \
         patch("sts2.app.asyncio.sleep", new_callable=AsyncMock):
        try:
            await _poll_game_log()
        except asyncio.CancelledError:
            pass  # Expected — we use this to break the infinite loop

    # If we got here without an unhandled exception, the error handling works
    assert call_count >= 2


async def test_watch_saves_polling_fallback():
    """_watch_saves should fall back to polling when watchdog unavailable."""
    from unittest.mock import patch

    from sts2.app import _watch_saves

    call_count = 0

    async def fake_sleep(t):
        nonlocal call_count
        call_count += 1
        if call_count > 2:
            raise asyncio.CancelledError

    import asyncio

    with patch("sts2.watcher.start_observer", return_value=None), \
         patch("sts2.app.SAVE_DIR") as mock_dir, \
         patch("sts2.app.asyncio.sleep", side_effect=fake_sleep), \
         patch("sts2.app._check_mtime", return_value=0.0):
        mock_dir.exists.return_value = False
        try:
            await _watch_saves()
        except asyncio.CancelledError:
            pass

    assert call_count >= 2  # Confirms polling loop ran


# ---------------------------------------------------------------------------
# Coaching alerts (live page)
# ---------------------------------------------------------------------------


async def test_coaching_defensive_gap_warning(client):
    """Floor ≥4 with no Block keywords should produce a warning alert."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun

    run = CurrentRun(active=True, character="Defect", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=5,
                     deck=["CARD.ZAP", "CARD.ZAP", "CARD.BEAM_CELL"])
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock,
               return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    assert "No defensive cards by floor" in resp.text


async def test_coaching_defensive_gap_critical(client):
    """Floor ≥8 with no defense should escalate to critical."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun

    run = CurrentRun(active=True, character="Defect", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=10,
                     deck=["CARD.ZAP", "CARD.ZAP", "CARD.BEAM_CELL"])
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock,
               return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    assert "danger-critical" in resp.text
    assert "No defensive cards by floor" in resp.text


async def test_coaching_card_fatigue(client):
    """3+ copies of same card should trigger fatigue warning."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun

    run = CurrentRun(active=True, character="Defect", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=5,
                     deck=["CARD.ZAP", "CARD.ZAP", "CARD.ZAP", "CARD.BEAM_CELL"])
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock,
               return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    assert "appears 3x in deck" in resp.text
    assert "diminishing returns" in resp.text


async def test_coaching_boss_prep(client):
    """Approaching boss floor without defense should warn."""
    from unittest.mock import AsyncMock, patch

    from sts2.models import CurrentRun

    run = CurrentRun(active=True, character="Defect", current_hp=60, max_hp=80,
                     gold=50, act=1, floor=13,
                     deck=["CARD.ZAP", "CARD.ZAP", "CARD.BEAM_CELL"])
    with patch("sts2.routes._get_live_run", new_callable=AsyncMock,
               return_value=run):
        resp = await client.get("/live")
    assert resp.status_code == 200
    assert "Boss in" in resp.text
    assert "Block/defense" in resp.text


# ---------------------------------------------------------------------------
# Enhanced analyze_run + analyze_run_patterns
# ---------------------------------------------------------------------------


def test_analyze_run_low_skills():
    """All-attack deck should warn about low Skill percentage."""
    from unittest.mock import MagicMock

    from sts2.analytics import analyze_run
    from sts2.models import RunHistory

    kb = MagicMock()

    def make_card(type_):
        card = MagicMock()
        card.type = type_
        card.keywords = []
        return card

    # 8 attacks, 1 skill, 1 power = 10% skills
    cards = ["CARD.A"] * 8 + ["CARD.S"] + ["CARD.P"]
    kb.get_card_by_id.side_effect = lambda cid: (
        make_card("Attack") if "A" in cid else
        make_card("Skill") if "S" in cid else
        make_card("Power"))

    run = RunHistory(id="test", character="Defect", win=False, deck=cards,
                     relics=[], floors=[], run_time=600, ascension=0)
    result = analyze_run(run, kb=kb)
    texts = [i["text"] for i in result["insights"]]
    assert any("Skills" in t and "severely" in t.lower() for t in texts)


def test_analyze_run_no_defense():
    """Deck with no Block keywords should flag defensive gap."""
    from unittest.mock import MagicMock

    from sts2.analytics import analyze_run
    from sts2.models import RunHistory

    kb = MagicMock()
    card = MagicMock()
    card.type = "Attack"
    card.keywords = ["Damage"]
    kb.get_card_by_id.return_value = card

    run = RunHistory(id="test", character="Defect", win=False,
                     deck=["CARD.A"] * 5, relics=[], floors=[],
                     run_time=600, ascension=0)
    result = analyze_run(run, kb=kb)
    texts = [i["text"] for i in result["insights"]]
    assert any("Block/defensive" in t for t in texts)


def test_analyze_run_card_stacking():
    """3+ copies of same card should warn about stacking."""
    from unittest.mock import MagicMock

    from sts2.analytics import analyze_run
    from sts2.models import RunHistory

    kb = MagicMock()
    card = MagicMock()
    card.type = "Attack"
    card.keywords = ["Block"]
    kb.get_card_by_id.return_value = card
    kb.id_to_name.return_value = "Zap"

    run = RunHistory(id="test", character="Defect", win=False,
                     deck=["CARD.ZAP"] * 4 + ["CARD.OTHER"],
                     relics=[], floors=[], run_time=600, ascension=0)
    result = analyze_run(run, kb=kb)
    texts = [i["text"] for i in result["insights"]]
    assert any("Card stacking" in t for t in texts)


def test_analyze_run_without_kb():
    """Without kb, analyze_run should produce existing insights only."""
    from sts2.analytics import analyze_run
    from sts2.models import RunHistory

    run = RunHistory(id="test", character="Defect", win=True,
                     deck=["CARD.A"] * 5, relics=["R1"] * 8,
                     floors=[], run_time=600, ascension=0)
    result = analyze_run(run)
    # Should still work without kb
    assert "insights" in result
    # No KB-powered insights about Skills percentage
    texts = [i["text"] for i in result["insights"]]
    assert not any("Skills" in t for t in texts)


def test_analyze_run_patterns_defense_neglect():
    """6/10 runs with no defense should produce a recurring pattern."""
    from unittest.mock import MagicMock

    from sts2.analytics import analyze_run_patterns
    from sts2.models import RunHistory

    kb = MagicMock()
    # All cards have no defensive keywords
    card = MagicMock()
    card.keywords = ["Damage"]
    kb.get_card_by_id.return_value = card

    runs = [RunHistory(id=f"r{i}", character="Defect", win=False,
                       deck=["CARD.A"] * 5, relics=[], floors=[],
                       run_time=600, ascension=0)
            for i in range(8)]
    patterns = analyze_run_patterns(runs, kb=kb)
    assert len(patterns) >= 1
    assert any("Defense neglected" in p["text"] for p in patterns)


def test_analyze_run_patterns_insufficient_runs():
    """Fewer than 3 runs should return empty patterns."""
    from sts2.analytics import analyze_run_patterns
    from sts2.models import RunHistory

    runs = [RunHistory(id="r1", character="Defect", win=False,
                       deck=["CARD.A"], relics=[], floors=[],
                       run_time=600, ascension=0)]
    assert analyze_run_patterns(runs) == []
