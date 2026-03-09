# Contributing to Spirescope

Thanks for your interest in contributing!

## Getting Started

```bash
git clone https://github.com/thequantumfalcon/Spirescope.git
cd Spirescope
pip install -e ".[dev]"
pytest -q
```

## Development

- **Python 3.11+** required
- Run `python -m sts2` to start the dev server at http://127.0.0.1:8000
- Run `python -m sts2 update` to fetch fresh game data
- Run `python -m sts2 community` to pull community data from Reddit and Steam
- Run `pytest -q --tb=short` before submitting changes

## Project Layout

```
sts2/
  __main__.py        # CLI entry point
  app.py             # FastAPI app, middleware, security headers
  routes.py          # All route handlers
  analytics.py       # Run analytics computation
  aggregate.py       # Aggregate stats computation and merging
  community/         # Multi-source community data (Reddit + Steam)
    __init__.py      # Orchestrator + re-exports
    _types.py        # Shared types, extraction functions
    _merge.py        # Weighted merge logic
    reddit.py        # Reddit data fetcher (public JSON API)
    steam.py         # Steam data fetcher (reviews, guides, discussions)
  config.py          # Auto-detected paths and settings
  fetcher.py         # Data fetcher (wiki + save file discovery)
  knowledge.py       # Search, filter, synergy, and deck analysis engine
  logparser.py       # Game log tailer for live run tracking
  models.py          # Pydantic models for all game entities
  saves.py           # Save file parser (progress + run history + co-op)
  sync.py            # Aggregate sync client (upload/download)
  updater.py         # Auto-update checker
  watcher.py         # File watcher with debounce + polling fallback
  data/              # JSON game data + mods
  templates/         # Jinja2 HTML templates
  static/            # CSS, fonts, images, JS
tests/               # 494 tests (pytest + pytest-asyncio)
```

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
- All 494 tests must pass before merge

## Guidelines

- Keep changes focused — one feature or fix per PR
- Add tests for new routes or logic
- Don't commit game data changes (sts2/data/*.json) unless adding new fields
- Follow existing code style (no linter config — just match what's there)
- All tests must pass before merge

## Reporting Issues

Open an issue on GitHub with:
- What you expected vs. what happened
- Steps to reproduce
- Your Python version and OS

## License

By contributing, you agree that your contributions will be licensed under the MIT License.
