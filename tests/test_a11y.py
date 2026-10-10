"""Accessibility and docs-site regressions (audit findings M24-M27).

Covers: the <html lang> attribute tracking the active UI language instead of
being hardcoded, the nav-toggle/shortcuts-dialog ARIA wiring, the
prefers-reduced-motion stylesheet block, and the docs/index.html landing page
(heading order, <main> landmark, canonical/og:url, and CTA contrast). Also
the theme toggle and the light theme's colour overrides and WCAG AA contrast.
"""
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _luminance(value):
    """Relative luminance of a #rrggbb colour (WCAG formula)."""
    parts = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    chan = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
    return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]


def _contrast_ratio(fg, bg):
    """WCAG contrast ratio between two #rrggbb colours. Mirrors the helper
    in tests/test_packaging.py's test_theme_text_colours_meet_wcag_aa."""
    a, b = _luminance(fg), _luminance(bg)
    hi, lo = max(a, b), min(a, b)
    return (hi + 0.05) / (lo + 0.05)


# ── M24/M25: <html lang> and nav/shortcuts ARIA wiring ──

async def test_html_lang_reflects_active_language(client, monkeypatch):
    """get_language() (sts2/i18n.py) has STS2_LANG win over the persisted
    setting; base.html must read it live via ui_lang() each render rather
    than hardcode lang="en"."""
    monkeypatch.setenv("STS2_LANG", "de")
    resp = await client.get("/")
    assert resp.status_code == 200
    assert '<html lang="de"' in resp.text
    assert '<html lang="en"' not in resp.text


async def test_nav_toggle_has_expanded_state_and_controls_target(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'aria-expanded="false"' in resp.text
    assert 'aria-controls="nav-links"' in resp.text
    assert 'id="nav-links"' in resp.text


async def test_search_input_has_an_accessible_name(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert re.search(r'<input type="search"[^>]*aria-label="[^"]+"', resp.text)


async def test_shortcuts_overlay_is_a_labelled_dialog(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'id="shortcut-overlay"' in resp.text
    assert 'role="dialog"' in resp.text
    assert 'aria-modal="true"' in resp.text
    assert 'aria-labelledby="shortcut-overlay-title"' in resp.text
    assert 'id="shortcut-overlay-title"' in resp.text


async def test_shortcuts_overlay_has_a_visible_trigger(client):
    """M25 requires a visible '?' trigger, not just the '?' keyboard shortcut."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert 'class="shortcuts-btn"' in resp.text
    assert 'aria-controls="shortcut-overlay"' in resp.text


def test_shortcuts_js_traps_focus_and_restores_it_on_close():
    js = (PROJECT_ROOT / "sts2" / "static" / "shortcuts.js").read_text(encoding="utf-8")
    assert "Tab" in js, "no Tab handling — focus trap is missing"
    assert ".focus()" in js
    # An element must be recorded before opening so it can be refocused on close.
    assert "document.activeElement" in js


# ── M25: reduced motion + deck touch targets ──

def test_style_css_has_reduced_motion_block():
    css = (PROJECT_ROOT / "sts2" / "static" / "style.css").read_text(encoding="utf-8")
    assert "@media (prefers-reduced-motion: reduce)" in css


def test_deck_qty_button_touch_target_is_at_least_32px():
    css = (PROJECT_ROOT / "sts2" / "static" / "style.css").read_text(encoding="utf-8")
    match = re.search(r"\.qty-btn\s*\{([^}]*)\}", css)
    assert match, ".qty-btn rule not found"
    height_match = re.search(r"min-height:\s*(\d+)px", match.group(1))
    assert height_match, ".qty-btn has no min-height set"
    assert int(height_match.group(1)) >= 32


# ── M26: docs/index.html (GitHub Pages landing page) ──

def test_docs_index_wraps_content_in_main():
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert "<main" in html
    assert "</main>" in html


def test_docs_index_has_canonical_and_og_url():
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    assert 'rel="canonical"' in html
    assert 'property="og:url"' in html


def test_docs_index_og_image_resolves_under_the_pages_url():
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    match = re.search(r'property="og:image" content="([^"]+)"', html)
    assert match, "og:image not found"
    assert match.group(1).startswith("https://thequantumfalcon.github.io/spirescope/")


def test_docs_index_heading_order_has_no_skip():
    """No h(n+1) may appear before an h(n) has appeared (h1 -> h2 -> h3, ...).

    Regression for the old h1 -> h3 skip: the feature cards used to jump
    straight from the page's only h1 to five h3s with no h2 in between.
    """
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    body = html.split("<body", 1)[1]
    levels = [int(m.group(1)) for m in re.finditer(r"<h([1-6])[ >]", body)]
    assert levels, "no headings found in docs/index.html"
    seen_max = 0
    for level in levels:
        assert level <= seen_max + 1, (
            f"heading level jumps to h{level} with max seen so far h{seen_max}")
        seen_max = max(seen_max, level)


def test_docs_index_cta_meets_wcag_aa_contrast():
    """The 'Download for Windows' CTA is white text on a two-stop gradient;
    both stops must individually clear WCAG AA's 4.5:1 for normal text (the
    lighter stop measured 3.97:1 before the fix)."""
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    match = re.search(
        r"\.download\s*\{[^}]*background:\s*linear-gradient\(135deg,\s*"
        r"(#[0-9a-fA-F]{6}),\s*(#[0-9a-fA-F]{6})\)", html)
    assert match, "CTA gradient not found in docs/index.html"
    white = "#ffffff"
    for stop in match.groups():
        ratio = _contrast_ratio(white, stop)
        assert ratio >= 4.5, f"CTA stop {stop} on white = {ratio:.2f}:1, below WCAG AA"


def test_docs_index_screenshots_have_dimensions_and_lazy_loading():
    html = (PROJECT_ROOT / "docs" / "index.html").read_text(encoding="utf-8")
    for src in ("screenshot-dashboard.png", "screenshot-cards.png", "screenshot-live.png"):
        tag_match = re.search(rf'<img src="{re.escape(src)}"[^>]*>', html)
        assert tag_match, f"{src} img tag not found"
        tag = tag_match.group(0)
        assert re.search(r'width="\d+"', tag), f"{src} missing width"
        assert re.search(r'height="\d+"', tag), f"{src} missing height"
        assert 'loading="lazy"' in tag, f"{src} missing loading=lazy"


# ── Theme toggle and light theme ──

class TestTheme:
    def test_theme_init_js_exists(self):
        from sts2.config import STATIC_DIR
        assert (STATIC_DIR / "theme-init.js").exists()

    async def test_base_has_theme_toggle(self, client):
        resp = await client.get("/")
        assert resp.status_code == 200
        assert "theme-init.js" in resp.text
        assert "theme-toggle" in resp.text

    def test_css_has_light_theme(self):
        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        assert '[data-theme="light"]' in css
        # The light theme must override the character and status colours, but
        # pin the names rather than the hex values: the old version hardcoded
        # three literals and annotated them "WCAG-safe" when --ironclad
        # #c0392b actually measured 4.30:1 on --bg3. Contrast is verified for
        # real, across every colour and background, in
        # test_theme_text_colours_meet_wcag_aa.
        import re
        block = re.search(r'\[data-theme="light"\]\s*\{([^}]+)\}', css)
        assert block, "no light theme block"
        for name in ("--regent", "--silent", "--ironclad", "--yellow", "--red"):
            assert f"{name}:" in block.group(1), f"light theme does not override {name}"

    def test_css_card_bg_not_circular(self):
        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        # Should NOT have --card-bg: var(--card-bg) (circular reference)
        assert "--card-bg: var(--card-bg)" not in css


# ── WCAG AA contrast of the light theme's colours ──

class TestWCAGContrast:
    """Verify light theme color pairs meet WCAG AA (4.5:1 for normal text)."""

    LIGHT_BG = "#f5f0e8"
    # All text/accent colors from [data-theme="light"] CSS block
    # Read from the stylesheet rather than restated here. The hardcoded
    # version listed 8 of 17 colours and omitted --yellow, which shipped at
    # 4.07:1 — the list itself was the blind spot.
    @staticmethod
    def _light_colours() -> list[tuple[str, str]]:
        import re

        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        block = re.search(r'\[data-theme="light"\]\s*\{([^}]+)\}', css)
        assert block, "no light theme block"
        found = re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1))
        skip = {"bg", "bg2", "bg3", "border", "card-bg", "nav-bg", "accent2"}
        return [(f"--{n}", v) for n, v in found if n not in skip]

    def test_all_text_colors_pass_wcag_aa(self):
        """All light-theme text/accent colors must have >= 4.5:1 contrast on bg."""
        failures = []
        for name, color in self._light_colours():
            ratio = _contrast_ratio(color, self.LIGHT_BG)
            if ratio < 4.5:
                failures.append(f"{name} ({color}): {ratio:.2f}:1 < 4.5:1")
        assert not failures, "WCAG AA contrast failures:\n" + "\n".join(failures)

    def test_contrast_ratio_math(self):
        """Sanity check: black on white should be ~21:1."""
        ratio = _contrast_ratio("#000000", "#ffffff")
        assert 20.9 < ratio < 21.1

    def test_light_theme_colors_parsed_from_css(self):
        """Verify the CSS file actually contains the colors we're testing."""
        import re

        from sts2.config import STATIC_DIR
        css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
        # Find the [data-theme="light"] block
        match = re.search(r'\[data-theme="light"\]\s*\{([^}]+)\}', css)
        assert match, "No [data-theme='light'] block in CSS"
        block = match.group(1)
        for name, expected_color in self._light_colours():
            assert expected_color in block, f"{name}: {expected_color} not found in light theme CSS"
