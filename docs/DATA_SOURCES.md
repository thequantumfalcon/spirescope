# Data source decision record (P1 / V5)

**Date:** 2026-07-22 · **Status:** decided

## Decision

| Priority | Source | Method | Role |
|---|---|---|---|
| Primary | slaythespire2.gg | Next.js RSC payload extraction (`/cards`, `/relics`, `/potions`) | Full structured catalog; wins per-entity |
| Secondary | slaythespire.wiki.gg | MediaWiki API, `Module:*/StS2 data` Lua modules | Fills gaps; full fallback when primary is down |
| Tertiary | save files | `--save-only` discovery (existing) | Names/ids only, offline |

## Why

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

**Merge policy:** primary wins per entity; secondary contributes entities the
primary lacks (matched by name); `--save-only` discovery continues to add
enemies/events from local saves. Every new or changed record is stamped with
`fetched_from` + `fetched_at` (date); unchanged records keep their stamps so
data diffs stay reviewable.

## Revisit when

- Both web sources break (spec kill switch: hand-curated JSON drops + save
  discovery — re-plan, do not build a third scraper).
- An official Mega Crit data API appears.
