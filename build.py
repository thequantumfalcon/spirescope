"""Build Spirescope into a standalone executable."""
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

    # Copy user-facing README into dist folder
    readme_src = ROOT / "README_DIST.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, DIST / "README.txt")

    print(f"\nBuild complete: {DIST}")
    print(f"Zip the '{DIST.name}' folder and share it.")


if __name__ == "__main__":
    main()
