<p align="center">
  <img src="docs/banner.png" alt="SpireScope" width="100%">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.11%2B-blue" alt="Python 3.11+">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="License: MIT">
  <img src="https://img.shields.io/badge/tests-387%20passing-brightgreen" alt="Tests">
</p>

A companion dashboard for **Slay the Spire 2** — card/relic/enemy lookup, deck analysis, live run tracking, run history, analytics, community meta, and strategy guides.

## Features

- **Card Browser** — All cards across 5 characters with filters by character, type, rarity, cost, and keyword. Paginated (30 per page).
- **Relic & Potion Browser** — Browse and filter all relics and potions
- **Enemy Guides** — Boss patterns, elite strategies, and encounter tips
- **Event Guide** — Optimal choices for every event
- **Strategy Guides** — Per-character archetypes, key cards, key relics, and general tips
- **Deck Analyzer** — Select cards to get archetype detection, synergy analysis, weakness identification, and suggestions. Save/load decks to localStorage.
- **Live Run Tracker** — Real-time dashboard via Server-Sent Events (SSE) — no page reloads. Shows deck, relics, potions, HP, floor history, counter-cards, synergy hints, and danger alerts.
- **Run History** — Floor-by-floor breakdown of completed runs with HP tracking, card picks, and damage taken. Import/export runs in `.spirescope.json` format.
- **Analytics** — Aggregate stats: per-character win rates, floor survival, card pick rates, HP curves, death floor heatmaps, and causes of death
- **Collections** — Track card/relic discovery progress with ascension filtering
- **Community Meta** — Tier lists and strategy posts from Reddit and Steam, community-voted card tiers, aggregate player stats with import/export
- **Global Search** — Fuzzy search with "Did you mean?" suggestions across all entities
- **User Guide** — In-app guide covering setup, features, and troubleshooting
- **Co-op Support** — Track any player in a multiplayer run via `?player=N`
- **Mod Support** — Load custom cards, relics, and enemies from JSON files in a mods directory
- **Dark/Light Theme** — Dark gothic fantasy aesthetic (Cinzel serif font, warm gold/crimson palette) with a warm parchment light mode toggle
- **Content Creator API** — Paginated JSON endpoints with CSV export and optional API key bypass

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

### Standalone Executable (No Python Required)

```bash
pip install -e ".[dev]"
python build.py
```

Output: `dist/Spirescope/Spirescope.exe` — zip the entire `dist/Spirescope/` folder and share it. Recipients just double-click `Spirescope.exe`.

### Docker

```bash
docker build -t spirescope .
docker run -p 8000:8000 spirescope
```

## CLI Commands

```bash
spirescope              # Start the web dashboard (default)
spirescope serve        # Same as above
spirescope serve --no-browser  # Start without opening browser
spirescope update       # Fetch latest data from the wiki + saves
spirescope update --save-only  # Discover from saves only (no network)
spirescope community    # Scrape community data from Reddit and Steam
spirescope export       # Export aggregate stats to JSON file
spirescope reset-stats  # Delete aggregate stats file
spirescope sync-up      # Upload local aggregate stats to sync service
spirescope sync-down    # Download and merge community stats from sync service
spirescope --help       # Show usage
spirescope --version    # Show version
```

## Configuration

| Variable | Description | Default |
|----------|-------------|---------|
| `STS2_SAVE_DIR` | Path to your STS2 save directory | Auto-detected |
| `STS2_GAME_DIR` | Path to STS2 game install | Auto-detected |
| `STS2_MODS_DIR` | Path to mods directory (JSON files) | `sts2/data/mods/` |
| `STS2_HOST` | Server bind address | `127.0.0.1` |
| `STS2_PORT` | Server port | `8000` |
| `STS2_COMMUNITY_SOURCES` | Community sources: `all`, `reddit`, `steam` | `all` |
| `STS2_SYNC_URL` | Sync service URL (opt-in) | Disabled |
| `STS2_SYNC_KEY` | API key for sync service | None |
| `SPIRESCOPE_ADMIN_TOKEN` | Token for `/api/reload` | Auto-generated |

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
| `/api/export/stats` | GET | Export aggregate player stats (JSON) |
| `/api/import/stats` | POST | Import/merge aggregate stats |
| `/api/reload?token=` | POST | Hot-reload knowledge base (requires admin token) |
| `/health` | GET | Health check for monitors |
| `/docs` | GET | Interactive API documentation (Swagger UI) |

## Security

- CSRF protection on all POST forms
- Content-Security-Policy, X-Frame-Options, Referrer-Policy, X-Content-Type-Options
- Per-IP rate limiting (60 req/min) with automatic memory cleanup
- Admin-token-gated reload endpoint (constant-time comparison)
- SSE connection cap (10 concurrent) with 5-minute idle timeout
- Jinja2 auto-escaping on all user-reflected input
- Log injection prevention (control character sanitization)
- Request body size limits on deck analysis and stats import
- Input validation on all query parameters
- Anti-manipulation caps on aggregate stats merging

## Project Structure

```
sts2/
  __main__.py        # CLI entry point
  app.py             # FastAPI app, middleware, security headers
  routes.py          # All route handlers
  analytics.py       # Run analytics computation
  community/         # Multi-source community scraper (Reddit + Steam)
    __init__.py      # Orchestrator + re-exports
    _types.py        # Shared types, extraction functions
    _merge.py        # Weighted merge logic
    reddit.py        # Reddit scraper (public JSON API)
    steam.py         # Steam scraper (reviews, guides, discussions)
  aggregate.py       # Aggregate stats computation and merging
  sync.py            # Aggregate sync client (upload/download)
  config.py          # Auto-detected paths and settings
  knowledge.py       # Search, filter, synergy, and deck analysis engine
  models.py          # Pydantic models for all game entities
  saves.py           # Save file parser (progress + run history + co-op)
  scraper.py         # Data scraper (wiki + save file discovery)
  watcher.py         # File watcher with debounce + polling fallback
  data/              # JSON game data + mods
  templates/         # Jinja2 HTML templates (21 pages)
  static/            # CSS, fonts (Cinzel), images, JS
tests/               # 387 tests (pytest + pytest-asyncio)
```

## Requirements

- Python 3.11+
- Slay the Spire 2 (for save file features)

## License

MIT
