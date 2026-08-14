"""Check THIRD_PARTY_NOTICES.md against what's actually installed.

THIRD_PARTY_NOTICES.md hand-lists the runtime dependency closure. Nothing
keeps that list in sync automatically, so it drifts: an OS-conditional
transitive dependency (colorama, pulled in on Windows via click/uvicorn) was
missing from the "Runtime Python dependencies" table for several releases
before being added by hand.

This script re-derives the runtime closure from what's actually importable in
the current environment and reports any distribution missing from the notices
file. It is inherently environment-dependent: OS-conditional and
Python-version-conditional dependencies (colorama, uvloop, macholib,
pywin32-ctypes, pefile) only show up in the closure computed on a matching
platform/interpreter. Run it on the platform whose gap you're checking for.

Usage:
    python scripts/check_notices.py             # runtime closure (default)
    python scripts/check_notices.py --mode all   # every installed distribution
    python scripts/check_notices.py --verbose    # also print what WAS found
"""
import argparse
import importlib.metadata as metadata
import re
import sys
import tomllib
from pathlib import Path

try:
    from packaging.requirements import Requirement
except ImportError:  # pragma: no cover - packaging ships transitively via
    # mypy/pyinstaller in the dev extra lock, but guard anyway so a bare
    # runtime environment gets a clear error instead of a traceback.
    print("error: the 'packaging' package is required to run this script "
          "(pip install packaging)", file=sys.stderr)
    sys.exit(2)

REPO_ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = REPO_ROOT / "pyproject.toml"
DEFAULT_NOTICES = REPO_ROOT / "THIRD_PARTY_NOTICES.md"

# Packages that are part of the *build/packaging* toolchain rather than
# something distributed to end users, or that are already documented under a
# non-table section of the notices file (fonts, artwork, game data). Not
# runtime dependencies in the sense this checker cares about.
KNOWN_NON_RUNTIME = {"pip", "setuptools", "wheel"}


def _normalize(name: str) -> str:
    """PEP 503 normalization: case- and separator-insensitive comparison."""
    return re.sub(r"[-_.]+", "-", name).lower()


def declared_runtime_requirements(pyproject_path: Path = PYPROJECT) -> list[Requirement]:
    """The direct runtime deps from [project.dependencies], extras and all."""
    data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    deps = data.get("project", {}).get("dependencies", [])
    return [Requirement(d) for d in deps]


def runtime_closure(direct: list[Requirement]) -> set[str]:
    """Walk installed-package metadata to build the transitive runtime closure.

    Only follows requirements whose environment marker is satisfied (or
    unconditional). Extras are tracked per-package: pyproject.toml declares
    `uvicorn[standard]`, so uvicorn's own "standard"-gated requirements count,
    but that must NOT leak into evaluating some other package's unrelated
    same-named extra further down the graph (fastapi happens to also define a
    "standard" extra; pyproject.toml requests plain `fastapi`, not
    `fastapi[standard]`, so fastapi's extra-gated deps must stay excluded).
    """
    seen: set[str] = set()
    # (distribution name, the extras requested *of that specific package*)
    stack: list[tuple[str, frozenset[str]]] = [
        (req.name, frozenset(req.extras)) for req in direct
    ]
    while stack:
        name, extras = stack.pop()
        norm = _normalize(name)
        if norm in seen:
            continue
        seen.add(norm)
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            # Not installed in the current environment -- can't walk further,
            # but still record it as "expected" so it gets flagged if missing
            # from the notices file.
            continue
        for req_str in dist.requires or []:
            req = Requirement(req_str)
            if req.marker is not None:
                # A requirement applies if it's unconditional for *some*
                # active extra of this package (bare install == extra "").
                active = extras or frozenset({""})
                if not any(req.marker.evaluate({"extra": e}) for e in active):
                    continue
            stack.append((req.name, frozenset(req.extras)))
    return seen


def all_installed() -> set[str]:
    return {_normalize(d.name) for d in metadata.distributions() if d.name}


def missing_from_notices(names: set[str], notices_text: str) -> list[str]:
    haystack = notices_text.lower()
    missing = []
    for norm in sorted(names):
        if norm in KNOWN_NON_RUNTIME:
            continue
        # Accept either separator style ("python-multipart" / "python_multipart")
        # and a no-separator form ("typingextensions") to tolerate the notices
        # file's own display-name capitalization/spacing choices.
        candidates = {norm, norm.replace("-", "_"), norm.replace("-", "")}
        if not any(c in haystack for c in candidates):
            missing.append(norm)
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mode", choices=["runtime", "all"], default="runtime",
        help="'runtime' (default) checks the declared-dependency closure; "
             "'all' checks every distribution installed in this environment "
             "(noisy -- includes dev/build tooling never meant to be listed).",
    )
    parser.add_argument(
        "--notices", type=Path, default=DEFAULT_NOTICES,
        help="Path to THIRD_PARTY_NOTICES.md (default: repo root).",
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Also print the full set of names that were checked.",
    )
    args = parser.parse_args()

    notices_text = args.notices.read_text(encoding="utf-8")

    if args.mode == "runtime":
        direct = declared_runtime_requirements()
        names = runtime_closure(direct)
    else:
        names = all_installed()

    if args.verbose:
        print(f"Checked {len(names)} distribution name(s) ({args.mode} mode):")
        for n in sorted(names):
            print(f"  {n}")

    missing = missing_from_notices(names, notices_text)
    if missing:
        print(f"MISSING from {args.notices.name}:")
        for m in missing:
            print(f"  {m}")
        return 1

    print(f"OK: all checked distributions ({args.mode} mode) are documented in {args.notices.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
