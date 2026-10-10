"""Build the GitHub release body for a tag from its CHANGELOG.md section.

A release is immutable once published, so its notes cannot be fixed after
the fact. The publisher used to fall back to a placeholder body ("See
CHANGELOG.md for details.") whenever no `## v<version>` section matched --
which is exactly what a tag pushed before `## Unreleased` was renamed would
produce. This refuses instead: exit status 1, and nothing written, when the
section is missing or has nothing under it but blank lines and sub-headings.

release.yml runs it twice: once early, with no --output, so a bad tag fails
before either platform build starts; and again in the publish job to write
the body it attaches.

Usage:
    python scripts/release_notes.py --tag v3.2.0                     # check only
    python scripts/release_notes.py --tag v3.2.0 --output RELEASE_NOTES.md
"""
import argparse
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CHANGELOG = REPO_ROOT / "CHANGELOG.md"


def section_for(text: str, version: str) -> str | None:
    """The text under `## v<version>`, up to the next `## ` heading.

    None when there is no such heading at all, so a missing section and an
    empty one can be reported differently.
    """
    match = re.search(
        rf"^## v{re.escape(version)}[ \t]*$(.*?)(?=^## |\Z)", text, re.M | re.S)
    return match.group(1).strip() if match else None


def has_content(body: str) -> bool:
    """Anything that is neither blank nor a sub-heading counts.

    Same rule as the CHANGELOG test for released sections: a paragraph is as
    good as a bullet list, but a heading with nothing under it is not notes.
    """
    return any(line.strip() and not line.lstrip().startswith("#")
               for line in body.splitlines())


def render(tag: str, body: str) -> str:
    header = '<h2 align="center">⚔ S P I R E S C O P E ⚔</h2>\n'
    header += ('<p align="center"><em>Card lookup · Deck analysis · Live run tracking'
               ' · Analytics for Slay the Spire 2</em></p>\n\n---\n\n')
    header += f"## What's New in {tag}\n\n"
    footer = '\n\n---\n\n### Download\n\n'
    footer += ('**[Download Spirescope for Windows](https://github.com/thequantumfalcon/'
               'spirescope/releases/latest/download/Spirescope-windows.zip)**')
    footer += ' — extract the zip, open the `Spirescope` folder, double-click `Spirescope.exe`.\n\n'
    footer += ('GitHub is the only official download source. Use the release assets here'
               ' and the attached checksum file.\n\n')
    footer += ('**Windows may flag the download as a virus.** Unsigned builds can trigger'
               ' security warnings. ')
    footer += 'A warning needs investigation; see '
    footer += ('[docs/ANTIVIRUS.md](https://github.com/thequantumfalcon/spirescope/blob/'
               'master/docs/ANTIVIRUS.md) ')
    footer += ('for checksum and provenance verification, reporting a detection, and'
               ' source installation.\n\n')
    footer += ('The versioned and unversioned zips are identical; the unversioned names'
               ' exist so the latest-download URL stays stable.')
    return header + body + footer


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="release tag, e.g. v3.2.0")
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    parser.add_argument("--output", type=Path,
                        help="write the full release body here; omit to only check")
    args = parser.parse_args(argv)

    version = args.tag.removeprefix("v")
    text = args.changelog.read_text(encoding="utf-8")
    body = section_for(text, version)
    if body is None:
        print(f"::error::{args.changelog.name} has no '## v{version}' section for tag "
              f"{args.tag}. Rename '## Unreleased' to '## v{version}' (and add a fresh "
              f"empty Unreleased heading above it) before tagging.")
        return 1
    if not has_content(body):
        print(f"::error::the '## v{version}' section of {args.changelog.name} is empty; "
              f"a release cannot ship without notes.")
        return 1
    if args.output:
        args.output.write_text(render(args.tag, body), encoding="utf-8")
    print(f"release notes for {args.tag}: {len(body.splitlines())} lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())
