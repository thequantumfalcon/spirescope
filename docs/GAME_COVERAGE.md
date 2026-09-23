# Game compatibility and completion plan

Reviewed 2026-09-23. The engineering candidate is substantially repaired, but
complete game coverage and a stable release are not yet demonstrated.

## Verified baseline

The official Steam announcement feed retrieved on 2026-09-22 lists
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
The user subsequently launched this main build. The integration check reads its
save and log without changing either. Steam and its selected branch were not
changed. No separate beta installation is available for native verification.

The reference catalog includes beta mechanics. The candidate now selects a
separate reviewed main mechanics profile when the installed version **and commit**
match v0.107.1 / `59260271`. Expect a Fight uses main's Energy-per-Attack effect;
the reference catalog retains the later Block/Strength effect. Hyperbeam and
the Scare/Sidestep rename likewise use the selected version. An unidentified
installation or historical version does not inherit a claim of verification.

A field-level v0.111.0 check found Guiding Star already had next-turn draw
but still cost 2 Stars. The candidate now corrects its Star cost to 1, matching
the official notes linked above. This is a targeted beta-catalog correction;
the old data-fetch timestamp is retained and no complete-refresh claim is made.
The current candidate adds guarded Star-cost expectations and rejects
unrecognized correction drift. A complete branch/build-specific dataset remains
necessary; those targeted checks do not certify every card.

The public app release remains v3.1.2. The repaired executable candidate was
qualified at `24947e7e58d027617e9e74191b2ab8eb67c46a75` in
[PR #60](https://github.com/thequantumfalcon/spirescope/pull/60), with
[CI](https://github.com/thequantumfalcon/spirescope/actions/runs/35807577729) and
[Windows/macOS artifact rehearsal](https://github.com/thequantumfalcon/spirescope/actions/runs/35807670327).
The content audit, versioned main profile, saved-card properties and live-seed
repair all postdate that executable build. Those archives and earlier remote
CI results do not qualify the current uncommitted candidate.

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

## Reviewed native identity baseline

The initial localization audit was an investigation queue, not an active-content
count. The follow-up inspected the installed assembly's model registry, character
and shared pools, epoch-supplied potions, act/event encounters, static encounter
collections, Fabricator spawn sets and badge registry. It did not execute the
game. The reviewed identifiers and definition hashes are preserved in
[the v0.107.1 baseline](game-baselines/v0.107.1.json); native source and descriptions
remain private. Regression checks compare this independent baseline with the
bundled catalog and verify runtime enemy lookups.

| Reviewed main-build scope | Expected native IDs | Catalog matches |
| --- | ---: | ---: |
| Non-deprecated cards in registered pools/starting decks | 577 | 577 |
| Non-deprecated relics in registered pools/starting relics | 296 | 296 |
| Non-deprecated potions in registered pools, excluding mocks | 63 | 63 |
| Act-pool and event-referenced encounters | 85 | 85 |
| Monsters in those encounters and reviewed spawn collections | 107 | 107 |
| Ordinary events and Ancients in act/shared pools | 65 | 65 |
| Badges registered by BadgePool, using literal save IDs | 23 | 23 |

These are identity checks, **not complete mechanics or runtime availability
certification**. Unlock state, reward eligibility, pets, special ending content,
all game modes and beta still require separate review. Five playable character
registrations are present. The four act models are Overgrowth and Underdocks
(alternative Act 1s), Hive (Act 2), and Glory (Act 3).

The current uncommitted candidate includes these repairs:

- Twenty-four explicit legacy-to-native mappings, verified against native model
  identities. Old links and overlays still resolve. Analytics and aggregate
  statistics join the spellings on copies without rewriting raw run exports.
  A spot check of fourteen formerly unresolved native IDs from historical saves
  now resolves all fourteen.
- Sixteen additional monster/encounter entries, including the event dummies,
  Mysterious Knight, Fake Merchant, Aeonglass's encounter, illusions and Fabricator
  bots. Battle Friend V2's incorrect three-enemy-fight description is replaced:
  the event offers one of three dummies. Reviewed mechanics are labeled main
  v0.107.1; their presence does not verify beta mechanics.
- All twenty-three registered badge requirements, including win/co-op conditions
  and applicable tiers. The Records page uses their catalog names and shows
  requirements and recorded badges even without run-history files. Helper model
  class names and the unregistered Favorite Card/Whomper localization entries
  are not invented as earned-badge identities.
- Wiki presentation variants marked `NoList` no longer suppress the canonical
  Mad Science/Wither records. Mad Science is displayed as customizable, with a
  variable type; the previous catalog incorrectly promised one specific Power
  effect for every copy. The main profile now reads the saved type and rider
  effect for all nine Tinker Time choices. Missing, malformed or unsupported
  properties remain explicit and are excluded from effect-based advice.
- Localization overlay metadata reads the selected installation's release
  identity. Missing metadata stays unknown instead of claiming v0.107.1.
- Cross-source filling of mechanical fields is rejected when the sources also
  disagree on supplied mechanics. Guarded Alignment/Guiding Star cost corrections
  accompany the existing beta text corrections; unrecognized correction drift
  rejects the whole refresh before installing any data.

The source mismatch is reproducible: wiki.gg Regent module revision `46536`,
timestamp `2026-08-14T03:28:15Z`, still describes Guiding Star's main-branch
immediate draw and 2-Star cost. Its revision timestamp cannot establish beta
compatibility. The new guard prevents a demonstrated partial join; it does not
prove compatibility when sources omit the conflicting evidence.

## Reviewed main card rules and saved copies

The versioned profile in `sts2/data/mechanics.json` now covers printed traits and
base/first-upgrade rules for all **577** cards in the independent main pool.
[The card review record](game-baselines/v0.107.1-card-mechanics.json) preserves
the reviewed IDs, definition/helper hashes, method and limitations. Most rules
were checked by strict full-template alignment and native values; reworks,
missing upgrade text, conditional descriptions and saved-instance rules received
separate review. Native text/source stays private. The four Knowledge Demon
choices are identified as choices, not ordinary Energy-cost cards.

The selected profile reaches card pages, deck analysis and historical deck/card
links. Historical versions remain explicit; browser-saved decks retain the
version and each copy's properties. Older deck formats remain version-unknown.
Genetic Algorithm and The Scythe use each copy's consistent saved permanent value.
Mad Science uses its saved Attack/Skill/Power type and event effect. Upgraded
copies use their own keyword mentions, including added Innate and removed
Exhaust/Ethereal. Malformed, missing or foreign-build properties are not guessed.

Derived localization descriptions require both matching version metadata and a
fingerprint of the exact English mechanics. Full template matching rejects
translations that would omit timing, targeting, extra effects or upgrade-only
keywords. Legacy overlays may supply display names; a known version-specific
rename cannot be overwritten by a foreign-version name. This can leave English
fallback text until a compatible translation is available.

The running game exposed a native save integration defect: its seed is stored
at `rng.seed`, while the reader used only a legacy top-level field. The corrected
reader accepts native/legacy agreement and rejects conflicts and malformed values.
A read-only live check then matched the save to the log and read seven card plays
without replacing saved HP, gold, deck or floor. This is evidence for that repair,
not a complete gameplay or same-seed replay qualification.

**Scope remains bounded.** Printed rules and the supported saved properties are
not a combat simulator. Temporary combat changes, enchantment effects, repeated
upgrades beyond the reviewed first upgrade and all possible card interactions
are not certified. This card review does not certify other entity families or beta;
separate reviewed family scopes are described below. The overall profile and game-coverage reports retain `complete: false`.

## Reviewed main relics, potions, monsters, encounters and epochs

The same exact-version profile now includes general rules and rarity for all
**296 relics**, and printed rules, rarity, targeting, usage timing and combat
generation flags for all **63 potions**. The review records are
[relic mechanics](game-baselines/v0.107.1-relic-mechanics.json) and
[potion mechanics](game-baselines/v0.107.1-potion-mechanics.json). Reworks and
conditional text received separate native definition review. Historical relic
links preserve the run's version. Current relic counters, stored selections and
all cross-item interactions are not simulated. Jeweled Mask explicitly records
the observed discrepancy between its printed combat-long free effect and the
installed implementation's opening-turn duration.

The profile also records titles, printed rules, extra card text and eligibility
for all **22 enchantments** registered in the main build, with the review in
[enchantment mechanics](game-baselines/v0.107.1-enchantment-mechanics.json).
Strings come from the installed game's English localization table; fixed
values come from each native model's canonical variables, and `{Amount}` stays
a placeholder because it is saved per card copy and Spirescope records only
the enchantment id. Run detail shows the rules for the run's own recorded
version and falls back to the bare title otherwise. Status reset timing,
per-copy amounts and interactions with relics, powers and other cards are not
simulated, and deck analysis still counts enchanted copies as unmodeled.

Move sets and turn patterns are reviewed for all **107 monsters** with
reviewed HP: the two Act 1 pools (the Overgrowth and Underdocks act models,
42 encounters), the Act 2 pool (the Hive act model, 20 encounters), the Act 3
pool (the Glory act model, 18 encounters) and the five event and
encounter-specific monsters outside those pools, with the review in
[monster moves](game-baselines/v0.107.1-monster-moves.json): each move's
intent, damage, hits, Block and applied powers with their Ascension 8+ and
9+ variants, the turn order including random-branch weights, repeat rules and
cooldowns, and effects applied on entering combat. Titles come from the game's
localization table. Enemy pages show these in place of reference patterns for
that version, and counter-card suggestions read the reviewed text. Named
powers are identifiers whose effects are not reviewed; summon slot
availability, encounter-specific starting moves and forced-state triggers are
not simulated. Monsters without reviewed HP (companions, the ending creature,
mocks and deprecated models) are outside this review.

Initial HP is reviewed for all **107 monsters**, including the Ascension 8
threshold. These are base ranges before multiplayer scaling, encounter effects,
powers or modifiers. [The HP review](game-baselines/v0.107.1-monster-stats.json)
keeps this verification separate from attack patterns. Unverified enemy patterns
cannot drive card suggestions for a known game version; suggested cards must
also have compatible mechanics. Cards requiring saved per-copy properties are
excluded from catalog-only counter suggestions.

Declared possible-monster sets and room types are reviewed for all **85
encounters**. [The roster review](game-baselines/v0.107.1-encounter-rosters.json)
covers literal declarations, static collections and Fabricator's spawn sets.
Encounter pages link to versioned monster health. Possible participants are not
simultaneous counts or a guaranteed starting lineup; generation probabilities,
all summons and encounter-specific adjustments remain outside this review.

Requirements and reward lists are reviewed for all **57 registered epochs**.
[The timeline review](game-baselines/v0.107.1-epoch-mechanics.json) includes the
18-step score-bar sequence, per-step thresholds, one-unlock-per-run limit and
overflow cap. Daily mode requires playing all five characters and then winning
a Standard run, not a victory with each character. Character epoch 7 is checked
at exactly Ascension 1. Main's alternate Act 2 and Act 3 timeline entries are
obtainable placeholders, not playable acts. All eight previously blank epoch
entries have reviewed main information. The Epochs catalog now renders without
a save; completion percentages still require observed progress. Slot reachability
and multiplayer progression persistence are not simulated or qualified.

## Reviewed main events and Ancient offers

All **65 registered main events/Ancients** have reviewed option summaries,
base costs/rewards, local entry conditions and normal act-pool placement.
[The event review](game-baselines/v0.107.1-event-mechanics.json) records the
definition/helper hashes and exact scope. This includes all **8 Ancients**,
their separate offer groups, selection weights, deck/relic requirements and
Neow's modifier-run opening actions. Ancient healing uses the actual Ascension
2 threshold. The main profile corrects **36** missing or different act labels;
Act 1 locations distinguish Overgrowth from Underdocks. Ancient entries are
labeled separately from ordinary events.

The review corrects material reference errors: Dense Vegetation costs HP for
Gold rather than removing a card; Drowning Beacon loses Max HP; Crystal Sphere
reveals a reward board rather than future map encounters. Repeatable choices
retain escalating costs, and rewards distinguish direct grants from selectable
offers. Leaving Wongo's can downgrade a card. Its points and badge relic are
separate from score-bar progression. Fake Merchant is solo only; the native
shared-event flag does not imply multiplayer eligibility. Its displayed prices
include shop variation, and fighting awards the remaining stock rather than
re-awarding purchased items.

Act filters use reviewed main pool membership and explicit act restrictions.
Timeline-gated events and Lantern Key's forced Act 3 event are distinguished.
This is a catalog of rules, not a prediction of current random offers. The full
Crystal Sphere reward board, every cross-entity hook, custom act ordering,
runtime offer state and special ending sequence are not certified by this
review. Foreign builds and extra reference records remain visibly unverified.

## Native registry inventory and advice limits

[The complete native model registry inventory](game-baselines/v0.107.1-model-registry.json)
resolves all **1,624 registered model types** to unique definition hashes. Of
these, **1,215** match the bounded card/relic/potion/enchantment/monster/
encounter/event reviews above. This is an inventory, not a completion percentage: it includes
mock models, deprecated placeholders and infrastructure. Three companion models
and the Architect event, encounter and visual creature are identified separately.
The application applies that classification: Osty, Byrdpip and Pael's Legion
and the Architect ending (event, encounter and creature) are never added to the
enemy catalog by save discovery, the ending is not counted as a combat in run
analysis, and a companion recorded among a floor's monsters is labelled as one
in run detail. The game appends every creature that joins a combat to the
room's monster list whichever side it is on, so companion ids do occur in
saved history. Companion and Architect HP values are placeholders and are not
catalogued.
The remaining model families are explicit review queues. Epochs, intents,
keywords, modes and other systems outside this registry still need separate
accounting; registry membership does not establish playable availability.

A further live review exposed unsupported advice based only on deck size,
card-type ratios, repeated cards, zero-cost counts and fixed boss-floor numbers.
Those automatic claims are removed. Deck/live analysis now labels its effect
observations and gaps as card-text checks, with the omitted sources of effects
stated. Cost summaries show the known numeric Energy-cost sample and a
five-card estimate calculated before rounding. Unknown IDs remain in the
cost curve; all-variable samples display Unknown. There is no invented
15-Energy hand budget or promise about how many cards can be played. Keyword
connectivity keeps its mathematical score but is labeled as connections;
reference archetype matches are explicitly based on names and may describe
another patch. These repairs do not introduce a combat simulator.

Run-history analysis had the same problem. Post-mortem insights graded deck
size, relic count, card-type ratios and repeated copies, called skipped
rewards a weakness, treated an unrecorded run time as a speed run, folded
event damage into a combat total, used the number of recorded floors as the
death floor and estimated death acts from floor numbers. They now report the
recorded counts, combat and non-combat damage separately, the floor number
the save stored, and only the acts the save recorded; losses without a
recorded act are reported as uncounted. Card-text checks on a finished run
use that run's own recorded game version and say so when the version is
unrecorded or unreviewed instead of borrowing the installed game's card text.

## Remaining content findings

The current catalog has 639 cards, 312 relics, 65 potions, 200 mixed monster/
encounter records, 67 event/Ancient records, 57 epochs and 23 badges. Extra rows
may represent beta, historical content, curated variants or discovery entries.
Do not delete them merely because they are outside a reviewed main pool.

The localization audit now separates dotted Sea Glass character titles from
serialized model IDs. Those are variants of one native relic, although the
catalog retains its existing curated variants for compatibility. Localization
also contains unused names, pets, transformations and helpers. For example,
Hatchling is a display-name change of Tough Egg, not another monster ModelId.

The reference catalog still has sixteen blank base descriptions and 51 blank
upgraded descriptions; these counts describe the unversioned reference rows.
All sixteen base blanks are outside the reviewed main pools. The main profile
now supplies reviewed rules for every main card, with no upgrade text required
for cards that cannot upgrade. The unversioned reference still has five blank
relic descriptions, 139 mixed monster/encounter rows without HP and 136 without
patterns. The selected main profile supplies all reviewed relic rules and
monster HP, and treats encounter rosters separately. Six reference events lack
choices; the main profile supplies reviewed summaries for all 65 registered main events/Ancients. Eight reference epoch entries remain blank, while the main profile
supplies reviewed information for all 57. These reference-file counts are
investigation queues, not counts of missing selected-main behavior. The 23
registered badges have requirements; beta changes and gameplay persistence
still require verification.

Branch metadata remains absent on 636/639 cards, 310/312 relics and 64/65 potions.
The catalog still mixes information collected at different revisions. Versioned
mechanics now cover the bounded main scopes above. Enemy move/state-machine
behavior beyond the paraphrased move machines (power effects, summons, forced
states), full event simulations, other systems and beta remain review work. These
profiles and refresh guards do not establish unreviewed families' or beta's
compatibility.

Characters, acts, powers, afflictions, orbs, keywords, intents, ascension,
modes, modifiers and achievements need a feature-by-feature audit.
Some already participate in live records or analysis. A model definition alone
does not prove a shipped feature; neither does absence of a dedicated JSON file
prove that the app has no support for it.

## Ordered execution and acceptance

1. **Establish branch-specific truth.** Preserve this main-build inventory;
   obtain an independently identified beta build without replacing a player's
   main installation. Record release metadata, relevant table hashes, source
   revisions and actual pool membership for both. Build a patch-impact ledger
   for every changed entity, field and integration since v0.107.1. Completion:
   every item has evidence or an explicit unresolved status.
2. **Repair identity and availability.** The 24 reviewed compatibility
   mappings and the main pool identity baseline are implemented. Continue with
   beta, special ending content, pets, availability and collision checks. Separate monsters from encounters and Ancients from ordinary events.
   Classify active, generated, co-op, removed, deprecated, placeholder and modded
   records. Preserve old identifiers for history. Completion: every expected
   native ID resolves appropriately; no speculative alias or missing-name fallback
   is counted as complete support.
3. **Make data compatible with the selected build.** Maintain explicit main/beta
   datasets or versioned mechanics with provenance. The main card, relic, potion, monster HP, encounter roster, epoch and event
   profiles, plus saved-card-copy support, are implemented within the scopes above. Extend the same evidence boundaries to
   other families and beta; expose unknown/mismatched versions and prevent mixing mechanics in
   updates, overlays, deck analysis and patch statistics. Overlay generation now records actual installed release metadata;
   use that evidence when selecting and validating compatible mechanics. Prioritize
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
