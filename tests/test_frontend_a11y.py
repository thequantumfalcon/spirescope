"""Accessible names, controls and text alternatives in the rendered pages.

Covers the import control that was display:none behind a non-focusable label,
section headings that had role="button" (erasing heading semantics), inputs
named only by a placeholder or a title, information carried only by colour
or a hover title, and the shortcuts dialog's close button.
"""
import re
from html.parser import HTMLParser
from unittest.mock import AsyncMock, patch

import sts2.app
from sts2.analytics import compute_analytics
from sts2.models import PlayerProgress, RunFloor, RunHistory


class _Elements(HTMLParser):
    """Every start tag with its attributes, in document order."""

    def __init__(self):
        super().__init__()
        self.elements = []

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, attrs))


def _elements(html):
    parser = _Elements()
    parser.feed(html)
    return [(tag, dict(attrs)) for tag, attrs in parser.elements]


def _by_id(html, element_id):
    matches = [(tag, attrs) for tag, attrs in _elements(html) if attrs.get("id") == element_id]
    assert len(matches) == 1, f"expected one #{element_id}, found {len(matches)}"
    return matches[0]


async def test_import_run_input_is_reachable_by_keyboard(client):
    resp = await client.get("/runs")
    assert resp.status_code == 200
    tag, attrs = _by_id(resp.text, "import-file")
    assert tag == "input" and attrs["type"] == "file"
    assert "style" not in attrs
    assert "hidden" not in attrs
    assert "tabindex" not in attrs
    assert "sr-only" in attrs["class"].split()
    # The label follows the input so the focus ring can be drawn on it.
    assert re.search(r'id="import-file"[^>]*>\s*<label for="import-file"', resp.text)


async def test_section_headings_keep_heading_semantics_with_a_button_inside(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    headers = re.findall(r'<h3 class="deck-section-header[^"]*"[^>]*>(.*?)</h3>', resp.text, flags=re.S)
    assert headers
    for body in headers:
        assert re.search(r'<button type="button" class="deck-section-toggle" aria-expanded="(true|false)">', body)
    assert not re.search(r'<h3[^>]*role="button"', resp.text)


async def test_collections_headings_have_a_button_inside(client):
    progress = PlayerProgress(discovered_cards=["CARD.BASH"])
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=progress)):
        resp = await client.get("/collections")
    assert resp.status_code == 200
    assert 'class="deck-section-toggle" aria-expanded="true"' in resp.text
    assert not re.search(r'<h3[^>]*role="button"', resp.text)


async def test_deck_builder_controls_have_accessible_names(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    assert _by_id(resp.text, "deck-search")[1].get("aria-label")
    assert _by_id(resp.text, "load-deck")[1].get("aria-label")


async def test_card_rarity_is_also_given_as_text(client):
    resp = await client.get("/deck")
    assert resp.status_code == 200
    labels = re.findall(r'<span class="card-label">(.*?)</span> \(', resp.text)
    with_rarity = [label for label in labels if re.search(r'rarity-[a-z]+"', label)]
    assert with_rarity
    assert all('<span class="sr-only">' in label for label in with_rarity)
    assert re.search(r'<span class="sr-only">(Common|Uncommon|Rare|Starter) rarity</span>', resp.text)


async def test_date_filters_have_accessible_names(client):
    resp = await client.get("/runs")
    assert resp.status_code == 200
    dates = [attrs for tag, attrs in _elements(resp.text)
             if tag == "input" and attrs.get("type") == "date"]
    assert [d.get("aria-label") for d in dates] == ["From date", "To date"]


async def test_heatmap_cells_carry_their_numbers_as_text(client):
    stats = compute_analytics([])
    stats["overview"]["total"] = 1
    stats["card_pick_rates"] = [{"id": "CARD.BASH", "pick_rate": 60, "picked": 3, "offered": 5}]
    stats["card_quality"] = [{"id": "CARD.BASH", "pick_rate": 60, "win_rate": 70,
                              "picked": 3, "offered": 5}]
    with patch("sts2.app._get_analytics", new=AsyncMock(return_value=stats)), \
            patch("sts2.app._get_runs", new=AsyncMock(return_value=[])):
        resp = await client.get("/analytics")
    assert resp.status_code == 200
    cell = re.search(r'<a href="/cards/CARD.BASH" class="heatmap-cell ([^"]*)"[^>]*>(.*?)</a>',
                     resp.text, flags=re.S)
    assert cell
    assert cell.group(1).strip() == "bg-green"
    name = sts2.app.kb.id_to_name("CARD.BASH")
    assert f'<span class="sr-only">{name}: 60% pick, 70% win</span>' in cell.group(2)


async def test_run_timeline_columns_carry_their_details_as_text(client):
    run = RunHistory(id="timeline-run", character="Ironclad", win=False, deck=["CARD.BASH"],
                     floors=[RunFloor(floor=1, current_hp=80, max_hp=80),
                             RunFloor(floor=2, current_hp=50, max_hp=80, damage_taken=30,
                                      cards_picked=["CARD.BASH"])])
    with patch("sts2.app._get_run_by_id", new=AsyncMock(return_value=run)):
        resp = await client.get("/runs/timeline-run")
    assert resp.status_code == 200
    assert '<span class="sr-only">Floor 1: 80/80 HP</span>' in resp.text
    name = sts2.app.kb.id_to_name("CARD.BASH")
    assert f'<span class="sr-only">Floor 2: 50/80 HP, lost 30 HP, picked {name}</span>' in resp.text
    assert re.search(r'<div class="timeline-marker timeline-hit" title="-30 HP">', resp.text)


async def test_shortcuts_dialog_has_a_close_button(client):
    resp = await client.get("/")
    assert resp.status_code == 200
    dialog = resp.text.split('id="shortcut-overlay"', 1)[1].split("</table>", 1)[0]
    assert re.search(r'<button type="button" class="shortcut-close" aria-label="[^"]+">', dialog)
