"""Playwright browser integration tests.

These tests require Playwright browsers to be installed:
    pip install .[browser]
    playwright install chromium

Run with: pytest -m browser
Skipped automatically during normal 'pytest -q' runs.
"""
import json
import os
import socket
import threading
import time

import pytest

pytestmark = pytest.mark.browser

try:
    from playwright.sync_api import expect
except ImportError:
    pytest.skip("Playwright not installed", allow_module_level=True)


@pytest.fixture(scope="module")
def live_server(tmp_path_factory):
    """Start a real HTTP server for Playwright browser tests."""
    from sts2.app import app

    save_dir = tmp_path_factory.mktemp("saves")
    progress = {
        "character_stats": {},
        "card_stats": {},
        "encounter_stats": {},
        "enemy_stats": {},
        "discovered_cards": [],
        "discovered_relics": [],
        "discovered_potions": [],
        "discovered_events": [],
    }
    (save_dir / "progress.save").write_text(json.dumps(progress), encoding="utf-8")
    (save_dir / "history").mkdir()

    old_env = os.environ.get("STS2_SAVE_DIR")
    os.environ["STS2_SAVE_DIR"] = str(save_dir)

    # conftest sets STS2_HOST=0.0.0.0 so the rate-limit tests see an active
    # limiter, but the auth middleware reads the same variable at request time
    # and would then demand a token for every page. This server really is on
    # loopback, and the browser suite exists to exercise the zero-config
    # loopback deployment a player actually runs, so align the variable with
    # the socket for the fixture's lifetime. Without this every navigation
    # gets 401 while /health (exempt) still answers, so the fixture starts and
    # all 15 tests fail on their first assertion.
    old_host = os.environ.get("STS2_HOST")
    os.environ["STS2_HOST"] = "127.0.0.1"

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]

    base_url = f"http://127.0.0.1:{port}"

    import uvicorn
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    import urllib.error
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(f"{base_url}/health", timeout=1)
            break
        except (urllib.error.URLError, OSError):
            time.sleep(0.2)
    else:
        pytest.fail("Live server failed to start within 10 seconds")

    yield base_url

    server.should_exit = True
    thread.join(timeout=5)
    if old_env is None:
        os.environ.pop("STS2_SAVE_DIR", None)
    else:
        os.environ["STS2_SAVE_DIR"] = old_env
    if old_host is None:
        os.environ.pop("STS2_HOST", None)
    else:
        os.environ["STS2_HOST"] = old_host


class TestThemeToggle:
    """Theme persistence via localStorage."""

    def test_default_respects_system_preference(self, page, live_server):
        """With no localStorage, theme follows prefers-color-scheme."""
        # Force dark preference at the browser level
        page.emulate_media(color_scheme="dark")
        page.goto(live_server)
        assert page.locator("html").get_attribute("data-theme") == "dark"

        # Force light preference
        page.emulate_media(color_scheme="light")
        page.goto(live_server)
        assert page.locator("html").get_attribute("data-theme") == "light"

    def test_toggle_persists_across_reload(self, page, live_server):
        page.emulate_media(color_scheme="dark")
        page.goto(live_server)
        assert page.locator("html").get_attribute("data-theme") == "dark"

        page.click(".theme-toggle")
        assert page.locator("html").get_attribute("data-theme") == "light"

        # Reload — localStorage should override system preference
        page.reload()
        assert page.locator("html").get_attribute("data-theme") == "light"

    def test_toggle_cycles_both_directions(self, page, live_server):
        page.emulate_media(color_scheme="dark")
        page.goto(live_server)
        page.evaluate("localStorage.removeItem('theme')")
        page.reload()
        assert page.locator("html").get_attribute("data-theme") == "dark"

        page.click(".theme-toggle")
        assert page.locator("html").get_attribute("data-theme") == "light"

        page.click(".theme-toggle")
        assert page.locator("html").get_attribute("data-theme") == "dark"


class TestSearchUI:
    """Search form interaction."""

    def test_search_navigates_to_results(self, page, live_server):
        page.goto(live_server)
        search_input = page.locator("input[type='search']")
        search_input.fill("bash")
        search_input.press("Enter")

        # Should navigate to search results page
        page.wait_for_url("**/search?q=bash")
        assert "search" in page.url

    def test_search_shows_results(self, page, live_server):
        page.goto(f"{live_server}/search?q=strike")
        # Should have at least one result (Strike is a starter card)
        results = page.locator(".card-link")
        expect(results.first).to_be_visible(timeout=5000)


class TestPageNavigation:
    """Page loading and navigation."""

    def test_cards_page_loads(self, page, live_server):
        page.goto(f"{live_server}/cards")
        expect(page.locator("h1")).to_contain_text("Cards")
        # Should have card links
        expect(page.locator(".card-link").first).to_be_visible()

    def test_card_detail_loads(self, page, live_server):
        page.goto(f"{live_server}/cards")
        first_card = page.locator(".card-link").first
        first_card.click()
        # Should navigate to detail page with the card name
        expect(page.locator("h1")).to_be_visible()

    def test_relics_page_loads(self, page, live_server):
        page.goto(f"{live_server}/relics")
        expect(page.locator("h1")).to_contain_text("Relics")

    def test_enemies_page_loads(self, page, live_server):
        page.goto(f"{live_server}/enemies")
        expect(page.locator("h1")).to_contain_text("Enemies")

    def test_analytics_page_loads(self, page, live_server):
        page.goto(f"{live_server}/analytics")
        expect(page.locator("h1")).to_contain_text("Analytics")


class TestResponsiveLayout:
    """Responsive design at different viewports."""

    def test_desktop_nav_visible(self, page, live_server):
        page.set_viewport_size({"width": 1280, "height": 800})
        page.goto(live_server)
        expect(page.locator(".nav-links")).to_be_visible()

    def test_mobile_nav_hidden_then_toggle(self, page, live_server):
        page.set_viewport_size({"width": 375, "height": 667})
        page.goto(live_server)
        # Nav should be hidden on mobile
        expect(page.locator(".nav-links")).not_to_be_visible()
        # Toggle should make it visible
        page.click(".nav-toggle")
        expect(page.locator(".nav-links")).to_be_visible()


class TestWCAGContrast:
    """WCAG AA contrast ratio validation in rendered DOM."""

    @staticmethod
    def _check_contrast_js():
        """JS snippet to compute contrast ratio of text against nearest opaque background."""
        return """
        () => {
            function luminance(r, g, b) {
                const [rs, gs, bs] = [r, g, b].map(c => {
                    c = c / 255;
                    return c <= 0.03928 ? c / 12.92 : Math.pow((c + 0.055) / 1.055, 2.4);
                });
                return 0.2126 * rs + 0.7152 * gs + 0.0722 * bs;
            }
            function parseColor(str) {
                const m = str.match(/rgba?\\((\\d+),\\s*(\\d+),\\s*(\\d+)/);
                return m ? [+m[1], +m[2], +m[3]] : null;
            }
            function isOpaque(str) {
                if (!str || str === 'transparent' || str === 'rgba(0, 0, 0, 0)') return false;
                const m = str.match(/rgba\\((\\d+),\\s*(\\d+),\\s*(\\d+),\\s*([\\d.]+)/);
                return !m || parseFloat(m[4]) > 0.5;
            }
            function findBgColor(el) {
                let node = el;
                while (node && node !== document.documentElement) {
                    const bg = getComputedStyle(node).backgroundColor;
                    if (isOpaque(bg)) return parseColor(bg);
                    node = node.parentElement;
                }
                return parseColor(getComputedStyle(document.body).backgroundColor) || [255,255,255];
            }
            function contrastRatio(fg, bg) {
                const l1 = luminance(...fg) + 0.05;
                const l2 = luminance(...bg) + 0.05;
                return l1 > l2 ? l1 / l2 : l2 / l1;
            }

            const results = [];
            // Check content text elements (skip gradient-bg elements like active filters)
            const selectors = ['h1', 'h2', 'main p', '.card-link'];
            for (const sel of selectors) {
                const el = document.querySelector(sel);
                if (!el) continue;
                const fg = parseColor(getComputedStyle(el).color);
                if (!fg) continue;
                const bg = findBgColor(el);
                const ratio = contrastRatio(fg, bg);
                results.push({selector: sel, ratio: ratio, fg: fg, bg: bg});
            }
            return results;
        }
        """

    def test_dark_theme_contrast(self, page, live_server):
        page.emulate_media(color_scheme="dark")
        page.goto(f"{live_server}/cards")
        assert page.locator("html").get_attribute("data-theme") == "dark"
        results = page.evaluate(self._check_contrast_js())
        for r in results:
            assert r["ratio"] >= 4.5, (
                f"WCAG AA fail (dark): {r['selector']} has ratio {r['ratio']:.2f} "
                f"(fg={r['fg']}, bg={r['bg']})"
            )

    def test_light_theme_contrast(self, page, live_server):
        page.emulate_media(color_scheme="light")
        page.goto(f"{live_server}/cards")
        assert page.locator("html").get_attribute("data-theme") == "light"
        results = page.evaluate(self._check_contrast_js())
        for r in results:
            assert r["ratio"] >= 4.5, (
                f"WCAG AA fail (light): {r['selector']} has ratio {r['ratio']:.2f} "
                f"(fg={r['fg']}, bg={r['bg']})"
            )


class TestCardFiltering:
    """Card list filtering by character."""

    def test_character_filter(self, page, live_server):
        page.goto(f"{live_server}/cards?character=Ironclad")
        # All visible cards should be Ironclad (or Colorless)
        expect(page.locator("h1")).to_contain_text("Cards")
        # Should have filtered results
        expect(page.locator(".card-link").first).to_be_visible()


class TestLiveRevisionReload:
    """Same-floor deck/item changes must refresh the server-rendered lists.

    live.js used to reload only on an active or floor change, so a card
    reward, upgrade or potion change on the same floor updated the counters
    but left the lists and deck analysis stale. The page and stream are
    served from routes here so the real live.js can be driven through exact
    message sequences without a running game.
    """

    _PAGE = ('<!doctype html><html lang="en"><head><title>live</title></head><body>'
             '<div class="live-cards">0</div><div class="live-gold">0</div>'
             '<div id="live-config" data-player="0" data-was-active="true"'
             ' data-revision="{rev}"></div>'
             '<script src="/static/live.js"></script></body></html>')

    @staticmethod
    def _msg(rev, gold=10, deck=2):
        return "data: " + json.dumps({
            "active": True, "current_hp": 50, "max_hp": 80, "gold": gold,
            "act": 1, "floor": 5, "deck": ["CARD.BASH"] * deck,
            "relics": [], "potions": [], "revision": rev}) + "\n\n"

    def _drive(self, page, live_server, page_revs, streams):
        """Serve page_revs[i] / streams[i] to the i-th load / connection
        (the last entry repeats); return the list of page loads."""
        loads: list[str] = []
        conns: list[int] = []

        def serve_page(route):
            rev = page_revs[min(len(loads), len(page_revs) - 1)]
            loads.append(rev)
            route.fulfill(status=200, content_type="text/html",
                          body=self._PAGE.format(rev=rev))

        def serve_stream(route):
            body = streams[min(len(conns), len(streams) - 1)]
            conns.append(1)
            # A long retry keeps the ended stream from reconnecting inside
            # the test window.
            route.fulfill(status=200, content_type="text/event-stream",
                          headers={"Cache-Control": "no-cache"},
                          body="retry: 60000\n\n" + body)

        page.route(f"{live_server}/live-revision-test", serve_page)
        page.route("**/api/live/stream*", serve_stream)
        page.goto(f"{live_server}/live-revision-test")
        return loads

    def test_same_floor_content_change_reloads(self, page, live_server):
        loads = self._drive(page, live_server, ["aaa", "bbb"],
                            [self._msg("aaa") + self._msg("bbb", deck=3),
                             self._msg("bbb", deck=3)])
        page.wait_for_timeout(2500)
        assert loads == ["aaa", "bbb"]
        expect(page.locator(".live-cards")).to_have_text("3")

    def test_counter_only_change_does_not_reload(self, page, live_server):
        loads = self._drive(page, live_server, ["aaa"],
                            [self._msg("aaa", gold=10) + self._msg("aaa", gold=20)])
        expect(page.locator(".live-gold")).to_have_text("20")
        page.wait_for_timeout(2000)
        assert loads == ["aaa"]

    def test_persistent_page_stream_mismatch_reloads_once(self, page, live_server):
        loads = self._drive(page, live_server, ["aaa"], [self._msg("bbb")])
        page.wait_for_timeout(3000)
        assert loads == ["aaa", "aaa"]


def test_swagger_operations_render_offline_under_csp(page, live_server):
    errors = []
    requests = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
    page.on("request", lambda request: requests.append(request.url))
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(live_server) else route.abort())
    response = page.goto(live_server + "/docs")
    assert "script-src 'self'" in response.headers["content-security-policy"]
    expect(page.locator(".opblock").first).to_be_visible(timeout=10000)
    operation = page.locator(".opblock").filter(has=page.locator('[data-path="/health"]'))
    operation.locator(".opblock-summary").click()
    operation.get_by_role("button", name="Try it out").click()
    operation.get_by_role("button", name="Execute", exact=True).click()
    expect(operation.locator(".live-responses-table")).to_contain_text("200")
    assert all(url.startswith(live_server) for url in requests)
    assert errors == []


def test_saved_deck_retains_build_and_customized_copies(page, live_server):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(live_server + "/deck")
    record = {"version": 3, "game_version": "v0.107.1", "instances": [{
        "card_id": "CARD.MAD_SCIENCE", "upgrade_level": 1, "enchantment": "",
        "properties": {"ints": {"TinkerTimeType": 2, "TinkerTimeRider": 5}, "unmodeled": False},
    }]}
    page.evaluate("value => localStorage.setItem('spirescope_decks', JSON.stringify({Native: value}))", record)
    page.reload()
    page.locator("#load-deck").select_option("Native")
    page.wait_for_url("**/deck/analyze")
    expect(page.locator("#deck-game-version")).to_have_value("v0.107.1")
    expect(page.get_by_text("Innate. Gain 8 Block. Draw 3 cards.", exact=False)).to_be_visible()
    page.once("dialog", lambda dialog: dialog.accept("Saved copy"))
    page.locator("#save-deck").click()
    saved = page.evaluate("JSON.parse(localStorage.getItem('spirescope_decks'))")
    copy = next(value for key, value in saved.items() if key.endswith(" / Saved copy"))
    assert copy == record
    # Legacy decks carry no game-build evidence, even when loaded from a main view.
    page.evaluate("localStorage.setItem('spirescope_decks', JSON.stringify({Legacy: ['CARD.BASH']}))")
    # Open the builder as a new visit. Playwright Firefox reloads the POST
    # result as a GET to /deck/analyze, which correctly rejects that method.
    page.goto(live_server + "/deck")
    page.locator("#load-deck").select_option("Legacy")
    expect(page.locator("#deck-game-version")).to_have_value("")
    expect(page.get_by_text("Game version not verified; analysis uses the reference catalog.")).to_be_visible()
    assert errors == []
