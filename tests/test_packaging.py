"""Packaging guards: the frozen build must ship every runtime resource.

Regression origin (issue #5): sts2/locales was added for i18n but never
added to the PyInstaller spec, so every packaged v3.0.0/v3.0.1 build
rendered raw translation keys ("nav.cards") in the navigation. Source runs
were fine, which is exactly why source-only testing missed it.
"""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
SPEC = PROJECT_ROOT / "spirescope.spec"
PKG = PROJECT_ROOT / "sts2"


def _resource_dirs() -> list[str]:
    """Package subdirectories holding runtime data rather than Python code."""
    dirs = []
    for path in sorted(PKG.iterdir()):
        if not path.is_dir() or path.name.startswith((".", "_")):
            continue
        has_py = any(path.glob("*.py"))
        has_data = any(p.is_file() and p.suffix != ".pyc" for p in path.iterdir())
        if has_data and not has_py:
            dirs.append(path.name)
    return dirs


def test_spec_bundles_every_runtime_resource_dir():
    """Any non-code directory under sts2/ must be in the spec's datas.

    Catches the whole class of bug: add a resource dir, forget the spec,
    ship a broken binary while every source-run test still passes.
    """
    spec = SPEC.read_text(encoding="utf-8")
    missing = [
        name for name in _resource_dirs()
        if f"'sts2/{name}', 'sts2/{name}'" not in spec
    ]
    assert not missing, (
        f"sts2/{{{','.join(missing)}}} exist but are not bundled in "
        f"spirescope.spec — frozen builds would ship without them"
    )


def test_resource_dirs_are_actually_discovered():
    """Guard the guard: if this returns nothing, the test above is vacuous."""
    found = _resource_dirs()
    assert {"data", "locales", "static", "templates"} <= set(found)


def test_locales_present_and_parseable():
    import json
    locales = sorted((PKG / "locales").glob("*.json"))
    assert locales, "no locale files"
    for path in locales:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "nav" in data, f"{path.name} missing nav section"


@pytest.mark.parametrize("key", ["nav.cards", "nav.live_run", "settings.title"])
def test_translator_never_returns_raw_key_for_shipped_keys(key):
    """A raw key reaching a template is the visible symptom of issue #5."""
    from sts2.i18n import get_translator
    assert get_translator("en")(key) != key


def test_version_is_consistent_across_release_artifacts():
    """pyproject, the app, and the PyInstaller spec must agree.

    The spec used to restate the version as a literal and drifted six releases
    behind (2.9.7 while the app shipped 3.0.2), stamping the stale number into
    the Windows executable's file metadata. It now derives the value, and this
    guards the other two.
    """
    import re

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    config = (PKG / "config.py").read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    pyproject_version = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    config_version = re.search(r'^VERSION\s*=\s*"([^"]+)"', config, re.M)
    assert pyproject_version and config_version
    assert pyproject_version.group(1) == config_version.group(1), (
        f"pyproject {pyproject_version.group(1)} != config {config_version.group(1)}")

    # The spec must not reintroduce a hardcoded literal.
    hardcoded = re.search(r'^VERSION\s*=\s*"([^"]+)"', spec, re.M)
    assert hardcoded is None, (
        f"spirescope.spec hardcodes VERSION={hardcoded.group(1)!r}; derive it instead")
    assert "config.py" in spec, "spec no longer reads the version from config.py"
