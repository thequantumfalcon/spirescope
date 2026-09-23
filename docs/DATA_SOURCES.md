# Data source decision record (P1 / V5)

**Original decision:** 2026-07-22 · **Implementation review:** 2026-09-22

## Decision

| Priority | Source | Method | Role |
|---|---|---|---|
| Primary | slaythespire2.gg | Next.js RSC payload extraction (`/cards`, `/relics`, `/potions`) | Structured cards/relics/potions; preferred supplied fields |
| Secondary | slaythespire.wiki.gg | MediaWiki API, `Module:*/StS2 data` Lua modules | Fills gaps; full fallback when primary is down |
| Tertiary | save files | `--save-only` discovery (existing) | Names/ids only, offline |

## Original source-selection evidence

The observations below are dated July 2026, not a current completeness or
patch-compatibility certification. See [GAME_COVERAGE.md](GAME_COVERAGE.md) for
the latest installed-build audit and remaining evidence requirements.

**slaythespire2.gg (primary):** whole catalog in 3 requests; structured records
(id, name, character, rarity, energy, cardType, both description variants);
current within days of a patch (v0.109.0 content present 2026-07-22, image
URLs versioned `cards-composite-v0.109`). robots.txt permits general scraping;
`/api`, `/admin`, `/analysis`, `/planner` are disallowed and never requested.
Risk: RSC markup drifts silently (two breaking changes between 2026-05 and
2026-07) — mitigated by extraction validation, count guards, and the secondary.

**slaythespire.wiki.gg (secondary):** stable MediaWiki API (not HTML
scraping); data lives in per-type Lua modules — cards per character
(`Module:Cards/StS2 data/<Character>`), relics and potions in single modules —
in a regular table format parseable with stdlib regex. Verified current
(carries v0.109.0 rarity changes). robots.txt: `User-agent: * → Allow: /`
with content-signal `use=reference` (the disallow list targets AI-training
crawlers, not reference tools); requests use the project User-Agent and the
standard 1s delay. Content is CC BY-SA 4.0 — attribution is in
THIRD_PARTY_NOTICES.md and README. Risk: community-maintained, may lag a
patch by a few days; no upgraded-description field for relics.

## Implemented merge and validation policy

Adapters use shared entity/character identity rules and skip ambiguous collisions.
Sources join by normalized ID, not display name alone. Primary supplied fields
win; secondary-only records and absent mechanical fields fill gaps. Explicit
zero, false and empty mechanical values remain distinct from absent values.
Empty description/cost text can be filled from the secondary. Known conflicting
branch or change-revision metadata rejects the join; absent metadata stays
unknown and cannot establish compatibility.

Merging into the installed dataset preserves curated character categories and
nonempty text when a source lacks it. Source provenance dates change with content,
not every check. The full refresh stages all files, requires successful fetches
for cards/relics/potions, applies guarded text corrections, validates the complete
dataset and commits atomically. Historical rarity overrides are an explicit
maintenance operation, not part of the automatic refresh.

Save discovery provides identifiers and observed records, not complete mechanics.
The local game audit provides versioned localization identifiers, not active-pool
or numerical-mechanics certification. Publisher patch notes establish announced
changes; neither a community scrape nor a successful structural validation proves
that every relevant field matches a specified game build.

## Revisit when

- Both web sources break (spec kill switch: hand-curated JSON drops + save
  discovery — re-plan, do not build a third scraper).
- An official Mega Crit data API appears.
