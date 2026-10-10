"""Inline styles are kept to data-driven sizes.

Project convention: presentation lives in CSS classes; a style attribute is
only for a width, height or flex weight computed from data. Fixed colours,
borders, display and grid columns had crept into templates and into HTML
built by deck.js.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES = ROOT / "sts2" / "templates"
STATIC = ROOT / "sts2" / "static"

_DATA_PROPERTIES = {"width", "height", "flex"}


def _style_attributes(text):
    return re.findall(r'\sstyle="([^"]*)"', text)


def test_template_inline_styles_are_only_data_driven_sizes():
    offenders = []
    for path in sorted(TEMPLATES.glob("*.html")):
        for style in _style_attributes(path.read_text(encoding="utf-8")):
            for declaration in filter(None, (d.strip() for d in style.split(";"))):
                prop, _, value = declaration.partition(":")
                if prop.strip() not in _DATA_PROPERTIES or "{{" not in value:
                    offenders.append(f"{path.name}: {declaration}")
    assert not offenders, "inline styles that belong in style.css:\n" + "\n".join(offenders)


def test_scripts_do_not_build_inline_styles():
    for path in sorted(STATIC.glob("*.js")):
        assert 'style="' not in path.read_text(encoding="utf-8"), path.name


def test_classes_used_in_place_of_inline_styles_are_defined():
    css = (STATIC / "style.css").read_text(encoding="utf-8")
    for selector in (".bg-green", ".bg-yellow", ".bg-red", ".bg-muted",
                     ".card.card-edge-green", ".card.card-edge-crimson", ".card.card-edge-gold",
                     ".stat-grid.stat-grid--3", ".stat-grid.stat-grid--4", ".stat-grid.stat-grid--5",
                     ".tag-tier", ".hp-bg--full", ".w-5em", ".w-30em", ".min-w-60", ".inline",
                     ".flex-1", ".sr-only"):
        assert re.search(re.escape(selector) + r"[\s,{:]", css), selector
    overlay = (TEMPLATES / "overlay.html").read_text(encoding="utf-8")
    assert re.search(r"\.danger-warning\s*\{", overlay)
