"""Browser regressions for the dashboard's front-end scripts.

Live-run reconnection (backoff, the server's too_many refusal), the OBS
overlay's idle timeout, the shortcuts dialog, keyboard access to the import
control and section toggles, blocked storage, malformed saved decks,
auto-submitting filters and the copy-seed fallback.

Run with: pytest -m browser
"""
import json
import os
import re
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
    """Start a real HTTP server for Playwright browser tests (same pattern
    as tests/test_browser.py: an empty save tree and a loopback bind)."""
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
    # conftest binds 0.0.0.0, which makes the auth middleware demand a token;
    # this server really is on loopback, so align the variable with it.
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


def _sse(payload=None, event=None):
    lines = []
    if event:
        lines.append(f"event: {event}")
    lines.append("data: " + json.dumps(payload if payload is not None else {}))
    return "\n".join(lines) + "\n\n"


def _run_msg(gold=0):
    return _sse({"active": False, "current_hp": 0, "max_hp": 0, "gold": gold, "act": 1,
                 "floor": 0, "deck": [], "relics": [], "potions": []})


def _count_loads(page, url_pattern):
    loads = []

    def handle(route):
        loads.append(route.request.url)
        route.continue_()

    page.route(url_pattern, handle)
    return loads


def _serve_stream(page, responders):
    """Answer the i-th live-stream request with responders[i] (the last one
    repeats); returns the list of requests seen."""
    conns = []

    def handle(route):
        responder = responders[min(len(conns), len(responders) - 1)]
        conns.append(route.request.url)
        responder(route)

    page.route("**/api/live/stream*", handle)
    return conns


def _abort(route):
    route.abort()


def _real_server(route):
    route.continue_()


class TestLiveConnection:
    """live.js used to reload the whole page 10 s after any stream error, with
    no backoff or cap. A refused stream is not retried by EventSource, so the
    page reloaded every 10 s forever; a stopped server swapped the page for
    the browser's error page; the server's own too_many refusal was ignored."""

    def test_too_many_shows_a_message_and_stops(self, page, live_server):
        loads = _count_loads(page, re.compile(r".*/live$"))
        conns = _serve_stream(page, [lambda route: route.fulfill(
            status=200, content_type="text/event-stream",
            body=_sse({"reason": "too_many"}, event="error"))])
        page.clock.install()
        page.goto(f"{live_server}/live")
        status = page.locator("#live-connection")
        expect(status).to_be_visible()
        expect(status).to_contain_text("too many live pages are open")
        page.clock.run_for(30 * 60 * 1000)
        page.wait_for_timeout(500)
        assert len(conns) == 1
        assert len(loads) == 1

    def test_lost_connection_backs_off_then_gives_up(self, page, live_server):
        loads = _count_loads(page, re.compile(r".*/live$"))
        conns = _serve_stream(page, [_abort])
        page.clock.install()
        page.goto(f"{live_server}/live")
        status = page.locator("#live-connection")
        delays = [5, 10, 20, 40, 60, 60, 60, 60]
        for attempt, delay in enumerate(delays, start=1):
            expect(status).to_have_text(
                f"Lost the connection to Spirescope. Retrying in {delay} s.")
            assert len(conns) == attempt
            page.clock.run_for(delay * 1000)
        expect(status).to_contain_text("Reload the page to try again")
        assert len(conns) == len(delays) + 1
        page.clock.run_for(30 * 60 * 1000)
        page.wait_for_timeout(500)
        assert len(conns) == len(delays) + 1
        assert len(loads) == 1

    def test_recovered_stream_clears_the_message(self, page, live_server):
        loads = _count_loads(page, re.compile(r".*/live$"))
        conns = _serve_stream(page, [_abort, _real_server])
        page.clock.install()
        page.goto(f"{live_server}/live")
        status = page.locator("#live-connection")
        expect(status).to_have_text("Lost the connection to Spirescope. Retrying in 5 s.")
        page.clock.run_for(5000)
        expect(status).to_be_hidden()
        assert len(conns) == 2
        assert len(loads) == 1


class TestOverlayStream:
    """The OBS overlay had no 'timeout' listener: the server ends a quiet
    stream after 5 minutes, the resulting error scheduled a reload, and data
    arriving afterwards never cancelled it."""

    _PAGE = ('<!doctype html><html lang="en"><head><title>overlay</title></head><body>'
             '<b class="live-gold">-</b><script src="/static/overlay.js"></script></body></html>')

    def _open(self, page, live_server, responders):
        loads = []

        def serve_page(route):
            loads.append(route.request.url)
            route.fulfill(status=200, content_type="text/html", body=self._PAGE)

        page.route(f"{live_server}/overlay-test", serve_page)
        conns = _serve_stream(page, responders)
        page.clock.install()
        page.goto(f"{live_server}/overlay-test")
        return loads, conns

    def test_idle_timeout_reconnects_without_reloading(self, page, live_server):
        loads, conns = self._open(page, live_server, [
            lambda route: route.fulfill(status=200, content_type="text/event-stream",
                                        body=_run_msg(gold=10) + _sse(event="timeout")),
            _real_server])
        gold = page.locator(".live-gold")
        expect(gold).to_have_text("10")
        page.clock.run_for(6000)
        page.wait_for_timeout(500)
        assert len(loads) == 1
        assert len(conns) == 1
        page.clock.run_for(10000)
        expect(gold).to_have_text("0")
        assert len(conns) == 2
        page.clock.run_for(60000)
        page.wait_for_timeout(500)
        assert len(loads) == 1

    def test_data_after_an_error_cancels_the_pending_reload(self, page, live_server):
        loads, conns = self._open(page, live_server, [
            lambda route: route.fulfill(status=200, content_type="text/event-stream",
                                        body="retry: 300\n\n" + _run_msg(gold=10)),
            _real_server])
        gold = page.locator(".live-gold")
        expect(gold).to_have_text("0")
        assert len(conns) == 2
        page.clock.run_for(10000)
        page.wait_for_timeout(500)
        assert len(loads) == 1


class TestShortcutsDialog:
    """The dialog covers the page, including the '?' button, and closed only
    on Escape, so touch users could not dismiss it."""

    def test_close_button_closes_and_returns_focus(self, page, live_server):
        page.goto(live_server)
        page.click(".shortcuts-btn")
        dialog = page.locator("#shortcut-overlay")
        expect(dialog).to_be_visible()
        page.click(".shortcut-close")
        expect(dialog).to_be_hidden()
        assert page.evaluate("document.activeElement.className") == "shortcuts-btn"

    def test_backdrop_click_closes_but_panel_click_does_not(self, page, live_server):
        page.goto(live_server)
        page.click(".shortcuts-btn")
        dialog = page.locator("#shortcut-overlay")
        page.click("#shortcut-overlay-title")
        expect(dialog).to_be_visible()
        dialog.click(position={"x": 5, "y": 5})
        expect(dialog).to_be_hidden()

    def test_letters_do_not_navigate_while_the_dialog_is_open(self, page, live_server):
        page.goto(live_server + "/relics")
        page.keyboard.press("?")
        expect(page.locator("#shortcut-overlay")).to_be_visible()
        page.keyboard.press("c")
        page.wait_for_timeout(500)
        assert page.url.endswith("/relics")
        expect(page.locator("#shortcut-overlay")).to_be_visible()

    def test_slash_keeps_focus_in_the_open_dialog_on_the_deck_page(self, page, live_server):
        """deck.js has its own '/' shortcut; it must not pull focus out from
        behind the open shortcuts dialog."""
        page.goto(live_server + "/deck")
        page.keyboard.press("?")
        expect(page.locator("#shortcut-overlay")).to_be_visible()
        page.keyboard.press("/")
        page.wait_for_timeout(200)
        assert page.evaluate("document.activeElement.id") != "deck-search"
        assert page.evaluate(
            "document.getElementById('shortcut-overlay').contains(document.activeElement)")

    def test_letters_do_not_navigate_from_a_section_header(self, page, live_server):
        page.goto(live_server + "/deck")
        page.locator(".deck-section-toggle").first.focus()
        page.keyboard.press("c")
        page.wait_for_timeout(500)
        assert page.url.endswith("/deck")


class TestKeyboardAccess:
    def test_import_run_input_takes_keyboard_focus(self, page, live_server):
        page.goto(live_server + "/runs")
        page.focus("#import-file")
        assert page.evaluate("document.activeElement.id") == "import-file"
        # The input is visually hidden, so its label shows the focus ring.
        outline = page.evaluate(
            "getComputedStyle(document.querySelector('label[for=\"import-file\"]')).outlineStyle")
        assert outline == "solid"

    def test_section_toggle_is_a_button_that_reports_its_state(self, page, live_server):
        page.goto(live_server + "/deck")
        toggle = page.locator(".deck-section-toggle").first
        section = page.locator(".deck-section").first
        expect(toggle).to_have_attribute("aria-expanded", "true")
        toggle.focus()
        page.keyboard.press("Enter")
        expect(toggle).to_have_attribute("aria-expanded", "false")
        expect(section).to_have_class(re.compile(r"\bcollapsed\b"))
        toggle.click()
        expect(toggle).to_have_attribute("aria-expanded", "true")
        expect(section).not_to_have_class(re.compile(r"\bcollapsed\b"))


class TestBlockedStorage:
    """Where storage access throws, theme-init aborted before setting
    data-theme and the toggle threw halfway through."""

    _BLOCK = ("Object.defineProperty(window, 'localStorage', {configurable: true, get: function() {"
              " throw new DOMException('The operation is insecure.', 'SecurityError'); }});")

    def test_theme_applies_and_toggles_without_storage(self, page, live_server):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script(self._BLOCK)
        page.emulate_media(color_scheme="light")
        page.goto(live_server)
        html = page.locator("html")
        assert html.get_attribute("data-theme") == "light"
        page.click(".theme-toggle")
        assert html.get_attribute("data-theme") == "dark"
        expect(page.locator(".theme-toggle")).to_have_attribute("aria-label", "Switch to light mode")
        assert errors == []


class TestStoredDecks:
    def test_malformed_saved_decks_do_not_disable_the_builder(self, page, live_server):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(live_server + "/deck")
        page.evaluate("""() => localStorage.setItem('spirescope_decks', JSON.stringify({
            'Bad / no instances': {version: 3, game_version: ''},
            'Bad / null': null,
            'Bad / bad copies': {version: 2, instances: [null]},
            'Good': {version: 3, game_version: '', instances: [
                {card_id: 'CARD.BASH', upgrade_level: 0, enchantment: ''}]}
        }))""")
        page.reload()
        options = page.locator("#load-deck option").all_text_contents()
        assert options == ["Load saved deck...", "Good (1 cards)"]
        card = page.locator(".deck-section").first.locator(".deck-card").first
        card.locator(".qty-plus").click()
        expect(card.locator(".qty-count")).to_have_text("1")
        expect(page.locator("#deck-count")).to_have_text("1 selected")
        assert errors == []


class TestAutoSubmit:
    """form.submit() skipped submit listeners (a js-confirm form never asked)
    and let a second change submit again."""

    _CHANGE = """(value) => {
        const input = document.querySelector('form.filter-bar input[name="from"]');
        input.value = value;
        input.dispatchEvent(new Event('change', {bubbles: true}));
    }"""

    def test_change_fires_submit_listeners_and_submits_once(self, page, live_server):
        page.goto(live_server + "/runs")
        count = page.evaluate("""() => {
            let count = 0;
            const form = document.querySelector('form.filter-bar');
            form.addEventListener('submit', () => { count++; });
            const input = form.querySelector('input[name="from"]');
            input.value = '2026-01-01';
            input.dispatchEvent(new Event('change', {bubbles: true}));
            input.dispatchEvent(new Event('change', {bubbles: true}));
            return count;
        }""")
        assert count == 1
        page.wait_for_url(re.compile(r".*/runs\?.*from=2026-01-01"))

    def test_cancelled_confirm_keeps_the_form_usable(self, page, live_server):
        page.goto(live_server + "/runs")
        page.evaluate("""() => {
            const form = document.querySelector('form.filter-bar');
            form.classList.add('js-confirm');
            form.setAttribute('data-confirm', 'Apply this filter?');
        }""")
        dialogs = []

        def answer(dialog):
            dialogs.append(dialog.message)
            if len(dialogs) < 3:
                dialog.dismiss()
            else:
                dialog.accept()

        page.on("dialog", answer)
        page.evaluate(self._CHANGE, "2026-01-01")
        page.evaluate(self._CHANGE, "2026-01-02")
        assert dialogs == ["Apply this filter?", "Apply this filter?"]
        assert page.url.endswith("/runs")
        page.evaluate(self._CHANGE, "2026-01-03")
        page.wait_for_url(re.compile(r".*/runs\?.*from=2026-01-03"))
        assert len(dialogs) == 3


class TestCopySeed:
    """On a plain-http LAN origin navigator.clipboard does not exist, and a
    browser may refuse the write; the button used to do nothing either way."""

    _PAGE = ('<!doctype html><html lang="en"><head><title>seed</title></head><body>'
             '<p>Seed: <span id="seed-text">ABC123</span> '
             '<button class="copy-seed" data-seed="ABC123">Copy</button></p>'
             '<script src="/static/nav.js"></script></body></html>')

    def _open(self, page, live_server, clipboard_js):
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.add_init_script("Object.defineProperty(Navigator.prototype, 'clipboard',"
                             " {configurable: true, get: function() { return " + clipboard_js + "; }});")
        page.route(f"{live_server}/seed-test", lambda route: route.fulfill(
            status=200, content_type="text/html", body=self._PAGE))
        page.goto(f"{live_server}/seed-test")
        page.click(".copy-seed")
        return errors

    def test_without_the_clipboard_api_the_seed_is_selected(self, page, live_server):
        errors = self._open(page, live_server, "undefined")
        expect(page.locator(".copy-seed")).to_have_text(re.compile(r"^(Copied!|Seed selected)$"))
        assert page.evaluate("window.getSelection().toString()") == "ABC123"
        assert errors == []

    def test_a_refused_write_falls_back(self, page, live_server):
        errors = self._open(page, live_server,
                            "{writeText: function() { return Promise.reject(new Error('denied')); }}")
        expect(page.locator(".copy-seed")).to_have_text(re.compile(r"^(Copied!|Seed selected)$"))
        assert page.evaluate("window.getSelection().toString()") == "ABC123"
        assert errors == []


class TestStatNumberColours:
    """Colour classes on stat numbers (live HP danger, ghost ahead/behind,
    wins/losses) used to be painted over by the gold gradient fill."""

    @pytest.mark.parametrize("theme", ["dark", "light"])
    def test_colour_classes_show_on_stat_numbers(self, page, live_server, theme):
        page.goto(live_server + "/relics")
        page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
        fills = page.evaluate("""() => {
            const box = document.createElement('div');
            box.className = 'stat-box';
            box.innerHTML = '<div class="num text-red">1</div><div class="num win">2</div>'
                          + '<div class="num">3</div><span class="text-red">4</span>';
            document.body.appendChild(box);
            const fill = el => getComputedStyle(el).webkitTextFillColor;
            const [red, win, plain, ref] = box.children;
            return {red: fill(red), win: fill(win), plain: fill(plain),
                    ref: getComputedStyle(ref).color};
        }""")
        assert fills["red"] == fills["ref"], fills
        assert fills["win"] != fills["plain"], fills
        assert fills["red"] != fills["plain"], fills


class TestStopButton:
    def test_a_refused_stop_shows_the_server_reason(self, page, live_server):
        """/shutdown answers 409 with a JSON reason while a data update is
        installing; the page shows that reason instead of a bare status."""
        page.route("**/shutdown", lambda route: route.fulfill(
            status=409, content_type="application/json",
            body='{"error": "A game data update is being installed.", "status": 409}'))
        messages = []

        def on_dialog(dialog):
            messages.append(dialog.message)
            dialog.accept()

        page.on("dialog", on_dialog)
        page.goto(live_server + "/relics")
        page.click(".stop-btn")
        page.wait_for_timeout(500)
        assert any("A game data update is being installed." in m for m in messages), messages

