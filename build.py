"""Build Spirescope into a standalone executable."""
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent
DIST = ROOT / "dist" / "Spirescope"


def main():
    print("Building Spirescope executable...")
    result = subprocess.run(
        ["pyinstaller", "spirescope.spec", "--clean", "--noconfirm"],
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
