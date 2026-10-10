"""Exported run pages carry the app stylesheet verbatim.

The HTML export inlines static/style.css into a <style> element. It used to
be rendered through autoescaping, so quotes became &#39;/&#34; and ">" became
&gt;. Browsers do not decode entities inside <style>, so the fonts, the
@font-face rules, child selectors and every [data-theme="light"] rule dropped
out of each exported file.
"""
import re
from html.parser import HTMLParser
from unittest.mock import AsyncMock, patch

from sts2.config import STATIC_DIR
from sts2.models import RunHistory


def _style_blocks(html):
    return re.findall(r"<style>(.*?)</style>", html, flags=re.S)


class _StartTags(HTMLParser):
    """Element start tags as an HTML parser sees them: <style> content is
    raw text, so tags inside it only count if the element ended early."""

    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)


async def _export(client, run_id="style-run"):
    run = RunHistory(id=run_id, character="Ironclad", win=True, deck=["CARD.BASH"])
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
        resp = await client.get(f"/runs/{run_id}/export/html")
    assert resp.status_code == 200
    return resp.text


async def test_exported_stylesheet_is_raw_css(client):
    html = await _export(client)
    blocks = _style_blocks(html)
    assert len(blocks) == 1
    style = blocks[0]
    assert "font-family: 'Cinzel'" in style
    assert '[data-theme="light"]' in style
    assert ".home-hero > *" in style
    for entity in ("&#39;", "&#34;", "&gt;", "&lt;", "&amp;", "&quot;"):
        assert entity not in style, f"{entity} inside <style>"


async def test_exported_stylesheet_matches_the_app_stylesheet(client):
    html = await _export(client)
    css = (STATIC_DIR / "style.css").read_text(encoding="utf-8")
    assert css.strip() in _style_blocks(html)[0]


async def test_closing_style_tag_in_the_stylesheet_cannot_end_the_element(client, tmp_path):
    (tmp_path / "style.css").write_text(
        'a::after { content: "</STYLE><script>alert(1)</script>"; }\n'
        "/* </style> */\nbody { color: red; }\n", encoding="utf-8")
    with patch("sts2.config.STATIC_DIR", tmp_path):
        html = await _export(client, "style-run-2")
    head = html.split("<body>", 1)[0]
    assert head.lower().count("</style") == 1
    parser = _StartTags()
    parser.feed(html)
    assert "script" not in parser.tags
    assert "body { color: red; }" in _style_blocks(html)[0]
