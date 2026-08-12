"""Collect verbatim license (and NOTICE) text for every shipped runtime
dependency into a single LICENSES.txt.

Compliance-risk repair, not legal advice: THIRD_PARTY_NOTICES.md lists package
names, SPDX identifiers and project URLs, but a URL is not a reproduction of a
license text. BSD-3-Clause and similar licenses require the notice,
conditions and disclaimer to travel *with* a binary redistribution. Both
release workflows build the frozen app and then delete every bundled
`*.dist-info` directory (to avoid false positives from package scanners),
which also deletes the one place those license files lived. This script reads
them out of dist-info BEFORE that stripping step runs, so the text survives
into the shipped archive as LICENSES.txt instead.

The set of packages scanned is exactly the runtime dependency closure that
scripts/check_notices.py already computes and THIRD_PARTY_NOTICES.md already
documents (declared [project.dependencies], walked transitively through
installed metadata) -- not "everything installed in this environment", which
would also sweep in build/dev-only tooling (pyinstaller, mypy, pytest, ruff,
...) that is never shipped, and after CA-M16's spec excludes, in some cases
no longer even present in the frozen build at all.

Usage:
    python scripts/collect_licenses.py                       # writes LICENSES.txt to repo root
    python scripts/collect_licenses.py --output dist/Spirescope/LICENSES.txt
    python scripts/collect_licenses.py --verbose
"""
import argparse
import importlib.metadata as metadata
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_notices import declared_runtime_requirements, runtime_closure  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = REPO_ROOT / "LICENSES.txt"

# Conventional license/notice file basenames (case-insensitive prefix match,
# so LICENSE, LICENSE.txt, LICENSE.md, LICENSE-MIT, LICENCE, COPYING.rst,
# NOTICE.txt etc. all match). This is deliberately filesystem-based rather
# than parsing the PEP 639 `License-File` metadata field's paths, because
# those paths are recorded relative to a directory (sometimes the dist-info
# root, sometimes a `licenses/` subdirectory of it depending on the build
# tool and version that produced the wheel) and are more fragile to
# reconstruct than just scanning what the dist-info directory actually ships.
_LICENSE_PREFIXES = ("LICENSE", "LICENCE", "COPYING")
_NOTICE_PREFIXES = ("NOTICE",)


def _dist_info_dirname(dist: metadata.Distribution) -> str | None:
    """The `<name>-<version>.dist-info` path component for this distribution."""
    for f in dist.files or []:
        for part in Path(str(f)).parts:
            if part.endswith(".dist-info"):
                return part
    return None


def license_files_for(dist: metadata.Distribution) -> list[tuple[str, str]]:
    """Return [(relative_path, text), ...] for every license/notice file
    shipped inside this distribution's own dist-info directory."""
    dist_info = _dist_info_dirname(dist)
    if dist_info is None:
        return []

    found = []
    for f in dist.files or []:
        parts = Path(str(f)).parts
        if not parts or parts[0] != dist_info:
            continue
        basename = parts[-1]
        upper = basename.upper()
        if not (upper.startswith(_LICENSE_PREFIXES) or upper.startswith(_NOTICE_PREFIXES)):
            continue
        # dist.files paths are relative to the distribution's anchor (the
        # site-packages root) and so are prefixed with the dist-info dirname
        # itself -- but Distribution.read_text() resolves its argument
        # relative to the dist-info directory (self._path), which already
        # *is* that prefix. Passing the dist.files-style path straight
        # through silently returns None (FileNotFoundError is swallowed).
        # Strip the leading "<name>-<version>.dist-info/" segment before
        # reading, e.g. "click-8.4.2.dist-info/licenses/LICENSE.txt" ->
        # "licenses/LICENSE.txt".
        relative_to_dist_info = "/".join(parts[1:])
        try:
            text = dist.read_text(relative_to_dist_info)
        except (OSError, UnicodeDecodeError):
            text = None
        if text:
            found.append((str(f), text.rstrip("\n")))
    # Deterministic order regardless of RECORD ordering.
    found.sort(key=lambda pair: pair[0])
    return found


def spdx_hint(dist: metadata.Distribution) -> str:
    """Best-effort license identifier from package metadata. Not authoritative
    -- THIRD_PARTY_NOTICES.md carries the maintainer-verified SPDX table."""
    expr = dist.metadata.get("License-Expression")
    if expr:
        return expr
    classifiers = [v for k, v in dist.metadata.items() if k == "Classifier" and v.startswith("License ::")]
    if classifiers:
        return "; ".join(c.split("::")[-1].strip() for c in classifiers)
    raw = dist.metadata.get("License")
    if raw and raw.strip() and raw.strip().upper() != "UNKNOWN":
        return raw.strip()
    return "(not declared in package metadata)"


def build_report(names: set[str]) -> tuple[str, list[str]]:
    """Return (report_text, package_names_with_no_license_text_found)."""
    sections = []
    missing = []
    for norm in sorted(names):
        try:
            dist = metadata.distribution(norm)
        except metadata.PackageNotFoundError:
            missing.append(norm)
            continue
        display_name = dist.metadata.get("Name", norm)
        version = dist.metadata.get("Version", "unknown")
        files = license_files_for(dist)
        if not files:
            missing.append(norm)
            continue
        header = f"{'=' * 78}\n{display_name} {version}\nSPDX (declared): {spdx_hint(dist)}\n{'=' * 78}\n"
        body = "\n\n".join(f"--- {path} ---\n{text}" for path, text in files)
        sections.append(header + "\n" + body)
    report = (
        "Third-Party License Texts\n"
        "==========================\n\n"
        "Verbatim license (and NOTICE, where present) text for every runtime\n"
        "dependency bundled in this distribution, harvested from each package's\n"
        "installed dist-info metadata. See THIRD_PARTY_NOTICES.md for the\n"
        "human-curated summary table (package name, license, project URL).\n\n"
        + "\n\n".join(sections) + "\n"
    )
    return report, missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_OUTPUT,
        help=f"Where to write LICENSES.txt (default: {DEFAULT_OUTPUT}).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Print the package list and per-package file counts as they're processed.",
    )
    args = parser.parse_args()

    direct = declared_runtime_requirements()
    names = runtime_closure(direct)
    names = {n for n in names if n not in {"pip", "setuptools", "wheel"}}

    if args.verbose:
        print(f"Scanning {len(names)} runtime distribution(s): {', '.join(sorted(names))}")

    report, missing = build_report(names)

    if missing:
        print("ERROR: no license/notice text found (or package not installed) for:", file=sys.stderr)
        for m in missing:
            print(f"  {m}", file=sys.stderr)
        print(
            "\nEvery bundled runtime dependency must ship a license file this "
            "script can find in its dist-info directory. If a package "
            "genuinely ships none, add an explicit exception here with a "
            "comment explaining why, rather than silently shipping an "
            "undocumented binary.",
            file=sys.stderr,
        )
        return 1

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(report, encoding="utf-8")
    print(f"OK: wrote license text for {len(names)} package(s) to {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
