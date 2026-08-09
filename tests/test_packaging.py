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
        # Either the whole directory is bundled, or its files are listed
        # individually with it as their destination (which sts2/locales
        # does, to keep the user-built content/ subdirectory out).
        if f"'sts2/{name}', 'sts2/{name}'" not in spec
        and f", 'sts2/{name}')" not in spec
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


def test_spec_never_bundles_user_content_overlays():
    """sts2/locales/content holds text built from the user's own game copy.
    Bundling the locales directory wholesale swept it into the exe, which
    would redistribute it; the spec must list the UI files individually."""
    spec = (PKG.parent / "spirescope.spec").read_text(encoding="utf-8")
    assert "('sts2/locales', 'sts2/locales')" not in spec, \
        "spec bundles sts2/locales recursively, which includes content/"
    assert "sts2/locales').glob('*.json')" in spec


def test_content_overlays_are_clean_and_have_a_ui_locale():
    """Content overlays are user-supplied and not shipped, but when one is
    present it renders straight onto entity pages — so unresolved markup or
    a missing UI locale would be visible. Vacuous on a clean checkout."""
    import json
    import re

    overlays = sorted((PKG / "locales" / "content").glob("*.json"))
    residue = re.compile(r"\{[A-Za-z]+[:}]|\[/?(?:gold|blue|red|green)\]|@[A-Z][ES]\b")
    for path in overlays:
        data = json.loads(path.read_text(encoding="utf-8"))
        assert (PKG / "locales" / f"{path.name}").exists(), \
            f"{path.stem} has content but no UI locale file"
        dirty = []
        for family, entries in data.items():
            if family == "_meta" or not isinstance(entries, dict):
                continue
            for eid, entry in entries.items():
                for field, value in entry.items():
                    if isinstance(value, str) and residue.search(value):
                        dirty.append(f"{path.name}:{eid}.{field}: {value!r}")
        assert not dirty, "unrendered markup in overlays:\n" + "\n".join(dirty[:5])


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


class TestStateDirSplit:
    """User state must live outside the shipped data directory.

    DATA_DIR is replaced wholesale by `sts2 update` and by data-bundle
    installs. Anything of the user's kept there is collateral damage — which is
    how hand-assigned patch mappings used to be discarded on update.
    """

    def test_state_dir_is_not_inside_the_package_or_data_dir(self):
        from sts2.config import BUNDLED_DATA_DIR, DATA_DIR, PROJECT_ROOT, STATE_DIR

        assert PROJECT_ROOT not in STATE_DIR.parents
        assert BUNDLED_DATA_DIR not in STATE_DIR.parents
        assert STATE_DIR != DATA_DIR

    def test_user_state_files_resolve_into_state_dir(self, tmp_path, monkeypatch):
        import sts2.config as cfg

        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state")
        from sts2.aggregate import _aggregate_storage_path
        from sts2.hypothesis import _hypotheses_file
        from sts2.i18n import _settings_path

        for resolver in (_settings_path, _hypotheses_file, _aggregate_storage_path):
            assert (tmp_path / "state") in resolver().parents, resolver.__name__

    def test_migration_moves_existing_state_without_overwriting(self, tmp_path, monkeypatch):
        """An upgrading user keeps their stats; a newer file is never clobbered."""
        import json

        import sts2.config as cfg

        data_dir = tmp_path / "data"
        state_dir = tmp_path / "state"
        (data_dir / "mods").mkdir(parents=True)
        (data_dir / "mods" / "my_mod.json").write_text("{}", encoding="utf-8")
        # Ships with the package — must survive, or a source checkout loses a
        # tracked file the first time the app runs.
        (data_dir / "mods" / "README.md").write_text("mod format docs", encoding="utf-8")
        (data_dir / "settings.json").write_text('{"language": "en"}', encoding="utf-8")
        (data_dir / "community_aggregate.json").write_text('{"run_count": 42}', encoding="utf-8")
        # Already migrated, with different content — must survive untouched.
        state_dir.mkdir()
        (state_dir / "hypotheses.json").write_text('{"kept": true}', encoding="utf-8")
        (data_dir / "hypotheses.json").write_text('{"stale": true}', encoding="utf-8")

        monkeypatch.setattr(cfg, "DATA_DIR", data_dir)
        monkeypatch.setattr(cfg, "STATE_DIR", state_dir)
        moved = cfg.migrate_state_from_data_dir()

        assert set(moved) == {"settings.json", "community_aggregate.json", "mods/my_mod.json"}
        assert json.loads((state_dir / "community_aggregate.json").read_text())["run_count"] == 42
        assert (state_dir / "mods" / "my_mod.json").exists()
        assert not (data_dir / "settings.json").exists()
        # The shipped README stays put and is never copied into user state.
        assert (data_dir / "mods" / "README.md").exists()
        assert not (state_dir / "mods" / "README.md").exists()
        # The pre-existing file wins; the stale copy stays put rather than
        # silently replacing newer state.
        assert json.loads((state_dir / "hypotheses.json").read_text()) == {"kept": True}

    def test_migration_is_idempotent(self, tmp_path, monkeypatch):
        import sts2.config as cfg

        data_dir = tmp_path / "data"
        data_dir.mkdir()
        (data_dir / "settings.json").write_text("{}", encoding="utf-8")
        monkeypatch.setattr(cfg, "DATA_DIR", data_dir)
        monkeypatch.setattr(cfg, "STATE_DIR", tmp_path / "state")

        assert cfg.migrate_state_from_data_dir() == ["settings.json"]
        assert cfg.migrate_state_from_data_dir() == []


def test_changelog_has_no_bare_at_mentions():
    """Release notes are generated from CHANGELOG.md by .github/workflows/release.yml,
    and GitHub auto-links @name in a release body to that account.

    v3.0.4's notes described a data bug involving raw "@CE"-style icon codes.
    One of the two occurrences was outside backticks, so GitHub linked it to the
    real, unrelated account github.com/ce, listed them as a contributor on the
    release page, and notified them. Anything resembling a handle must stay
    inside code formatting.
    """
    import re

    text = (PROJECT_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    # Strip the forms GitHub will not turn into an accidental mention:
    # fenced blocks, inline code, and explicit markdown links — a deliberate
    # credit like "[@mattkuo]" or "[@mattkuo](https://github.com/mattkuo)" is
    # exactly what we want to keep.
    cleaned = re.sub(r"```.*?```", "", text, flags=re.S)
    cleaned = re.sub(r"`[^`\n]*`", "", cleaned)
    cleaned = re.sub(r"\[@[A-Za-z][A-Za-z0-9-]*\](\([^)]*\)|:[^\n]*)?", "", cleaned)
    mentions = re.findall(r"(?<![\w/])@([A-Za-z][A-Za-z0-9-]{0,38})", cleaned)
    assert not mentions, (
        "bare @mentions in CHANGELOG.md would be auto-linked in the generated "
        f"release notes and notify those accounts: {sorted(set(mentions))}. "
        "Wrap them in backticks.")
