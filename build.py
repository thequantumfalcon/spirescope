"""Build Spirescope into a standalone executable."""
import hashlib
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
    """Create a clean venv with only Spirescope deps + PyInstaller."""
    venv_python = _get_venv_python()
    if venv_python.exists():
        print("Build venv already exists, reusing.")
        return
    print("Creating clean build venv...")
    venv.create(str(BUILD_VENV), with_pip=True)
    subprocess.run(
        [str(venv_python), "-m", "pip", "install", "--quiet", ".", "pyinstaller>=6.0"],
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


def main():
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

    manifest = _write_sha256_manifest()

    print(f"\nBuild complete: {DIST}")
    print(f"Checksums written to: {manifest}")
    print(f"Zip the '{DIST.name}' folder and share it.")


if __name__ == "__main__":
    main()
