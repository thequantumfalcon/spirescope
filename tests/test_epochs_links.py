"""The selected character filter on /epochs keeps its character class.

The link emitted two class attributes when selected; browsers keep only the
first, so the selected link lost char-<name>.
"""
from html.parser import HTMLParser
from unittest.mock import AsyncMock, patch

from sts2.models import PlayerProgress


class _Anchors(HTMLParser):
    """Raw attribute lists of every <a>, duplicates included."""

    def __init__(self):
        super().__init__()
        self.anchors = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.anchors.append(attrs)


async def test_selected_character_link_has_one_class_attribute(client):
    progress = PlayerProgress(epochs=[])
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=progress)):
        resp = await client.get("/epochs?category=character&character=Ironclad")
    assert resp.status_code == 200
    parser = _Anchors()
    parser.feed(resp.text)
    links = [attrs for attrs in parser.anchors
             if ("href", "/epochs?category=character&character=Ironclad") in attrs]
    assert len(links) == 1
    classes = [value for name, value in links[0] if name == "class"]
    assert len(classes) == 1
    assert set(classes[0].split()) == {"active", "char-ironclad"}


async def test_no_anchor_on_the_epochs_page_repeats_an_attribute(client):
    progress = PlayerProgress(epochs=[])
    with patch("sts2.app._get_progress", new=AsyncMock(return_value=progress)):
        resp = await client.get("/epochs?category=character&character=Silent")
    parser = _Anchors()
    parser.feed(resp.text)
    for attrs in parser.anchors:
        names = [name for name, _ in attrs]
        assert len(names) == len(set(names)), attrs


def test_the_epoch_header_uses_classes_the_stylesheet_defines():
    """The header used flex-between, flex-center and mb-0, none of which
    existed, so the name and category tag were never laid out as intended."""
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[1] / "sts2"
    css = (root / "static" / "style.css").read_text(encoding="utf-8")
    defined = set(re.findall(r"\.([A-Za-z][\w-]*)", css))
    template = (root / "templates" / "epochs.html").read_text(encoding="utf-8")
    header = re.search(r'<div class="(flex [^"]*)">\s*<h3 class="([^"]*)"', template)
    assert header, "epoch card header not found"
    used = set(header.group(1).split()) | set(header.group(2).split())
    assert used <= defined, sorted(used - defined)

