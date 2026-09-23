# Game compatibility and completion plan

Reviewed 2026-09-22. The engineering candidate is substantially repaired, but
complete game coverage and a stable release are not yet demonstrated.

## Verified baseline

The official Steam announcement feed retrieved on the review date lists
[main v0.107.1](https://store.steampowered.com/news/app/2868840/view/710026912607505280)
(19 June) and
[beta v0.111.0](https://store.steampowered.com/news/app/2868840/view/671751488532383386)
(14 August) as the latest announced patches for their branches. No subsequent
patch announcement appeared in that response. This is an announcement check,
not proof that an unannounced depot build cannot exist.

A local Windows installation independently reports v0.107.1, game commit
`59260271`, in `release_info.json`; its Steam manifest records build `23811903`.
Steam build numbers, game commits, patch names, and save-file build identifiers
are different identifiers. Only map them when the relationship is observed.
The audit did not update Steam, switch branches, execute the game, or alter saves.

The bundled catalog includes beta mechanics. Expect a Fight has the v0.111.0
Block/Strength effect, while the installed main build's template still grants
Energy per Attack. Hyperbeam has temporary Focus loss in the catalog and
unqualified Focus loss in that main build. This confirms the disclosed branch
difference; it does not establish either branch's complete correctness.

The public app release remains v3.1.2. The repaired executable candidate was
qualified at `24947e7e58d027617e9e74191b2ab8eb67c46a75` in
[PR #60](https://github.com/thequantumfalcon/spirescope/pull/60), with
[CI](https://github.com/thequantumfalcon/spirescope/actions/runs/35807577729) and
[Windows/macOS artifact rehearsal](https://github.com/thequantumfalcon/spirescope/actions/runs/35807670327).
The content-audit tool and this document were added after that executable build.

## What changed after the installed main release

- [v0.108.0](https://store.steampowered.com/news/app/2868840/view/688635449342693610):
  a batch of multiplayer cards, balance changes, modding changes, and UX/art work.
  Audit teammate targeting, generated cards, and modded/unmodded save handling.
- [v0.109.0](https://store.steampowered.com/news/app/2868840/view/711155348639056490):
  new Neow relics, an associated potion and quest card, rebalances, and initial
  Traditional Chinese translation. The v0.109.1 hotfix corrects that translation.
- v0.110.0 (31 July, official feed): more reworks, including Scare renamed
  Sidestep, and keyboard-only controls. Verify identity separately from display
  name; check new mechanics and all subsequent reversions in chronological order.
- v0.111.0: further card/relic/enemy changes and Indonesian localization.
  Verify base/upgraded values, Star costs, Exhaust changes, enemy ascension
  values, badge persistence, and multiplayer card fixes. Spirescope's current
  language map does not offer Indonesian.

The [official August newsletter](https://store.steampowered.com/news/app/2868840)
describes experimental modes, an alternate Act 2, and a new character as work
in progress. Their announcement is not evidence that they have shipped. The
installed archive also contains helper/test/unused entries; a name in an archive
is not sufficient evidence of a released character, achievement, or encounter.

## Installed-build inventory findings

`scripts/audit_game_content.py` reads English localization tables directly from
the installed Godot pack. It excludes explicitly marked mock/deprecated entries,
TODO titles and specified interface helpers, then compares identifiers. Other
unused entries may remain. These are named candidates, **not active pool totals**.

| Family | Native candidates | Exact catalog ID matches | Follow-up |
| --- | ---: | ---: | --- |
| Cards | 599 | 588 | 11 potential Event aliases; mechanics/availability unverified |
| Relics | 308 | 297 | 11 potential fake/name aliases; preserve dotted Sea Glass variants |
| Potions | 63 | 62 | Clarity / Clarity Extract identity requires verification |
| Monsters | 122 | 90 | 32 candidates to classify: includes summons, helpers, parts and possible omissions |
| Encounters | 89 | 84 | 5 encounter IDs unresolved; do not substitute monster records silently |
| Events | 57 | 57 | Identity coverage only; option outcomes and conditions need review |
| Ancients | 9 | 8 | The Architect requires explicit classification/coverage |
| Epochs | 57 | 57 | 11 additional native TODO entries excluded; unlock logic unverified |
| Badges | 25 | 11 | 14 identifiers absent; all 11 shipped requirements are blank |

The catalog has 639 cards, 312 relics, 65 potions, 184 combined enemy/encounter
records, 67 combined event/Ancient records, 57 epochs and 11 badges. These totals
are not comparable to a single active-content count. Extra records can be beta,
historical, curated aliases or unused content; retain them until classified.

Sixteen card records lack base descriptions; 51 lack upgraded descriptions.
Some may be unavailable or non-upgradable, so classify before adding text.
Of 184 mixed monster/encounter records, 138 lack HP and 139 lack patterns. An
encounter need not have one HP value, so split the schemas before measuring
tactical completeness. Six events lack choices, including records needing
special handling. Eight epoch records lack requirements and unlock details; these are discovery
placeholders in the shipped catalog. Verify availability and requirements rather
than treating their presence as complete unlock support.

Branch metadata is absent on 636/639 cards, 310/312 relics and 64/65 potions.
The source merger rejects *known* incompatible branches but cannot identify a
conflict when metadata is missing. Refresh success is not a compatibility gate.

Additional native tables cover characters, acts, powers, enchantments,
afflictions, orbs, keywords, intents, ascension, modes, modifiers and achievements.
These do not have dedicated structured catalogs in Spirescope. Some mechanics
already participate in text, live records or analysis; audit each feature before
calling an entire system unsupported. Achievements and unused character entries
especially require active-pool confirmation.

## Ordered execution and acceptance

1. **Establish branch-specific truth.** Preserve this main-build inventory;
   obtain an independently identified beta build without replacing a player's
   main installation. Record release metadata, relevant table hashes, source
   revisions and actual pool membership for both. Build a patch-impact ledger
   for every changed entity, field and integration since v0.107.1. Completion:
   every item has evidence or an explicit unresolved status.
2. **Repair identity and availability.** Verify the 23 candidate aliases using
   native model/save IDs and runtime lookup; use explicit mappings with collision
   tests. Separate monsters from encounters and Ancients from ordinary events.
   Classify active, generated, co-op, removed, deprecated, placeholder and modded
   records. Preserve old identifiers for history. Completion: every expected
   native ID resolves appropriately; no speculative alias or missing-name fallback
   is counted as complete support.
3. **Make data compatible with the selected build.** Maintain explicit main/beta
   datasets or versioned mechanics with provenance. Select from installed/run
   evidence, expose unknown/mismatched versions, and prevent mixing mechanics in
   updates, overlays, deck analysis and patch statistics. Remove the hardcoded
   v0.107.1 overlay metadata and verify installed release information. Prioritize
   main because it is the installed build, while retaining beta as a separately
   qualified target. Completion: known divergent cards render and analyze using
   the correct branch; unknown versions cannot silently pass as verified.
4. **Complete content fields and supported mechanics.** Verify card pools, costs
   (Energy/Stars/X), upgrades, generated cards, tags, enchantments and afflictions;
   relic/potion restrictions; monster parts, moves, intents and ascension changes;
   event options, conditions and outcomes; Ancients, epochs, badge tiers/scoring;
   characters, acts, orbs, powers, modes and modifiers. Add Indonesian only after
   translating the UI and checking content fallbacks. Completion: every relevant
   entity and mechanic has a supported behavior, a reviewed exclusion, or a clear
   user-visible limitation. A companion need not simulate every combat to leave
   beta, but its claimed advice must not depend on unimplemented mechanics.
5. **Verify with real gameplay.** Capture sanitized fixtures from every released
   character, solo and co-op, main and beta, normal/daily/custom modes and supported
   mod configurations. Check IDs, upgrades, enchantments, rewards, rest/shop/event
   actions, restart/resume, simultaneous players, same-seed replay and patch-era
   mapping. Completion: exact observed inputs match displayed records and there
   is no silent loss or foreign-session merge. Synthetic tests supplement this.
6. **Finish operational qualification.** Run the two-hour replay/memory test,
   independent Windows/macOS game sessions, keyboard/screen-reader/reflow checks,
   and installation/update/recovery on the final candidate. Recheck native runtime
   advisories and signing/notarization options. Completion: recorded results,
   corrected defects, explicit platform limits and a support/recovery procedure.
7. **Pilot, then decide the release.** Proposed pilot: seven days, ten sessions,
   thirty runs, with both supported desktop platforms represented. Track incidents
   and rerun affected tests after fixes. Completion: no unresolved critical data
   loss, compatibility, security or core usability defect; the final exact commit
   passes source/browser/package/artifact gates. Review the version and release
   notes, merge and publish deliberately; retain Beta until evidence supports the
   narrower, explicit stable support matrix.

The pilot numbers are project acceptance targets, not an industry rule. Each
step can be implemented in small reviewable changes; data releases remain
separate from app releases. No automatic refresh may publish unreviewed content.

## Repeating the inventory

From the repository checkout:

```powershell
python scripts/audit_game_content.py --game-dir 'PATH TO GAME' --data-dir sts2/data --output build/game-audit/content-audit.json
```

Output must be outside the game and catalog directories. The command uses only
the standard library, does not import/initialize Spirescope, and does not read
saves or contact the network. Its JSON contains release identity, table/catalog
hashes, exclusions, unresolved identifiers and empty-field counts, without game
descriptions or personal account identifiers. Exit zero means the audit ran;
the report intentionally says `complete: false`. Missing tables, alias candidates
and unused content require a reviewer, not a misleading percentage.

The local 2026-09-22 evidence is in `build/game-audit-2026-09-22/`: the official
news response, private native-table inspection, and generated audit report.
Private game text stays outside version control and distribution.
