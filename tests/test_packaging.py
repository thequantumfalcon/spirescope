"""Packaging guards: the frozen build must ship every runtime resource.

Regression origin (issue #5): sts2/locales was added for i18n but never
added to the PyInstaller spec, so every packaged v3.0.0/v3.0.1 build
rendered raw translation keys ("nav.cards") in the navigation. Source runs
were fine, which is exactly why source-only testing missed it.
"""
import re
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


def test_version_is_single_sourced():
    """sts2/config.py owns the version; pyproject and the spec derive it.

    The spec used to restate the version as a literal and drifted six releases
    behind (2.9.7 while the app shipped 3.0.2), stamping the stale number into
    the Windows executable's file metadata. pyproject then carried its own
    literal copy, which is the same drift waiting to happen — it now declares
    the version dynamic and reads the config attribute.
    """
    import re

    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    config = (PKG / "config.py").read_text(encoding="utf-8")
    spec = SPEC.read_text(encoding="utf-8")

    config_version = re.search(r'^VERSION\s*=\s*"([^"]+)"', config, re.M)
    assert config_version, "sts2/config.py no longer defines VERSION"

    assert 'dynamic = ["version"]' in pyproject, (
        "pyproject.toml no longer declares the version dynamic")
    assert 'attr = "sts2.config.VERSION"' in pyproject, (
        "pyproject.toml no longer derives the version from sts2.config")
    literal = re.search(r'^version\s*=\s*"([^"]+)"', pyproject, re.M)
    assert literal is None, (
        f"pyproject.toml restates version={literal.group(1)!r}; config.py owns it")

    # The spec must not reintroduce a hardcoded literal either.
    hardcoded = re.search(r'^VERSION\s*=\s*"([^"]+)"', spec, re.M)
    assert hardcoded is None, (
        f"spirescope.spec hardcodes VERSION={hardcoded.group(1)!r}; derive it instead")
    assert "config.py" in spec, "spec no longer reads the version from config.py"


def test_wheel_package_data_covers_every_resource_dir():
    """Any non-code directory under sts2/ must be declared as package data.

    Same bug class as issue #5 but through the other packaging channel: the
    PyInstaller spec bundled every resource dir while wheels shipped none of
    them, so `pip install spirescope` from a wheel produced a package whose
    import failed on the missing static directory.
    """
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    section = re.search(
        r"\[tool\.setuptools\.package-data\](.*?)(?=\n\[|\Z)", pyproject, re.S)
    assert section, "pyproject.toml has no [tool.setuptools.package-data]"
    missing = [
        name for name in _resource_dirs()
        if f'"{name}/' not in section.group(1)
    ]
    assert not missing, (
        f"sts2/{{{','.join(missing)}}} exist but have no package-data pattern — "
        f"wheels would ship without them")


def test_wheel_never_bundles_user_content_overlays():
    """locales/content is the user's own game text; wheels must not sweep it in.

    The package-data pattern must stay file-scoped (locales/*.json) and the
    exclude list must keep the content directory out, mirroring what
    spirescope.spec does for frozen builds.
    """
    pyproject = (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert '"locales/*.json"' in pyproject, (
        "locales package-data no longer lists UI files individually")
    assert '"locales/content/*"' in pyproject, (
        "locales/content is no longer excluded from package data")


def test_sdist_manifest_covers_every_resource_dir():
    """MANIFEST.in must keep sdists complete and prune the content overlays."""
    manifest = (PROJECT_ROOT / "MANIFEST.in").read_text(encoding="utf-8")
    missing = [
        name for name in _resource_dirs()
        if f"sts2/{name}" not in manifest
    ]
    assert not missing, f"MANIFEST.in misses sts2/{{{','.join(missing)}}}"
    assert "prune sts2/locales/content" in manifest


def test_no_module_shadows_the_pypa_build_package():
    """`python -m build` from the project root must reach PyPA's builder.

    A root-level build.py used to shadow it: with the project root as cwd,
    `python -m build` executed the PyInstaller script instead of building a
    wheel. The executable-build script is build_exe.py precisely so the name
    `build` stays free.
    """
    assert not (PROJECT_ROOT / "build.py").exists(), (
        "build.py shadows PyPA's `python -m build`; keep it named build_exe.py")
    assert (PROJECT_ROOT / "build_exe.py").exists()


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


@pytest.mark.parametrize("theme", ["dark", "light"])
def test_theme_text_colours_meet_wcag_aa(theme):
    """Every variable used as a text colour, on every background of its theme.

    The browser suite's check listed 8 of 17 colours by hand and omitted
    --yellow, which shipped at 4.07:1 on --bg and 3.66:1 on --bg3. Enumerating
    from the stylesheet covers a newly added colour without anyone remembering
    to extend a list.

    Only variables that actually appear in a `color:` declaration are checked —
    AA's 4.5:1 applies to text. --accent2, for instance, measures 1.90:1 but is
    only ever a background, so holding it to a text ratio would be wrong.
    """
    import re

    css = (PROJECT_ROOT / "sts2" / "static" / "style.css").read_text(encoding="utf-8")
    selector = r":root" if theme == "dark" else r'\[data-theme="light"\]'
    block = re.search(selector + r"\s*\{(.*?)\}", css, re.S)
    assert block, f"{theme} theme block not found"
    colours = dict(re.findall(r"--([\w-]+):\s*(#[0-9a-fA-F]{6})", block.group(1)))
    backgrounds = {k: v for k, v in colours.items() if k in ("bg", "bg2", "bg3")}
    assert len(backgrounds) == 3, f"expected three {theme} backgrounds, got {backgrounds}"

    used_as_text = set(re.findall(r"(?<!-)\bcolor:\s*var\(--([\w-]+)\)", css))
    assert used_as_text, "no text colours found — the usage scan is broken"

    def luminance(value):
        parts = [int(value[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        chan = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in parts]
        return 0.2126 * chan[0] + 0.7152 * chan[1] + 0.0722 * chan[2]

    def ratio(fg, bg):
        a, b = luminance(fg), luminance(bg)
        hi, lo = max(a, b), min(a, b)
        return (hi + 0.05) / (lo + 0.05)

    failures = []
    for name, fg in colours.items():
        if name not in used_as_text or name in backgrounds:
            continue
        for bg_name, bg in backgrounds.items():
            r = ratio(fg, bg)
            if r < 4.5:
                failures.append(f"--{name} {fg} on --{bg_name} {bg} = {r:.2f}:1")
    assert not failures, (
        f"{theme} theme text below WCAG AA (4.5:1):\n  " + "\n  ".join(failures))


# ── CLI instructions must match how the reader actually runs the app ──

def test_ui_never_hardcodes_a_source_only_command():
    """A packaged reader has no Python and no `spirescope` on PATH.

    Telling them to run `python -m sts2 community` is an instruction they
    cannot follow: they have the executable they double-clicked. Commands
    shown in the UI go through the `cli` global instead, so they read
    correctly for whoever is looking at the page. The guide is exempt only
    inside its explicit source-install branch, which is guarded separately.
    """
    source_only = re.compile(r"<code>(?:python -m sts2|spirescope)\s+\w")
    offenders = []
    for path in sorted((PKG / "templates").glob("*.html")):
        text = path.read_text(encoding="utf-8")
        if path.name == "guide.html":
            continue
        for line in text.splitlines():
            if source_only.search(line):
                offenders.append(f"{path.name}: {line.strip()[:90]}")
    assert not offenders, (
        "UI shows a command a packaged user cannot run:\n  " + "\n  ".join(offenders))


def test_guide_offers_both_invocations():
    """The guide keeps source instructions, but only behind is_frozen."""
    text = (PKG / "templates" / "guide.html").read_text(encoding="utf-8")
    assert "{% if is_frozen %}" in text, "guide no longer branches on build type"
    assert "{{ cli }} update" in text, "guide hardcodes the update command"
    assert "{{ cli }} community" in text, "guide hardcodes the community command"
    # the pip/source lines must sit in the else branch, not the frozen one
    frozen_branch = text.split("{% if is_frozen %}")[1].split("{% else %}")[0]
    assert "pip install" not in frozen_branch
    assert "python -m sts2" not in frozen_branch


@pytest.mark.parametrize("exe_name", ["Spirescope.exe", "Spirescope"])
def test_cli_names_the_running_executable(monkeypatch, exe_name):
    """Frozen builds report their own binary, whatever it is called.

    The name is read from sys.executable rather than hardcoded: the Windows
    build is Spirescope.exe and the macOS build is Spirescope, so a literal
    would be wrong on one of them. The path is built with os.path.join so the
    test means the same thing on a Linux CI runner as on Windows.
    """
    import os
    import sys as _sys

    from sts2 import __main__ as entry

    monkeypatch.setattr(_sys, "frozen", True, raising=False)
    monkeypatch.setattr(_sys, "executable", os.path.join("anywhere", exe_name))
    assert entry._program_name() == exe_name

    monkeypatch.delattr(_sys, "frozen", raising=False)
    assert entry._program_name() == "spirescope"


def test_browser_fixture_aligns_host_with_its_loopback_bind():
    """The browser suite must not be locked out by the auth middleware.

    conftest sets STS2_HOST=0.0.0.0 so the rate-limiter engages, but the
    request-auth middleware reads that same variable at request time. The
    browser fixture serves on real loopback, so it must align the variable
    with its socket or every navigation gets 401 while /health (exempt) still
    answers — the fixture starts and all 15 tests fail on their first
    assertion. That failure mode is invisible to `pytest -q`, which
    deselects browser tests, so it is guarded here instead.
    """
    text = (PROJECT_ROOT / "tests" / "test_browser.py").read_text(encoding="utf-8")
    assert 'os.environ["STS2_HOST"] = "127.0.0.1"' in text, (
        "browser fixture no longer pins STS2_HOST to loopback; every page "
        "request will be refused by the auth middleware")
    assert "old_host" in text, "browser fixture does not restore STS2_HOST"


def test_local_build_refuses_a_tree_holding_unshippable_files():
    """A build runs against the working tree, so private modules sitting in
    it get swept into the artifact — PyInstaller bundles the package as it
    finds it, and setuptools can exclude package data but not discovered
    Python modules. The local build script must stop rather than produce a
    distributable containing them.
    """
    text = (PROJECT_ROOT / "build_exe.py").read_text(encoding="utf-8")
    assert "_refuse_dirty_tree" in text
    for name in ("sts2/risk.py", "sts2/diagnosis.py",
                 "sts2/data/.fetcher_keys.json"):
        assert name in text, f"build guard does not cover {name}"


def test_dockerignore_covers_the_private_set():
    """The Dockerfile copies sts2/ wholesale, so anything not excluded here
    lands in a locally built image and stays importable."""
    ignored = (PROJECT_ROOT / ".dockerignore").read_text(encoding="utf-8")
    for name in ("sts2/risk.py", "sts2/diagnosis.py",
                 "sts2/data/.fetcher_keys.json", "sts2/locales/content/"):
        assert name in ignored, f".dockerignore does not exclude {name}"


def test_every_configuration_variable_is_documented():
    """Configuration the code reads but the README never mentions is
    configuration nobody can find.

    Caught in review: STS2_ALLOWED_HOSTS was added to harden the request
    boundary and shipped undocumented, so the only way to discover it was
    to read the source.

    Limitation worth knowing: this sees direct reads only. A name passed
    through a helper (SPIRESCOPE_OPEN_BROWSER goes through _env_flag) is
    invisible here, so a clean run is evidence, not proof.
    """
    import re as _re

    # Only actual environment reads. Matching bare STS2_* identifiers would
    # also catch module constants such as the STS2_INDICATORS regex, which
    # is not configuration at all.
    reads = _re.compile(
        r"""os\.(?:environ\.get|getenv)\(\s*["']((?:STS2|SPIRESCOPE)_[A-Z_]+)["']"""
        r"""|os\.environ\[\s*["']((?:STS2|SPIRESCOPE)_[A-Z_]+)["']\s*\]""")
    used = set()
    for path in sorted(PKG.rglob("*.py")):
        for first, second in reads.findall(path.read_text(encoding="utf-8")):
            used.add(first or second)
    assert used, "no environment reads found — this guard has stopped working"
    documented = set(_re.findall(
        r"\b(?:STS2|SPIRESCOPE)_[A-Z_]+\b",
        (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")))
    missing = sorted(used - documented)
    assert not missing, (
        "environment variables read by the code but absent from README's "
        f"configuration section: {missing}")
