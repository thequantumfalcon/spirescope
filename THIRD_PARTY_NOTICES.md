# Third-Party Notices

SpireScope incorporates work from the following third parties. The full
license text for each is available at the URLs cited or in the upstream
package metadata.

## Runtime Python dependencies

| Package | License | Project |
|---|---|---|
| FastAPI | MIT | https://github.com/fastapi/fastapi |
| Starlette | BSD-3-Clause | https://github.com/encode/starlette |
| Uvicorn | BSD-3-Clause | https://github.com/encode/uvicorn |
| Jinja2 | BSD-3-Clause | https://github.com/pallets/jinja |
| Pydantic | MIT | https://github.com/pydantic/pydantic |
| python-multipart | Apache-2.0 | https://github.com/Kludex/python-multipart |
| watchdog | Apache-2.0 | https://github.com/gorakhargosh/watchdog |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| PyInstaller | GPL-2.0-or-later with bootloader exception | https://github.com/pyinstaller/pyinstaller |

PyInstaller is GPL-2.0-or-later, but its standard bootloader-exception
clause explicitly permits using PyInstaller to build and distribute
non-free programs (including non-GPL ones such as this MIT release).
SpireScope itself remains MIT-licensed; the bundled Python runtime in
the PyInstaller-produced binary is unmodified.

## Development / test dependencies

| Package | License | Project |
|---|---|---|
| pytest | MIT | https://github.com/pytest-dev/pytest |
| pytest-asyncio | Apache-2.0 | https://github.com/pytest-dev/pytest-asyncio |
| pytest-playwright | Apache-2.0 | https://github.com/microsoft/playwright-pytest |
| playwright (Python) | Apache-2.0 | https://github.com/microsoft/playwright-python |
| ruff | MIT | https://github.com/astral-sh/ruff |

## Fonts

| Asset | License | Source |
|---|---|---|
| Cinzel (woff2 subsets in `sts2/static/fonts/`) | SIL Open Font License 1.1 | https://fonts.google.com/specimen/Cinzel |

The Cinzel typeface is © Natanael Gama. The OFL text is bundled at
`sts2/static/fonts/OFL.txt`.

## Project artwork

| File | Description |
|---|---|
| `sts2/static/hero-bg.jpg` | Dark gothic background used on the home page |
| `sts2/static/logo.jpg` | 120x120 project logo |
| `sts2/static/favicon.ico` | Browser favicon (multi-resolution) |

These decorative assets are part of the SpireScope project and are
covered by the project's MIT license (see `LICENSE`). They are not
derived from, and do not reproduce, any Mega Crit Games artwork or
copyrighted character/card/relic art.

## Game data sources

SpireScope renders factual game data (card names, costs, descriptions,
relic effects, enemy stats, event outcomes) about *Slay the Spire 2*.
The game itself, its art, music, sound, and original creative content
are the property of Mega Crit Games and are NOT redistributed by this
project. Bundled data is derived from:

| Source | License / Terms | Use |
|---|---|---|
| [slaythespire.wiki.gg](https://slaythespire.wiki.gg/) | CC BY-SA 4.0 (wiki.gg standard) | Primary canonical source for cards, relics, potions, events, patch notes |
| [slaythespire2.gg](https://slaythespire2.gg/) | Scraped under their robots.txt permission. Disallowed paths (`/api/`, `/admin/`, `/analysis/`, `/planner/`) are never requested. We identify ourselves with a project-named User-Agent. Their AI-train opt-out is respected — this project is not training models. | Cross-reference data for cards, relics, potions, events |
| [sts2.untapped.gg](https://sts2.untapped.gg/) | Public reference; not actively scraped | Tertiary cross-reference |
| Reddit public JSON (e.g. r/slaythespire2) | Reddit User Agreement; non-commercial reads with rate-limiting | Community tips in the `/community` view |
| Steam community pages | Valve ToS (public reading) | Steam guide highlights in the `/community` view |
| NeonLightsMedia Epochs guide | Cited reference (not redistributed verbatim) | Epoch unlock requirement notes in `sts2/data/epochs.json` |

Wiki-derived bundled JSON in `sts2/data/` is republished under CC BY-SA
4.0 alongside the project's MIT license; downstream forks should retain
both notices. Code in this repository remains MIT.

## Trademarks

*Slay the Spire*, *Slay the Spire 2*, and *Mega Crit* are trademarks
of Mega Crit Games. SpireScope is a fan-made tool and is not
affiliated with, endorsed by, or associated with Mega Crit Games. The
trademarks are used here for nominative identification only.

## Reporting issues

If you are a rights-holder for any of the above and have a concern
about the way SpireScope cites or uses your work, open an issue at
https://github.com/thequantumfalcon/spirescope/issues and we will
respond promptly.
