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
- Run `python -m sts2 update` to scrape fresh game data
- Run `pytest -q --tb=short` before submitting changes

## Project Layout

```
sts2/
  app.py          # FastAPI routes + middleware
  config.py       # Auto-detected paths and settings
  knowledge.py    # Search, filter, and deck analysis engine
  models.py       # Pydantic models
  saves.py        # Save file parser
  scraper.py      # Data scraper
  data/           # JSON game data
  templates/      # Jinja2 HTML templates
  static/         # CSS
tests/            # pytest test suite
```

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
