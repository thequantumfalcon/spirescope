# Spirescope

A web dashboard for **Slay the Spire 2** — card/relic/enemy lookup, deck analysis, live run tracking, run history, analytics, and strategy guides.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)
![Tests](https://img.shields.io/badge/tests-233%20passing-brightgreen)

## Features

- **Card Browser** — All cards across 5 characters with filters by character, type, rarity, cost, and keyword. Paginated (30 per page).
- **Relic & Potion Browser** — Browse and filter all relics and potions
- **Enemy Guides** — Boss patterns, elite strategies, and encounter tips
- **Event Guide** — Optimal choices for every event
- **Strategy Guides** — Per-character archetypes, key cards, key relics, and general tips
- **Deck Analyzer** — Select cards to get archetype detection, synergy analysis, weakness identification, and suggestions. Save/load decks to localStorage.
- **Live Run Tracker** — Real-time dashboard via Server-Sent Events (SSE) — no page reloads. Shows deck, relics, potions, HP, floor history, and deck analysis.
- **Run History** — Floor-by-floor breakdown of completed runs with HP tracking, card picks, and damage taken
- **Analytics** — Aggregate stats: per-character win rates, floor survival, card pick rates, and causes of death
- **Community** — Reddit-sourced tier lists, meta posts, and community tips on detail pages
- **Global Search** — Fuzzy search with "Did you mean?" suggestions across all entities
- **User Guide** — In-app guide covering setup, features, and troubleshooting
- **Co-op Support** — Track any player in a multiplayer run via `?player=N`
- **Dark Theme** — Gaming-friendly dark UI with character-specific colors

## Quick Start

```bash
pip install -e .
spirescope
```

Or run directly:

```bash
python -m sts2
```

Opens your browser at [http://127.0.0.1:8000](http://127.0.0.1:8000).

### Docker

```bash
docker build -t spirescope .
docker run -p 8000:8000 spirescope
```

## CLI Commands

```bash
spirescope              # Start the web dashboard (default)
spirescope serve        # Same as above
spirescope update       # Fetch latest data from the wiki + saves
spirescope update --save-only  # Discover from saves only (no network)
spirescope community    # Scrape community tips from Reddit
spirescope --help       # Show usage
spirescope --version    # Show version
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `STS2_SAVE_DIR` | Path to your STS2 save directory | Auto-detected |
| `STS2_GAME_DIR` | Path to STS2 game install | Auto-detected |
| `STS2_HOST` | Server bind address | `127.0.0.1` |
| `STS2_PORT` | Server port | `8000` |
| `SPIRESCOPE_ADMIN_TOKEN` | Token for `/api/reload` | Auto-generated (printed to stderr) |

### Save File Location

- **Windows**: `%APPDATA%\SlayTheSpire2\steam\<steam_id>\profile1\saves\`
- **macOS**: `~/Library/Application Support/SlayTheSpire2/steam/<steam_id>/profile1/saves/`
- **Linux**: `~/.local/share/SlayTheSpire2/steam/<steam_id>/profile1/saves/`

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/search?q=` | GET | Search all entities |
| `/api/cards/{card_id}` | GET | Card details + stats (JSON) |
| `/api/runs` | GET | Run history (JSON, filterable by character/result) |
| `/api/analytics` | GET | Aggregate analytics (JSON) |
| `/api/live?player=0` | GET | Current run state (JSON) |
| `/api/live/stream?player=0` | GET | SSE stream of live run updates |
| `/api/reload?token=` | POST | Hot-reload knowledge base (requires admin token) |
| `/health` | GET | Health check for monitors |
| `/robots.txt` | GET | Crawler directives |

## Security

- CSRF protection on all POST forms
- Content-Security-Policy, X-Frame-Options, Referrer-Policy, X-Content-Type-Options
- Per-IP rate limiting (60 req/min) with automatic memory cleanup
- Admin-token-gated reload endpoint (constant-time comparison)
- SSE connection cap (10 concurrent) with 5-minute idle timeout
- Jinja2 auto-escaping on all user-reflected input
- Log injection prevention (control character sanitization)
- Request body size limits on deck analysis
- Input validation on all query parameters

## Project Structure

```
sts2/
  __main__.py        # CLI entry point (serve, update, community)
  app.py             # FastAPI routes + middleware
  analytics.py       # Run analytics computation
  community.py       # Reddit community data scraper
  config.py          # Auto-detected paths and settings
  knowledge.py       # Search, filter, synergy, and deck analysis engine
  models.py          # Pydantic models for all game entities
  saves.py           # Save file parser (progress + run history + co-op)
  scraper.py         # Data scraper (wiki + save file discovery)
  data/              # JSON game data
  templates/         # Jinja2 HTML templates (19 pages)
  static/            # CSS
tests/               # 233 tests (pytest + pytest-asyncio)
```

## Requirements

- Python 3.11+
- Slay the Spire 2 (for save file features)

## License

MIT
