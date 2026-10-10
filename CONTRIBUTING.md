# Contributing to Spirescope

Thanks for your interest in contributing!

## Getting Started

```bash
git clone https://github.com/thequantumfalcon/spirescope.git
cd spirescope
pip install -e ".[dev]"
pytest -q
```

## Development

- **Python 3.11+** required
- Run `python -m sts2` to start the dev server at http://127.0.0.1:8000
- Run `python -m sts2 update` to fetch fresh game data
- Run `python -m sts2 community` to pull community data from Steam
- Run `pytest -q --tb=short` before submitting changes. The suite hides your game install, saves and Spirescope state behind a temporary directory, so a local run checks the same data as CI and never touches your own files.

## Project Layout

```
sts2/
  __main__.py        # CLI entry point
  app.py             # FastAPI app, middleware, security headers
  routes.py          # All route handlers
  analytics.py       # Run analytics computation
  aggregate.py       # Aggregate stats computation and merging
  card_properties.py # Native card properties and exact-build views of customized copies
  community/         # Community data sourcing
    __init__.py      # Orchestrator + re-exports
    _types.py        # Shared types, extraction functions
    _merge.py        # Weighted merge logic
    steam.py         # Steam data fetcher (reviews, guides, discussions)
  config.py          # Auto-detected paths and settings
  corrections/       # Version-scoped corrections for known source defects
    rarity.py        # Historical rarity map (explicit maintenance tool)
    text.py          # Card text pinned from official patch notes
  data_health.py     # Side-effect-free dataset checks (refresh, validate-data)
  deck_instances.py  # Positional card copies with upgrade/enchantment metadata
  fetcher.py         # Data refresh (slaythespire2.gg scraping, staged install, save file discovery)
  game_version.py    # Reads the installed game's release identity
  i18n.py            # Interface translation, content overlays
  identities.py      # Mappings from older catalog IDs to native game IDs
  knowledge.py       # Search, filter, synergy, and deck analysis engine
  localize.py        # Builds translated game text from your install
  logparser.py       # Game log tailer for live run tracking
  mechanics.py       # Exact-version mechanics profiles
  models.py          # Pydantic models for all game entities
  patches.py         # Patch manifest: build id to patch era
  persist.py         # Atomic writes for the small state files
  saves.py           # Save file parser (progress + run history + co-op)
  sources.py         # Data source adapters for the update pipeline
  state_lock.py      # Cross-process locks for state transactions
  sync.py            # Aggregate sync client (upload/download)
  updater.py         # Auto-update checker + data-bundle installer
  watcher.py         # File watcher with debounce + polling fallback
  behavior.py, cascade.py, drift.py, ghost.py, graveyard.py,
  hypothesis.py, integrity.py, prophecy.py, rivalry.py,
  spectral.py        # The advanced analytics modules
  data/              # JSON game data; mods/ here holds only the mod format README
  locales/           # Interface translations; content/ holds text built by `localize`
  templates/         # Jinja2 HTML templates
  static/            # CSS, fonts, images, JS
scripts/             # Maintenance tools and correction wrappers
tests/               # pytest + pytest-asyncio (browser tests deselected by default)
                     # + Playwright browser tests: pip install -e ".[browser]"
                     #   && playwright install chromium && pytest -m browser
```

Mod files are user content: they load from `STS2_MODS_DIR`, which defaults to
`mods/` under the state directory (beside the executable in packaged builds),
not from `sts2/data/mods/`.

## Git Hooks

The repository ships three hooks in `.githooks/`. Git does not run them until
you point it there, once per clone:

```bash
git config core.hooksPath .githooks
```

- `pre-commit` rejects a commit whose staged changes contain AI-tool
  authorship attribution lines.
- `commit-msg` applies the same check to the commit message.
- `pre-push` re-checks the messages of the commits being pushed and the
  tracked files at `HEAD`, and blocks the push on a match.

The `No AI Attribution` workflow in `.github/workflows/` runs the same kind of
scan on every push and pull request.

## CSS Conventions

- **No inline styles** — use CSS utility classes from `style.css` instead
- Utilities: `.text-sm`, `.text-muted`, `.text-red`, `.mb-md`, `.flex`, `.gap-sm`, etc.
- Component classes: `.card-link`, `.card-win`, `.card-loss`, `.card-tip`, `.breadcrumb`, `.community-tips`
- Only use inline `style=` for data-driven values (bar widths, chart heights)
- Mobile-first: test at 768px and 480px breakpoints
- Dark/light theme: use CSS custom properties (`var(--bg)`, `var(--text)`, etc.)

## Testing Conventions

- pytest with pytest-asyncio in auto mode
- Async test functions: use `async def test_*` (not `asyncio.get_event_loop()`)
- Mock external dependencies (save files, network) — never hit real endpoints in tests
- All tests must pass before merge

## Guidelines

- Keep changes focused — one feature or fix per PR
- Add tests for new routes or logic
- Don't include game data changes (sts2/data/*.json) in feature PRs unless the change adds new fields. Data refreshes are committed and released separately by the maintainer through the data-release pipeline — see docs/DATA_MAINTENANCE.md
- Run `ruff check sts2/ tests/` to lint before submitting
- All tests must pass before merge

## Reporting Issues

Open an issue on GitHub with:
- What you expected vs. what happened
- Steps to reproduce
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
