# STS2 Assistant

A local web dashboard for **Slay the Spire 2** — card/relic/enemy lookup, deck analysis, run history, and strategy guides. All data stays on your machine.

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

## Features

- **Card Browser** — 217 cards across all 5 characters with filters by character, type, rarity, cost, and keyword
- **Relic & Potion Browser** — Browse and filter all relics and potions
- **Enemy Guides** — Boss patterns, elite strategies, and encounter tips
- **Event Guide** — Optimal choices for every event
- **Strategy Guides** — Per-character archetypes, key cards, key relics, and general tips
- **Deck Analyzer** — Select cards to get archetype detection, synergy analysis, weakness identification, and suggestions
- **Run History** — Floor-by-floor breakdown of your completed runs with HP tracking, card picks, and damage taken
- **Global Search** — Fuzzy search across all cards, relics, potions, enemies, and events
- **Dark Theme** — Gaming-friendly dark UI with character-specific colors

## Quick Start

```bash
# Install dependencies
pip install -e .

# Launch the dashboard
python -m sts2
```

Opens your browser at [http://127.0.0.1:8000](http://127.0.0.1:8000).

## Configuration

The assistant auto-detects your save file location. Override with environment variables if needed:

| Variable | Description | Default |
|----------|-------------|---------|
| `STS2_SAVE_DIR` | Path to your STS2 save directory | Auto-detected from AppData |
| `STS2_GAME_DIR` | Path to STS2 game install | Auto-detected from Steam |
| `STS2_HOST` | Server bind address | `127.0.0.1` |
| `STS2_PORT` | Server port | `8000` |

### Save File Location

The tool looks for save files in the standard location:
- **Windows**: `%APPDATA%\SlayTheSpire2\steam\<steam_id>\profile1\saves\`
- **macOS**: `~/Library/Application Support/SlayTheSpire2/steam/<steam_id>/profile1/saves/`
- **Linux**: `~/.local/share/SlayTheSpire2/steam/<steam_id>/profile1/saves/`

## Project Structure

```
sts2/
  __main__.py        # Entry point
  app.py             # FastAPI routes
  config.py          # Auto-detected paths and settings
  knowledge.py       # Search, filter, synergy, and deck analysis engine
  models.py          # Pydantic models for all game entities
  saves.py           # Save file parser (progress + run history)
  scraper.py         # Data update utility
  data/              # JSON game data (cards, relics, potions, enemies, events, strategy)
  templates/         # Jinja2 HTML templates
  static/            # CSS
```

## Updating Game Data

```bash
python -m sts2 update
```

This shows instructions for updating the JSON data files. You can also edit the files in `sts2/data/` directly.

## Requirements

- Python 3.11+
- Slay the Spire 2 (for save file features)

## License

MIT
