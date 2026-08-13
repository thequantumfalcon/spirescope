"""Static guards for the release pipeline (CA-H7, CA-H8, CA-H9, CA-M16).

These check the *structure* of the workflow files and spec, not a live CI
run -- they are regression guards for four confirmed defects:

  CA-H7  (release race): release.yml and release-macos.yml independently
         triggered on the same tag and both published to the same GitHub
         release with no ordering between them -- a race, and a hard
         failure waiting to happen if immutable releases were ever enabled
         (assets cannot be added after an immutable release is published).
  CA-H8  (tag builds skip the real gates): the release workflows ran a
         plain `pytest`, which excludes browser tests via pyproject's
         addopts -- ruff, mypy, the browser suite and the wheel-install
         check never ran before a tag published.
  CA-H9  (missing license texts): dist-info -- the only place bundled
         dependencies' own LICENSE files live once installed -- gets
         deleted before packaging, and THIRD_PARTY_NOTICES.md documents
         names/SPDX/URLs but does not reproduce license text.
  CA-M16 (dev tooling shipped): the pydantic PyInstaller hook's
         collect_submodules('pydantic') sweeps in the optional pydantic.mypy
         plugin module, pulling the whole mypy package and its own runtime
         deps into the frozen build even though the app never imports it.

Where useful this also exercises scripts/collect_licenses.py directly
against the real installed environment, rather than only grepping text.
"""
import importlib.metadata as metadata
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
RELEASE_YML = WORKFLOWS_DIR / "release.yml"
CI_YML = WORKFLOWS_DIR / "ci.yml"
SPEC = REPO_ROOT / "spirescope.spec"
COLLECT_LICENSES = REPO_ROOT / "scripts" / "collect_licenses.py"


def _load_workflow(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _jobs(workflow: dict) -> dict:
    return workflow.get("jobs", {})


def _as_list(value) -> list:
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _step_haystack(step: dict) -> str:
    """Every bit of text on a step worth substring-matching against."""
    parts = [str(step.get("name", "")), str(step.get("uses", "")), str(step.get("run", ""))]
    return "\n".join(parts).lower()


def _publishing_jobs(jobs: dict) -> dict:
    """Jobs that actually create/modify the GitHub release."""
    return {
        job_id: job
        for job_id, job in jobs.items()
        if any("action-gh-release" in str(s.get("uses", "")) for s in job.get("steps", []))
    }


class TestSingleReleasePublisher:
    """CA-H7: exactly one job ever calls action-gh-release, and it accounts
    for both platforms -- the fix for the two-workflow race."""

    def test_only_release_workflow_remains(self):
        assert RELEASE_YML.exists()
        assert not (WORKFLOWS_DIR / "release-macos.yml").exists(), (
            "release-macos.yml should be consolidated into release.yml, not "
            "left as a second workflow that can independently publish")

    def test_exactly_one_job_publishes_the_release(self):
        workflow = _load_workflow(RELEASE_YML)
        publishers = _publishing_jobs(_jobs(workflow))
        assert len(publishers) == 1, (
            f"expected exactly one job calling action-gh-release, found: {sorted(publishers)}")

    def test_publisher_needs_both_platform_builds(self):
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        needs = _as_list(jobs[publisher_id].get("needs"))
        assert any("windows" in n for n in needs), needs
        assert any("macos" in n for n in needs), needs

    def test_publisher_downloads_assets_for_both_platforms(self):
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        steps = jobs[publisher_id].get("steps", [])
        downloads = [s for s in steps if "download-artifact" in str(s.get("uses", ""))]
        names = [str(s.get("with", {}).get("name", "")) for s in downloads]
        assert any("windows" in n for n in names), names
        assert any("macos" in n for n in names), names

    def test_only_publisher_job_has_contents_write(self):
        """Build jobs get contents:read; only the publisher writes."""
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        for job_id, job in jobs.items():
            perms = job.get("permissions") or {}
            if not isinstance(perms, dict):
                continue
            contents = perms.get("contents")
            if job_id == publisher_id:
                assert contents == "write", f"{job_id} (publisher) must hold contents: write"
            else:
                assert contents != "write", f"{job_id} must not hold contents: write"

    def test_every_platform_build_is_required(self):
        """Publishing is all-or-nothing.

        Tolerating a macOS failure so the Windows archive could still ship
        was the earlier choice, and it pairs badly with immutable releases:
        assets cannot be added to a published immutable release, so a flaky
        runner would leave that version permanently Windows-only and force a
        version burn. Re-running the failed job is the cheaper failure.
        """
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        condition = " ".join(str(jobs[publisher_id].get("if", "")).split())
        for job in ("gate", "build-windows", "build-macos"):
            assert f"needs.{job}.result == 'success'" in condition, (
                f"publish does not require {job}")

    def test_a_partial_release_cannot_be_published(self):
        """Both builds succeeding is not proof both produced assets."""
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        guards = [s for s in jobs[publisher_id]["steps"]
                  if "assets before publishing" in (s.get("name") or "")]
        assert guards, "nothing verifies both platforms' assets are present"
        assert "exit 1" in guards[0]["run"], "the guard warns instead of stopping"


class TestTagBuildsRunTheRealGates:
    """CA-H8: a tag cannot publish without the same checks that protect
    master -- ruff, mypy, pytest, the browser suite, and the wheel install
    check."""

    def test_ci_workflow_is_callable_as_a_reusable_workflow(self):
        text = CI_YML.read_text(encoding="utf-8")
        assert re.search(r"^\s*workflow_call:\s*$", text, re.M), (
            "ci.yml must declare `workflow_call:` under `on:` so release.yml "
            "can depend on it as a reusable workflow")

    def test_release_workflow_gates_on_the_reusable_ci_workflow(self):
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        assert "gate" in jobs, "release.yml has no `gate` job"
        uses = str(jobs["gate"].get("uses", ""))
        assert uses.endswith(".github/workflows/ci.yml"), uses

    def test_both_build_jobs_depend_on_the_gate(self):
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        for job_id in ("build-windows", "build-macos"):
            needs = _as_list(jobs[job_id].get("needs"))
            assert "gate" in needs, f"{job_id} does not need the gate job"

    def test_publisher_also_requires_the_gate_to_have_passed(self):
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        needs = _as_list(jobs[publisher_id].get("needs"))
        assert "gate" in needs
        condition = str(jobs[publisher_id].get("if", ""))
        assert "needs.gate.result == 'success'" in condition

    def test_ci_gate_set_covers_the_required_minimum(self):
        """ruff, blocking mypy, pytest, browser (with chromium install), and
        the wheel build+install+import check must all exist in the job set
        release.yml depends on."""
        workflow = _load_workflow(CI_YML)
        jobs = _jobs(workflow)

        test_steps = jobs["test"]["steps"]
        assert any("ruff check" in str(s.get("run", "")) for s in test_steps)

        mypy_steps = [s for s in test_steps if "mypy" in str(s.get("run", "")).lower()]
        assert mypy_steps, "no step runs mypy"
        assert "continue-on-error" not in mypy_steps[0], (
            "mypy must be blocking, not continue-on-error")

        assert "browser" in jobs
        browser_text = " ".join(str(s.get("run", "")) for s in jobs["browser"]["steps"])
        assert "playwright install --with-deps chromium" in browser_text
        assert "pytest -m browser" in browser_text

        assert "build-dist" in jobs, "no wheel build+install+import check job"
        dist_text = " ".join(str(s.get("run", "")) for s in jobs["build-dist"]["steps"])
        assert "pip install dist/*.whl" in dist_text or "install dist/*.whl" in dist_text
        assert "import sts2.app" in dist_text

    def test_required_status_check_names_are_preserved(self):
        """Branch protection requires these exact context names; restructuring
        the release pipeline must not rename or remove them."""
        workflow = _load_workflow(CI_YML)
        jobs = _jobs(workflow)
        versions = jobs["test"]["strategy"]["matrix"]["python-version"]
        assert set(versions) == {"3.11", "3.12", "3.13"}
        assert "browser" in jobs


class TestNoUnpinnedInstallsBeforePublishing:
    """CA-H7 hardening: a job holding contents:write (or that calls
    action-gh-release) must never pip-install an unpinned package -- that
    job has enough access that a compromised dependency would be a
    supply-chain hole, not just a broken build. Scoped to the workflows this
    task owns (release.yml, ci.yml); a lock-file install (`-r
    requirements-lock.txt`) or a local editable install with `--no-deps` is
    fine since neither resolves anything unpinned from an index.
    """

    _PIP_INSTALL = re.compile(r"pip install[^\n|&]*", re.I)
    _ALLOWED = re.compile(
        r"^pip install\s+(-r\s+requirements-lock\.txt|-e\s+\.\s+--no-deps|dist/|\.\s*$)", re.I,
    )

    def _write_scoped_jobs(self, workflow: dict) -> dict:
        jobs = _jobs(workflow)
        result = dict(_publishing_jobs(jobs))
        for job_id, job in jobs.items():
            perms = job.get("permissions") or {}
            if isinstance(perms, dict) and perms.get("contents") == "write":
                result[job_id] = job
        return result

    @pytest.mark.parametrize("workflow_path", [RELEASE_YML, CI_YML])
    def test_no_write_scoped_job_installs_unpinned_packages(self, workflow_path):
        workflow = _load_workflow(workflow_path)
        for job_id, job in self._write_scoped_jobs(workflow).items():
            for step in job.get("steps", []):
                run = str(step.get("run", ""))
                for match in self._PIP_INSTALL.finditer(run):
                    installed = match.group(0)
                    if self._ALLOWED.match(installed.strip()):
                        continue
                    pytest.fail(
                        f"{workflow_path.name}:{job_id} installs unpinned packages "
                        f"while write-scoped: {installed!r}")

    def test_publisher_job_installs_nothing_at_all(self):
        """release.yml's publish job specifically: it only reads
        CHANGELOG.md and moves artifacts around, so it shouldn't need `pip
        install` in the first place."""
        workflow = _load_workflow(RELEASE_YML)
        jobs = _jobs(workflow)
        [publisher_id] = _publishing_jobs(jobs)
        for step in jobs[publisher_id].get("steps", []):
            assert "pip install" not in str(step.get("run", ""))


class TestSpecExcludesTypeCheckingTooling:
    """CA-M16: verified via a real PyInstaller build (Analysis + COLLECT)
    that the pydantic hook's collect_submodules('pydantic') sweeps in the
    optional pydantic.mypy plugin module, which pulls in mypy (72 mypyc
    .pyd files), mypy_extensions, and mypy's own runtime deps librt and
    ast_serialize -- ~74 files / ~3.2 MB the app never imports at runtime.
    Rebuilding with these excludes removed all of it and the packaged app
    still started and served /, /cards and /settings correctly.
    """

    def _excludes(self) -> list[str]:
        text = SPEC.read_text(encoding="utf-8")
        m = re.search(r"excludes\s*=\s*\[(.*?)\]", text, re.S)
        assert m, "spirescope.spec has no excludes=[...] list"
        return re.findall(r"'([^']+)'", m.group(1))

    def test_type_checking_packages_are_excluded(self):
        excludes = self._excludes()
        for name in ("mypy", "mypy_extensions"):
            assert name in excludes, (
                f"{name} is not in spirescope.spec's excludes list; a clean "
                f"build ships it via pydantic's PyInstaller hook")

    def test_mypys_own_runtime_helpers_are_excluded(self):
        """The two packages named in the defect report weren't the whole
        story -- mypy itself depends on librt and ast-serialize (verified
        via `importlib.metadata.distribution('mypy').requires`), and a real
        build showed both getting bundled too."""
        excludes = self._excludes()
        for name in ("librt", "ast_serialize"):
            assert name in excludes, (
                f"{name} is a runtime dependency of mypy and was verified "
                f"present in a real frozen build; add it to excludes")


class TestLicenseCollectionRunsBeforeStripping:
    """CA-H9: the license text has to be harvested from dist-info before the
    'Strip dist-info metadata' step deletes it, in every path that ships a
    binary."""

    @staticmethod
    def _step_order_indices(steps: list) -> tuple:
        collect_idx = next(
            (i for i, s in enumerate(steps) if "collect_licenses.py" in _step_haystack(s)), None)
        strip_idx = next(
            (i for i, s in enumerate(steps)
             if "dist-info" in _step_haystack(s)
             and ("remove-item" in _step_haystack(s) or "rm -rf" in _step_haystack(s)
                  or "strip" in str(s.get("name", "")).lower())),
            None,
        )
        return collect_idx, strip_idx

    @pytest.mark.parametrize("job_id", ["build-windows", "build-macos"])
    def test_collect_licenses_precedes_dist_info_strip(self, job_id):
        workflow = _load_workflow(RELEASE_YML)
        steps = _jobs(workflow)[job_id]["steps"]
        collect_idx, strip_idx = self._step_order_indices(steps)
        assert collect_idx is not None, f"{job_id} never runs collect_licenses.py"
        assert strip_idx is not None, f"{job_id} never strips dist-info"
        assert collect_idx < strip_idx, (
            f"{job_id}: license collection (step {collect_idx}) must run before "
            f"dist-info stripping (step {strip_idx})")

    @pytest.mark.parametrize("job_id", ["build-windows", "build-macos"])
    def test_licenses_txt_is_required_in_the_staged_distribution(self, job_id):
        workflow = _load_workflow(RELEASE_YML)
        steps = _jobs(workflow)[job_id]["steps"]
        stage = next(s for s in steps if "stage distribution" in str(s.get("name", "")).lower())
        assert "LICENSES.txt" in str(stage.get("run", ""))


class TestCollectLicensesScript:
    """Exercises scripts/collect_licenses.py against the real installed
    environment. Also guards a real bug hit while writing it:
    importlib.metadata.Distribution.read_text() resolves its argument
    relative to the dist-info directory itself, but dist.files entries are
    prefixed with the dist-info dirname -- passing one straight into the
    other silently returns None (FileNotFoundError is swallowed), so every
    package looked license-less until the path was re-relativized.
    """

    @staticmethod
    def _load_module():
        spec = importlib.util.spec_from_file_location("collect_licenses", COLLECT_LICENSES)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_license_files_found_for_a_known_bsd_package(self):
        module = self._load_module()
        try:
            dist = metadata.distribution("click")
        except metadata.PackageNotFoundError:
            pytest.skip("click not installed in this environment")
        files = module.license_files_for(dist)
        assert files, "expected at least one license file for click"
        name, text = files[0]
        assert "licen" in name.lower()  # license / licence
        assert len(text) > 100

    def test_runtime_closure_yields_no_missing_license_text(self):
        module = self._load_module()
        direct = module.declared_runtime_requirements()
        names = module.runtime_closure(direct)
        names = {n for n in names if n not in {"pip", "setuptools", "wheel"}}
        _, missing = module.build_report(names)
        assert missing == [], f"no license text found for: {missing}"

    def test_script_entry_point_writes_a_non_empty_file(self, tmp_path):
        output = tmp_path / "LICENSES.txt"
        result = subprocess.run(
            [sys.executable, str(COLLECT_LICENSES), "--output", str(output)],
            cwd=REPO_ROOT, capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        assert output.exists()
        assert output.stat().st_size > 1000

    def test_missing_or_licenseless_distribution_fails_closed(self, monkeypatch, tmp_path):
        """The workflow must fail, not silently ship an undocumented binary,
        if a bundled dependency has no discoverable license text."""
        module = self._load_module()
        _, missing = module.build_report({"not-a-real-package-xyz"})
        assert missing == ["not-a-real-package-xyz"]

        output = tmp_path / "LICENSES.txt"
        monkeypatch.setattr(module, "declared_runtime_requirements", lambda: [])
        monkeypatch.setattr(module, "runtime_closure", lambda direct: {"not-a-real-package-xyz"})
        monkeypatch.setattr(sys, "argv", ["collect_licenses.py", "--output", str(output)])
        exit_code = module.main()
        assert exit_code == 1
        assert not output.exists()


class TestWorkflowYamlIsWellFormed:
    """Cheap sanity net: every workflow file this task touched must at least
    parse. Full validation (pyyaml over every workflow) also runs as a
    standalone check outside pytest; this keeps a regression guard inside
    the suite too."""

    @pytest.mark.parametrize("name", ["release.yml", "ci.yml"])
    def test_workflow_parses_as_yaml(self, name):
        workflow = _load_workflow(WORKFLOWS_DIR / name)
        assert isinstance(workflow, dict)
        assert "jobs" in workflow


class TestReleaseIsAllOrNothing:
    """A partial release cannot be corrected once immutable releases are on:
    assets cannot be added after publication, so a flaky macOS runner would
    leave that version permanently Windows-only and force a version burn.
    Publishing is therefore gated on every build, and on the assets actually
    being present.
    """

    @staticmethod
    def _release():
        return _load_workflow(RELEASE_YML)

    def test_publish_requires_every_build(self):
        publish = self._release()["jobs"]["publish"]
        assert set(publish["needs"]) == {"gate", "build-windows", "build-macos"}
        condition = " ".join(publish["if"].split())
        for job in ("gate", "build-windows", "build-macos"):
            assert f"needs.{job}.result == 'success'" in condition, (
                f"publish does not require {job} to have succeeded")

    def test_publish_never_runs_on_a_dry_run(self):
        condition = " ".join(self._release()["jobs"]["publish"]["if"].split())
        assert "github.event_name == 'push'" in condition, (
            "the manual dry-run path could reach the publishing job")

    def test_missing_platform_assets_stop_the_release(self):
        steps = self._release()["jobs"]["publish"]["steps"]
        guard = [s for s in steps
                 if "assets before publishing" in (s.get("name") or "")]
        assert guard, "no step verifies both platforms' assets are present"
        body = guard[0]["run"]
        assert "*windows*" in body and "*macos*" in body
        assert "exit 1" in body, "the guard warns instead of stopping"

    def test_release_action_fails_on_unmatched_files(self):
        steps = self._release()["jobs"]["publish"]["steps"]
        create = [s for s in steps if "action-gh-release" in (s.get("uses") or "")]
        assert create, "no release-creating step found"
        assert create[0]["with"]["fail_on_unmatched_files"] is True


class TestDryRunPathExists:
    """A tag push must not be the first time any of this executes."""

    def test_workflow_dispatch_is_available(self):
        import yaml
        with open(RELEASE_YML,
                  encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        triggers = data.get(True) or data.get("on")
        assert "workflow_dispatch" in triggers

    def test_version_gate_is_skipped_without_a_tag(self):
        import yaml
        with open(RELEASE_YML,
                  encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
        checked = 0
        for job in ("build-windows", "build-macos"):
            for step in data["jobs"][job]["steps"]:
                if "tag matches the version" in (step.get("name") or ""):
                    checked += 1
                    assert step.get("if") == "github.event_name == 'push'", (
                        f"{job}'s version gate would fail a tagless dry run")
        assert checked == 2, "expected a version gate in each build job"


class TestCallableWorkflowStaysWithinCallerPermissions:
    """A reusable workflow cannot request more permission than its caller.

    ci.yml is called by the release pipeline's gate job, which grants
    contents: read. A write-scoped job inside ci.yml therefore made the whole
    release workflow fail to compile — startup_failure, before a single job
    ran, which is how the first real dry run failed. Badge publishing moved
    to its own workflow_run-triggered workflow so the gate stays purely
    verification.
    """

    def test_ci_requests_no_write_permission_anywhere(self):
        ci = _load_workflow(CI_YML)
        offenders = []
        for job_id, cfg in _jobs(ci).items():
            perms = cfg.get("permissions") or {}
            if isinstance(perms, dict):
                offenders += [f"{job_id}:{k}" for k, v in perms.items()
                              if v == "write"]
            elif perms == "write-all":
                offenders.append(f"{job_id}:write-all")
        assert not offenders, (
            "ci.yml is called as a reusable workflow with contents: read; "
            f"these jobs would make it fail to compile: {offenders}")

    def test_gate_grants_no_more_than_read(self):
        release = _load_workflow(RELEASE_YML)
        gate = _jobs(release)["gate"]
        assert gate["permissions"] == {"contents": "read"}

    def test_badge_publishing_still_exists_outside_the_gate(self):
        badge = _load_workflow(WORKFLOWS_DIR / "badge.yml")
        triggers = badge.get(True) or badge.get("on")
        assert "workflow_run" in triggers, (
            "the badge must react to CI finishing, not run inside it")
        [job] = _jobs(badge).values()
        assert job["permissions"]["contents"] == "write"
