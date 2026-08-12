"""Build Spirescope into a standalone executable."""
import hashlib
import os
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "Spirescope"
BUILD_VENV = ROOT / ".venv_build"


def _get_venv_python() -> Path:
    """Return the Python executable inside the build venv."""
    if sys.platform == "win32":
        return BUILD_VENV / "Scripts" / "python.exe"
    return BUILD_VENV / "bin" / "python"


def _ensure_venv():
    """Create (or re-sync) a venv with only Spirescope deps + PyInstaller.

    The venv is reused across builds for speed, but dependencies are
    re-installed every run: a reused venv with stale requirements is not a
    clean build, and used to silently ship whatever was installed last time.
    """
    venv_python = _get_venv_python()
    if venv_python.exists():
        print("Build venv already exists, syncing dependencies...")
    else:
        print("Creating clean build venv...")
        venv.create(str(BUILD_VENV), with_pip=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", "--upgrade",
         ".", "pyinstaller>=6.0"],
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
)


def _refuse_dirty_tree():
    """Stop before building if the tree holds files that must not ship.

    Keep this in step with the "Private modules" section of .gitignore and
    the exclusion list in .dockerignore.
    """
    present = [name for name in _FORBIDDEN_IN_ARTIFACTS if (ROOT / name).exists()]
    overlays = ROOT / "sts2" / "locales" / "content"
    if overlays.is_dir() and any(overlays.iterdir()):
        present.append("sts2/locales/content/ (game text built from your install)")
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
    # files, but BSD-3-Clause and Apache-2.0 both require the notice to travel
    # with a binary redistribution. Ship the notices as plain files instead.
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
