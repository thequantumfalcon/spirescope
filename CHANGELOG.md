# Changelog

## v2.9.3

### Security

- **`/shutdown` auth** — now requires a valid admin token or an actual loopback client (`request.client.host`), rather than trusting a spoofable `Referer` header. The previous `"127.0.0.1" in referer` substring check was bypassable by any cross-origin page hosted under a path containing `127.0.0.1` (e.g. `http://attacker.com/127.0.0.1.html`).
- **CSRF future-timestamp window closed** — `validate_csrf_token` was using `abs(time.time() - ts)`, accepting future timestamps up to 4 h. One-sided check now: future skew capped at 60 s.
- **SSE atomic reserve** — `_sse_active += 1` moved inside the request handler before `StreamingResponse` returns. Previously the increment was deferred inside `event_generator`, allowing concurrent requests to all pass the cap check.
- **Admin token visibility** — auto-generated `_ADMIN_TOKEN` (when `SPIRESCOPE_ADMIN_TOKEN` env var is unset) is now logged once at startup so operators can actually use admin endpoints.
- **`merge_aggregate` first-import cap** — applied `_MIN_IMPORT_CAP` even on first import to prevent a malicious file from anchoring future merges with bogus stats.

### Fixed

- **Windows release hardening** — removed UPX compression from the PyInstaller build to reduce antivirus false positives on the packaged executable.
- **Windows startup behavior** — frozen builds now keep a visible console window open and do not auto-open the browser unless explicitly requested with `--browser` or `SPIRESCOPE_OPEN_BROWSER=1`.
- **Frozen update checks** — packaged builds no longer make automatic GitHub update checks unless `SPIRESCOPE_CHECK_UPDATES=1` is set.
- **Live tracker background activity** — game log polling now runs on demand for live endpoints instead of as a permanent startup task.
- **Stop button CSP fix** — extracted inline `onclick` from `base.html` to `nav.js`. Existing `script-src 'self'` CSP was silently blocking the button in strict browsers.
- **Fetcher description newline regression** — `_clean_description` now collapses all internal whitespace (including embedded newlines from RSC payload structure and double-spaces left by stripped icons). v2.2.1 fixed 269 descriptions but the fix lived only in the data, not the fetcher, so each wiki refresh re-introduced them. Patched 192 descriptions on this refresh.
- **`/api/cards/{id}` 404 response** — was `PlainTextResponse`, broke JS clients calling `.json()`. Now JSON for both 200 and 404.
- **`steam.py` HTMLParser None crash** — `attr_dict.get("class", "")` returns the value if key exists, including `None`. `<div class>` (no value) → `"workshopItemTitle" in None` → TypeError. Coalesced 5 sites with `(.get("x") or "")`.
- **`steam.py` silent-staleness** — scraper now logs loud when the guide parser returns zero results (likely sign Steam HTML class names changed).
- **`live.js` SSE error setTimeout pile-up** — flapping SSE connection no longer stacks 10 s reload timers. `clearTimeout` before each new schedule.
- **`live.html` missing cache-buster** — `<script src="/static/live.js">` now uses `?v={{ live_js_hash }}` like every other JS file.
- **Reworked card text** — Drum of Battle (Power → Skill, new behavior), Synthesis (12 → 14 damage), Unrelenting (12 → 14 damage), Predator (Uncommon → Common). Patches 0.104.0 + 0.106.0.
- **`Monster.` prefix on 6 enemies** — Owl Magistrate, Slimed Berserker, Soul Nexus, Test Subject, Fabricator, Mecha Knight.

### Added

- **Run Integrity** wired to `/runs/{id}` — SHA-256 Merkle chain over every floor decision. Same hash means same run, byte-for-byte.
- **Cascade Map** wired to `/runs/{id}` — per-pick Δdamage / Δturns table showing each card's downstream impact.
- **Archetype Drift** wired to `/runs/{id}` — floor-by-floor archetype classification with drift alert when early and late dominant archetype diverge.
- **Deck Health Score** wired to `/deck/analyze` — spectral graph connectivity (0-100), orphan list, edge density.
- **Rivalry Seeds** wired to `/runs/compare` — when both runs played the same seed, surfaces floor-by-floor card-pick diffs.
- **Prophecy Engine** — new `/prophecy` route. Pre-run prediction: win probability, danger zone, recommendation based on historical runs at same character + similar ascension.
- **Tilt Detection + Anti-Patterns** wired to `/analytics` — session momentum banner; named anti-patterns (The Hoarder, Greedy Builder, Coward, Potion Paralysis).
- **Hypothesis Lab** — new `/hypothesis` route. Register strategic beliefs (`elite_skip`, `deck_size`, `card_pick`, `character` conditions); Bayesian-style update against run history; verdict after 10+ runs.
- **Nav links** for `/prophecy` and `/hypothesis`.
- **Stale-data badge** on home page — shows when wiki data is >30 days old, prompting `python -m sts2 update`. No silent network call on launch.
- **Fetcher field-validation + drift log** — rejects scraped batch when >10% of objects miss required fields; persists key-union baseline to `sts2/data/.fetcher_keys.json` to detect upstream schema drift between runs.
- **Log parser combat telemetry** — `cards_played`, `extra_turns`, `elites_defeated` now captured from `godot.log` and surfaced via `to_dict()` for SSE consumers. Closes part of the per-turn-analytics gap.
- **Release integrity** — Windows release workflow now publishes `.sha256` checksum files alongside the zip archive.

### Changed

- **Rate-limiter loopback skip** — middleware now bypasses rate-limit accounting when `STS2_HOST` is `127.0.0.1`, `localhost`, or `::1`. Eliminates an unbounded-dictionary memory growth path for the default single-user dashboard configuration. Tests force `STS2_HOST=0.0.0.0` in `conftest.py` to keep the rate-limit code path under coverage.
- **`python-multipart` minimum bump** 0.0.5 → 0.0.29 (security-relevant).
- **Pyright type-hint cleanup** — `_fetch_url` / `_fetch_reddit_json` return types now `str | None` / `dict | None` to match exhaustion-retry behavior.

### Data

- cards.json: 598 (+10) — wiki refresh + manual additions (Prepare, Not Yet) + Deprecated Card removal
- relics.json: 309 (+11) — wiki refresh added Neow's Bones, Phial Holster, Winged Boots, Hefty Tablet, Neow's Talisman, Pendulum, Silken Tress, etc.
- potions.json: 64 (+1)
- enemies.json: 184 (+14) — save-discovery + manual Aeonglass (Act 3 boss, 0.105.0)
- events.json: 67 (+3) — save-discovery
- Rarities canonicalized via `scripts/fix_card_rarity.py` against wiki.gg Lua module data.

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
