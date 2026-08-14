"""Tests for scripts/check_notices.py against the real THIRD_PARTY_NOTICES.md.

Guards against the M15 regression: colorama is pulled in on Windows via
click/uvicorn but was missing from the runtime dependency table for several
releases. The colorama assertions below are checked directly against the
notices file text (not through the platform-dependent closure walk) so this
test catches a regression on every CI platform, not only Windows.
"""
import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
NOTICES_PATH = REPO_ROOT / "THIRD_PARTY_NOTICES.md"
SCRIPT_PATH = REPO_ROOT / "scripts" / "check_notices.py"


def _load_check_notices():
    spec = importlib.util.spec_from_file_location("check_notices", SCRIPT_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


check_notices = _load_check_notices()


class TestNoticesFileContent:
    """Environment-independent: plain string checks against the real file."""

    def test_notices_file_exists(self):
        assert NOTICES_PATH.exists()

    def test_colorama_documented(self):
        # The specific M15 regression: colorama is a real runtime transitive
        # dependency (via click/uvicorn on Windows) and must be listed
        # regardless of which platform this test happens to run on.
        text = NOTICES_PATH.read_text(encoding="utf-8").lower()
        assert "colorama" in text

    def test_colorama_license_is_bsd(self):
        # colorama is BSD-3-Clause; make sure it wasn't added with a wrong
        # license label, consistent with how the file documents other BSD deps.
        text = NOTICES_PATH.read_text(encoding="utf-8")
        lines = [ln for ln in text.splitlines() if ln.lower().startswith("| colorama")]
        assert lines, "no table row found for colorama"
        assert "BSD-3-Clause" in lines[0]

    def test_declared_runtime_dependencies_documented(self):
        # The six packages pyproject.toml declares directly, independent of
        # platform/marker evaluation.
        direct = check_notices.declared_runtime_requirements()
        names = {req.name.lower() for req in direct}
        assert names == {
            "fastapi", "uvicorn", "jinja2", "pydantic",
            "python-multipart", "watchdog",
        }
        text = NOTICES_PATH.read_text(encoding="utf-8").lower()
        for name in names:
            assert name in text, f"{name} (direct dependency) not found in notices file"


class TestRuntimeClosureCheck:
    """Exercises the actual closure-walking + comparison logic."""

    def test_runtime_mode_reports_nothing_missing(self):
        direct = check_notices.declared_runtime_requirements()
        names = check_notices.runtime_closure(direct)
        notices_text = NOTICES_PATH.read_text(encoding="utf-8")
        missing = check_notices.missing_from_notices(names, notices_text)
        assert missing == [], f"undocumented runtime dependencies: {missing}"

    def test_colorama_included_when_installed(self):
        # On a platform where colorama's marker (platform_system ==
        # "Windows") evaluates true and click is installed, the closure walk
        # must surface it -- this is what actually exercises the check tool's
        # marker handling for the M15 case, on whichever platform CI happens
        # to be Windows.
        import importlib.metadata as metadata
        try:
            metadata.distribution("colorama")
        except metadata.PackageNotFoundError:
            import pytest
            pytest.skip("colorama not installed in this environment")
        direct = check_notices.declared_runtime_requirements()
        names = check_notices.runtime_closure(direct)
        assert "colorama" in names


class TestScriptEntryPoint:
    """Invokes the script as a program, the way a maintainer or CI would."""

    def test_runtime_mode_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--mode", "runtime"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "OK" in result.stdout

    def test_runtime_mode_verbose_lists_declared_deps(self):
        result = subprocess.run(
            [sys.executable, str(SCRIPT_PATH), "--mode", "runtime", "--verbose"],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert "fastapi" in result.stdout.lower()
