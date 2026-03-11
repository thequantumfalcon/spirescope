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
