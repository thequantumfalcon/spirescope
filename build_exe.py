"""Build Spirescope into a standalone executable."""
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "Spirescope"
BUILD_VENV = ROOT / ".venv_build"
RUNTIME_LOCK = ROOT / "requirements-runtime-lock.txt"
FULL_LOCK = ROOT / "requirements-lock.txt"


def _get_venv_python() -> Path:
    """Return the Python executable inside the build venv."""
    if sys.platform == "win32":
        return BUILD_VENV / "Scripts" / "python.exe"
    return BUILD_VENV / "bin" / "python"


def _normalize(name: str) -> str:
    """PEP 503 name normalization."""
    return re.sub(r"[-_.]+", "-", name).lower()


def _lock_entries(path: Path) -> dict[str, tuple[list[str], set[str]]]:
    """Each package pinned in a pip-compile lock file.

    Maps the normalized name to its requirement lines (pin, marker and hash
    lines, comments dropped) and the set of packages its `# via` annotation
    says pulled it in.
    """
    entries: dict[str, tuple[list[str], set[str]]] = {}
    lines: list[str] = []
    via: set[str] = set()
    in_via = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if line and not line[0].isspace() and not line.startswith("#"):
            name = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
            if not name:
                raise SystemExit(f"{path.name}: cannot read the requirement {line!r}")
            lines, via, in_via = [line], set(), False
            entries[_normalize(name.group(0))] = (lines, via)
        elif not line.startswith((" ", "\t")):
            in_via = False      # blank line or a top-level comment
        elif stripped.startswith("--hash="):
            lines.append(line)
        elif stripped.startswith("# via"):
            rest = stripped[len("# via"):].split()
            if rest:
                via.add(_normalize(rest[0]))
            in_via = not rest
        elif in_via and stripped.startswith("#") and stripped[1:].split():
            via.add(_normalize(stripped[1:].split()[0]))
    return entries


def _build_tool_requirements() -> str:
    """PyInstaller and its dependencies, exactly as requirements-lock.txt pins them.

    The runtime lock covers the app. The build also needs PyInstaller, at the
    versions and hashes CI builds with, so its closure is read out of the full
    lock by following the lock's own `# via` annotations outward from
    pyinstaller; whatever the runtime lock already pins is left to it.
    --require-hashes refuses any dependency this misses, so a gap stops the
    build instead of letting pip resolve an unpinned package.
    """
    full = _lock_entries(FULL_LOCK)
    runtime = _lock_entries(RUNTIME_LOCK)
    if "pyinstaller" not in full:
        raise SystemExit(f"{FULL_LOCK.name} does not pin pyinstaller")
    wanted = {"pyinstaller"}
    grew = True
    while grew:
        grew = False
        for name, (_, via) in full.items():
            if name not in wanted and via & wanted:
                wanted.add(name)
                grew = True
    blocks = ["\n".join(full[name][0]) for name in sorted(wanted - runtime.keys())]
    return "\n".join(blocks) + "\n"


def _ensure_venv():
    """Create (or re-sync) a venv with only Spirescope deps + PyInstaller.

    The venv is reused across builds for speed, but dependencies are
    re-installed every run: a reused venv with stale requirements is not a
    clean build, and used to silently ship whatever was installed last time.

    Everything comes from the hashed locks, the same pins CI builds with. The
    previous `pip install --upgrade . "pyinstaller>=6.0"` resolved whatever
    the index offered that day, unhashed, straight into a binary meant for
    distribution.
    """
    venv_python = _get_venv_python()
    if venv_python.exists():
        print("Build venv already exists, syncing dependencies...")
    else:
        print("Creating clean build venv...")
        venv.create(str(BUILD_VENV), with_pip=True)
    with tempfile.TemporaryDirectory(prefix="spirescope-build-") as tmp:
        build_tools = Path(tmp) / "build-tools-lock.txt"
        build_tools.write_text(_build_tool_requirements(), encoding="utf-8")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "--quiet", "--require-hashes",
             "-r", str(RUNTIME_LOCK), "-r", str(build_tools)],
            cwd=str(ROOT), check=True,
        )
    # The project last and on its own: --no-deps because everything it needs
    # is pinned above, and --no-build-isolation so the build backend is the
    # locked setuptools already installed rather than one fetched unhashed
    # into an isolated environment.
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade",
         "--no-deps", "--no-build-isolation", "."],
        cwd=str(ROOT), check=True,
    )
    print("Build venv ready.")


def _write_sha256_manifest() -> Path:
    """Write SHA-256 checksums for the built distribution files."""
    manifest = ROOT / "dist" / "SHA256SUMS.txt"
    lines = []
    for artifact in sorted(path for path in DIST.rglob("*") if path.is_file()):
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        rel = artifact.relative_to(ROOT / "dist").as_posix()
        lines.append(f"{digest}  {rel}")
    manifest.write_text("\n".join(lines) + "\n", encoding="ascii")
    return manifest


# Files that are deliberately not part of the published project. A build
# runs against the working tree, so anything sitting here gets swept into the
# artifact — PyInstaller bundles the package as it finds it, and setuptools
# can exclude package *data* but not discovered Python modules.
_FORBIDDEN_IN_ARTIFACTS = (
    "sts2/risk.py",
    "sts2/diagnosis.py",
    "sts2/data/pheromones.json",
    "sts2/data/hypotheses.json",
    "sts2/data/.fetcher_keys.json",
    # User state a legacy install kept in the data directory.
    "sts2/data/settings.json",
    "sts2/data/community_aggregate.json",
)


def _refuse_dirty_tree():
    """Stop before building if the tree holds files that must not ship.

    Keep this in step with the "Private modules" section of .gitignore, the
    exclusion list in .dockerignore, and _DATA_NEVER_SHIPPED in
    spirescope.spec.
    """
    present = [name for name in _FORBIDDEN_IN_ARTIFACTS if (ROOT / name).exists()]
    overlays = ROOT / "sts2" / "locales" / "content"
    if overlays.is_dir() and any(overlays.iterdir()):
        present.append("sts2/locales/content/ (game text built from your install)")
    mods = ROOT / "sts2" / "data" / "mods"
    if mods.is_dir():
        dropped_in = sorted(p.name for p in mods.iterdir() if p.name != "README.md")
        if dropped_in:
            present.append(f"sts2/data/mods/ ({', '.join(dropped_in)}: user mods, which "
                           f"belong in the state directory)")
    if not present:
        return
    print("Refusing to build: the working tree contains files that must not "
          "ship in an artifact:")
    for name in present:
        print(f"  - {name}")
    print("\nBuild from a clean checkout instead, e.g.:")
    print("  git archive HEAD | tar -x -C <empty dir>   # then build there")
    print("Set SPIRESCOPE_ALLOW_DIRTY_BUILD=1 to override for a local-only "
          "build you will not distribute.")
    sys.exit(1)


def main():
    if os.environ.get("SPIRESCOPE_ALLOW_DIRTY_BUILD") != "1":
        _refuse_dirty_tree()
    _ensure_venv()
    venv_python = _get_venv_python()

    print("Building Spirescope executable...")
    result = subprocess.run(
        [str(venv_python), "-m", "PyInstaller", "spirescope.spec", "--clean", "--noconfirm"],
        cwd=str(ROOT),
    )
    if result.returncode != 0:
        print("Build failed.")
        sys.exit(1)

    # Harvest the bundled packages' own licence texts BEFORE the dist-info
    # directories that hold them are stripped below.
    licenses_out = DIST / "LICENSES.txt"
    collector = subprocess.run(
        [str(venv_python), str(ROOT / "scripts" / "collect_licenses.py"),
         "--output", str(licenses_out)],
        cwd=str(ROOT),
    )
    if collector.returncode != 0:
        print("Build failed: could not collect third-party licence texts.")
        sys.exit(1)

    # Strip dist-info metadata to avoid false positives from package scanners
    # (for example, bundled metadata being misread as typosquatting)
    for dist_info in DIST.rglob("*.dist-info"):
        if dist_info.is_dir():
            shutil.rmtree(dist_info)
            print(f"  Stripped: {dist_info.name}")

    # Copy user-facing README into dist folder
    readme_src = ROOT / "README_DIST.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, DIST / "README.txt")

    # Stripping dist-info above also removes the bundled packages' LICENSE
    # files, but BSD-3-Clause and Apache-2.0 both require the notice, the
    # conditions and the disclaimer to travel with a binary redistribution —
    # a name and a URL is not a reproduction of them. Collect the verbatim
    # texts the same way the release workflows do.
    for name, dest in (("LICENSE", "LICENSE.txt"),
                       ("THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md")):
        src = ROOT / name
        if not src.exists():
            print(f"Build failed: {name} is missing; it must ship with the binary.")
            sys.exit(1)
        shutil.copy2(src, DIST / dest)

    manifest = _write_sha256_manifest()

    print(f"\nBuild complete: {DIST}")
    print(f"Checksums written to: {manifest}")
    print(f"Zip the '{DIST.name}' folder and share it.")


if __name__ == "__main__":
    main()
