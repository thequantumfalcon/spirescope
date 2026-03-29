# Changelog

## v2.9.2

### Fixed

- **Card rarity**: 402 cards corrected from wiki.gg Lua data modules — most were incorrectly labeled "Common" when they should be Uncommon, Rare, or Ancient
- **Card name**: "All For One" corrected to "All for One" (Defect)
- **Card character**: Brightest Flame moved from Ironclad to Colorless (Ancient)
- **Deprecated Card** removed — explicitly removed from game
- **Event names**: 9 events corrected to match canon naming (case, hyphens, articles, punctuation)
  - Aroma Of Chaos → Aroma of Chaos
  - Field Of Man Sized Holes → Field of Man-Sized Holes
  - Lost Wisp → The Lost Wisp
  - Room Full Of Cheese → Room Full of Cheese
  - Self Help Book → Self-Help Book
  - Sunken Statue → The Sunken Statue
  - Tablet Of Truth → Tablet of Truth
  - The Future Of Potions → The Future of Potions?
  - This Or That → This or That?
- **Vine Bracelet** relic: missing rarity set to Event
- **5 enemies enriched** with gameplay tips: Battle Friend V2, Decimillipede, Slithering Strangler, The Kin, Toadpoles
- **The Kin** classified as Act 1 boss

### Data Audit Summary

- cards.json: 588 (was 589, removed Deprecated Card)
- relics.json: 298 (11 more than untapped.gg — all verified as real game items)
- potions.json: 63 (perfect match with untapped.gg)
- events.json: 64 (56 on untapped.gg + 8 save-discovered)
- enemies.json: 170 (most complete dataset available, 0 empty tips remaining)
- epochs.json: 49 (complete, manually verified)

## v2.7.0

### Added
- **Data enrichment**: 589 cards (+43), 298 relics (+3), 64 events (+24), 170 enemies (+23) from canon sources
- **Modded save detection**: auto-detects both vanilla and modded save paths, prefers most recent
- **Shutdown endpoint**: POST /shutdown + red Stop button in nav bar (replaces console window)
- **README**: Why SpireScope, Works Without STS2, Using with Mods, Streamer Mode, Steam Deck sections
- **GitHub Pages**: dark gothic landing page at thequantumfalcon.github.io/spirescope
- **Repo hygiene**: SECURITY.md, issue templates, CHANGELOG backfilled, 15 topic tags

### Fixed
- Download link now version-agnostic (Spirescope-windows.zip) — no more stale links
- Capital-S URLs in pyproject.toml, CONTRIBUTING.md, footer template
- Author metadata: full name + email in pyproject.toml
- Light theme WCAG AA contrast on page-accent headings
- console=False in PyInstaller spec — no more black terminal window

### Changed
- CI: Python 3.13 added to test matrix
- Release workflow: uploads both versioned and fixed-name zip assets

## v2.6.0

### Added
- **Run Detail**: cards offered, potions gained, monsters fought, gold per floor, HP timeline chart
- **Boss Intelligence**: boss matchup table, relic tier list by character, card pick heatmap
- **Home Page**: win streak tracker, next epoch suggestions
- **Live Tracker**: encounters won log, events encountered list
- Cinzel font SIL Open Font License attribution
- 613 tests passing on Python 3.11 + 3.12

## v2.5.0

### Added
- **Version & Time Range Filters**: filter runs and analytics by game version or date range
- Version dropdown auto-populated from run history
- Time presets: 7-day, 30-day, 90-day, All
- Custom date range with native date pickers
- API support for version/from/to query params on /api/runs and /api/analytics
- 5 new card stubs, 2 new enemy stubs (542 cards, 143 enemies total)
- 18 new tests (613 total)

## v2.4.0

### Added
- **Personal Records** (/records): fastest win, highest ascension, best streak, flawless bosses
- **10 New Analytics**: per-act breakdown, combat efficiency, archetype performance, card pick timing, encounter danger ratings, gold economy, co-op stats, healing sources, card regret analysis
- Seed copy button, archetype badge, danger grades on enemy pages

## v2.3.0

### Added
- **Epochs Progression Tracker** (/epochs): all 49 epoch unlock states with filters
- Enhanced live tracker: merged save+log data, coaching alerts, post-run analysis
- Hardened sync URL validation, rate limit headers
- Version badge on landing page
- 565 tests passing

## v2.2.1

### Fixed

- **Fetcher: energy/star markup conversion** — `[energy:N]` and `[star:N]` wiki markup now converts to readable text ("2 Energy", "1 Star") instead of being silently deleted
- **Fetcher: prefixed icon handling** — Correctly handles `6[star:1]` → "6 Star" (digit before tag takes precedence)
- **Fetcher: merge preserves curated data** — Wiki scrapes no longer overwrite non-empty existing fields with empty values; falsy-but-valid values (0, False, []) are handled correctly
- **Fetcher: character normalization** — Wiki's "The Regent" automatically normalized to "Regent" to match app convention
- **Fetcher: rarity default** — Changed from "Common" (which corrupted 92% of cards) to empty string (honest about missing data)
- **Cards: 67 cards** mislabeled as "The Regent" normalized to "Regent"
- **Cards: DEFEND_SILENT/STRIKE_SILENT** restored to character "Silent" with rarity "Starter"
- **Cards: 269 descriptions** had embedded newlines replaced with spaces
- **Cards: 9 descriptions** had missing Energy/Star values restored from canon wiki data (Bloodletting, Adrenaline, Alignment, Big Bang, Black Hole, Convergence, Genesis, Solar Strike, Venerate)
- **Cards: missing Offering** added from canon wiki data
- **Cards: 43 entries** missing `description_upgraded` field now have it
- **Relics: 17 descriptions** had truncated Energy/Star values restored (Lantern, Glowing Orb, Happy Flower, Bread, etc.)
- **Relics: 16 descriptions** had double-space gaps from stripped icons fixed (Sozu, Velvet Choker, Philosopher's Stone, etc.)
- **Relics: 3 empty rarities** filled (Glowing Orb, Medical Kit, Mysterious Cocoon)
- **Relics: Deprecated Relic** placeholder removed
- **Potions: 4 truncated descriptions** fixed (Energy Potion, Star Potion, Cure All, Radiant Tincture)
- **Potions: Liquid Memories** stripped Energy icon restored
- **Potions: Deprecated Potion** placeholder removed
- **Enemies: 45 display names** had "Monster." prefix stripped
- **Sync: User-Agent** updated from stale "Spirescope/2.1" to dynamic version
- **CSS: muted text contrast** bumped from 4.48:1 to 4.65:1 (meets WCAG AA)

## v2.2.0

### Added

- **Keyboard shortcuts** — Press `?` for help overlay, `h/c/r/a/d/l` to navigate pages, `/` to focus search, `Esc` to close
- **Ascension filtering on analytics** — Filter analytics by ascension level with clickable filter bar
- **HTML export for runs** — Export any run as a self-contained HTML file with inlined CSS for offline viewing
- **Run comparison** — Side-by-side comparison of two runs with deck diff, relic diff, stat comparison, and analysis insights
- **ruff linter in CI** — Automated code quality checks on every push and PR

### Changed

- Run history page now includes compare checkboxes for selecting two runs
- Export button on run detail split into "Export JSON" and "Export HTML"
- Analytics cache keyed by ascension level for filtered results

### Fixed

- CSP violation in runs page: replaced inline `onchange` handler with external JS

## v2.1.0

### Added
- **Deck analyzer qty steppers** — replace checkboxes with +/- quantity controls (1-5 per card), save/load decks in new format
- **Enriched cost curve** — stacked type bars (Attack/Skill/Power), average cost, energy-per-hand stat, playability notes
- **Run-to-analyzer linking** — "Analyze Deck" buttons on run detail and live pages pre-load decks into the analyzer
- **Server-side deck pre-selection** — decks from run history render as pre-selected in the analyzer HTML (no JS dependency)
- **Card info popovers** — inline card details with synergy lookup on the deck analyzer page
- **Collections page search** — search and filter on the collections page

### Changed
- Deck analyzer card selection uses quantity model instead of checkboxes
- Static JS files use content-hash cache busting (`?v=` MD5 suffix)
- Inline scripts replaced with data attributes for CSP compliance

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
- **Fetcher resilience** — retry on network error, zero-result guard prevents overwriting good data
- **Dynamic version** — footer shows version from package metadata

### Changed
- All templates refactored to use CSS classes instead of inline styles
- README updated with accurate test count, new features, CLI commands, and API endpoints
- CONTRIBUTING updated with CSS and testing conventions

### Fixed
- Fetcher no longer overwrites large existing datasets when wiki returns empty/tiny results

## v1.0.0

Initial release with card/relic/potion/enemy/event browsing, deck analyzer, live run tracking, run history, strategy guides, global search, co-op support, and dark theme.
