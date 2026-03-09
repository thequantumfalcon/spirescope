# Changelog

## v2.0.0

### Added
- **Dark/Light theme toggle** — dark gothic fantasy aesthetic (Cinzel serif, gold/crimson palette) with warm parchment light mode, persisted via localStorage
- **Mod support** — load custom cards, relics, and enemies from JSON files in a mods directory with source badges and collision policy
- **Advanced analytics** — HP tracking, death floor heatmaps, ascension curves, card quality analysis, damage percentiles
- **Run import/export** — `.spirescope.json` format for sharing run data between players
- **Live run coaching** — counter-cards, synergy hints, danger alerts, AoE/Draw weakness detection
- **Content creator API** — paginated JSON endpoints with CSV export and optional API key bypass
- **Community aggregation** — aggregate stats from contributed runs with anti-manipulation caps, CLI export/reset
- **Multi-source community data** — Steam reviews, guides, and discussions alongside Reddit; weighted tier consensus, source badges on community page
- **Collections page** — track card/relic discovery progress with ascension filtering
- **Sync commands** — `sync-up` / `sync-down` for aggregate stats via optional sync service
- **`--no-browser` flag** — start server without auto-opening browser

### Changed
- Community module refactored from single file to package (`sts2/community/`) with pluggable source architecture
- Routes extracted from `app.py` into dedicated `routes.py`
- Hero background changed to gothic eye-in-spire concept art with cache-busting
- All theme colors verified WCAG AA contrast (4.5:1 ratio)

### Fixed
- SSE hash computation corrected
- CSRF token widened to 64-bit
- Cache pre-warming for faster startup
- Event loop blocking eliminated via async cache accessors
- Input validation hardened on all query parameters

## v1.1.0

### Added
- **Standalone executable** — PyInstaller build produces a click-to-run exe (no Python required). Run `python build.py` to create `dist/Spirescope/`
- **Analytics page** — aggregate stats: per-character win rates, floor survival, card pick rates, causes of death
- **Community page** — Reddit-sourced tier lists, meta posts, and community tips on detail pages
- **User guide** — in-app guide covering setup, features, configuration, and troubleshooting
- **Save-only update mode** — `spirescope update --save-only` discovers entities from saves without network
- **Auto-discovery** — cards, relics, and potions are now auto-discovered from save data (in addition to enemies/events)
- **Data status badge** — home page shows save file connection status and last wiki update
- **CLI improvements** — `--help`, `--version`, named commands (`serve`, `update`, `community`), unknown command handling
- **CSS utility system** — extracted 200+ inline styles into reusable CSS classes
- **SVG logo** — branded spire + telescope lens logo replaces text
- **Mobile navigation** — hamburger menu for small screens (768px and 480px breakpoints)
- **Accessibility** — `aria-current="page"` on nav links, focus-visible rings, skip-to-content link
- **Card hover animations** — subtle lift + shadow on card hover
- **Live badge pulse** — CSS animation on the live run indicator
- **CSS cache busting** — MD5 hash appended to stylesheet URL
- **Scraper resilience** — retry on network error, zero-result guard prevents overwriting good data
- **Dynamic version** — footer shows version from package metadata

### Changed
- All templates refactored to use CSS classes instead of inline styles
- README updated with accurate test count, new features, CLI commands, and API endpoints
- CONTRIBUTING updated with CSS and testing conventions

### Fixed
- Scraper no longer overwrites large existing datasets when wiki returns empty/tiny results

## v1.0.0

Initial release with card/relic/potion/enemy/event browsing, deck analyzer, live run tracking, run history, strategy guides, global search, co-op support, and dark theme.
