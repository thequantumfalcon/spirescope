# Stabilization and release qualification

This work implements the independent review against release v3.1.2
(`ef038a679aa7c777913a309cfbac369618277384`) and master
`2f39ce07f25325e84df26761a9e69105beacf002`. The four intervening commits
changed documentation, not application behavior. Development is on
`fix/stabilization`; a passing source suite is not a stable-release decision.

## Verified implementation progress

- Restored and hash-checked all five recovered work snapshots before integration.
- Preserved historical upgrade levels, enchantments, every card pick, native acts,
  and observed zero gold. Legacy scalar picks remain readable.
- Retained card copy metadata through the deck editor. Enchantment effects and
  unknown upgrades are disclosed rather than presented as fully modeled.
- Kept canonical English mechanics separate from translated presentation; Block,
  draw and area-damage checks distinguish capabilities from keyword mentions.
- Joined card sources by identity and character; ambiguous identities are skipped.
  Energy/Star X costs, fixed zero and secondary mechanical fields survive refresh.
- Decoded RSC strings before joining the stream and used JSON parsing for nested
  objects and braces in text.
- Staged complete data refreshes, validated before replacement, and retained a
  rollback copy. Attempts and save scans do not advance the installed bundle date.
- Added `validate-data DIRECTORY` for Python and frozen executables, with scratch
  state and no access to personal saves, game files or overlays during validation.
- Reset live log state on rotation/replacement/deletion and buffered complete
  lines. Save/log merging requires a matching seed and rejects known conflicts.
  Native player IDs select telemetry; absent teammate entries are never borrowed.
- Added a live content revision to refresh same-floor lists and retained view
  position/focus across reloads.
- Validated aggregate counter relationships and run representations. Aggregate
  retry deduplication and the merge/write operation share a process-safe lock.
  Hypothesis create/delete report persistence failure.
- Corrected IPv6 Host parsing and made throttling use the effective ASGI bind.
- Packaged Swagger UI 5.33.0 locally with licenses and source digests; an external
  initializer works under the same script policy as the dashboard.
- Bounded graph-analysis concurrency and pending work, coalesced duplicate
  requests, and keyed results by the actual card mechanics used in the graph.

## Validation recorded so far

The isolated public checkout excludes private modules, personal overlays, and
working build files. Windows source checks cover Python 3.11 and the locked
desktop Python 3.14.7 environment (3.13 was also exercised). Lint and type checks cover the public package;
Chromium checks include real Swagger operations with external requests blocked.
The exact `24947e7` candidate passed
[GitHub CI](https://github.com/thequantumfalcon/spirescope/actions/runs/35807577729):
1,757 tests passed on the coverage leg, four skips, and 89.56% branch coverage
against the 88% gate. All 19 browser tests passed on each of Chromium, Firefox and
WebKit. Mypy checked 40 public source files; Ruff and dependency checks passed.

The [artifact rehearsal](https://github.com/thequantumfalcon/spirescope/actions/runs/35807670327)
qualified actual Windows x64 and macOS ARM64 executables after metadata cleanup:
valid installation, invalid checksum/empty-family rejection, interrupted-swap
recovery, state preservation and key pages. Both archives and their SPDX SBOMs
were verified against the source commit and signer workflow. The downloaded
Windows archive passed an additional local qualification. These results identify
that candidate, not a later source revision or a complete real-game audit.

On Windows build 26200 with 32 logical CPUs, 30 measured browse requests had a
3.62 ms p95. Thirty 100-card analyses at two concurrent requests had a 523.69 ms
p95 (previous solver: 2668.65 ms). Concurrent health requests had a 198.55 ms p95.
These are warm local measurements, not independent hardware or a two-hour soak.
The benchmark and binary qualification JSON remain with local review evidence.

## Compatibility contracts

Energy costs remain strings for API compatibility: a nonnegative integer string,
`X`, `Unplayable`, or empty for unknown. Star costs are independent. In source
records, absence means unknown; explicit zero/false/empty mechanical fields must
not disappear through truthiness-based merging. Empty text cannot erase curated
text. Source freshness does not establish game-patch compatibility.

Historical `deck_upgrades` contains nonnegative integer levels aligned with
`deck`; an empty array means unknown. `deck_enchantments` follows the same
alignment rule. `CurrentRun.deck_upgrades` retains its public boolean semantics.
No persistent native card-instance identifier is invented. The editor uses
positional copies and nullable metadata.

`cards_picked` retains every observed choice. The legacy `card_picked` scalar is
the last pick; contradictory representations are rejected. Native act numbers
override floor heuristics. `gold_observed` distinguishes absent observations from
zero. Legacy exported gold scalars are treated as observations because their
original presence cannot be reconstructed. Import format 1 and raw-payload digest
verification remain compatible. Universally impossible elapsed/count fields are
rejected; signed HP/gold values are not universally banned because mods may differ.

Exact aggregate exports are deduplicated after canonical normalization. Distinct
exports may contain overlapping runs; this cannot be inferred from aggregate
counters alone. The digest ledger never silently forgets old accepted imports.

## Outstanding release gates

The engineering gates above passed for `24947e7`; rerun the affected checks
and final artifact qualification after subsequent implementation changes.
The [game coverage plan](GAME_COVERAGE.md) records a separate installed-build
audit and identifies unresolved identity, mechanics and main/beta compatibility.
Independent Windows/macOS game-session coverage must include solo/co-op and all
released characters. A seed match cannot prove that two replays of the same seed
are the same session; richer native timing evidence remains a qualification item.
Manual accessibility, the two-hour replay/memory test and the pilot remain open.

Signing/notarization depends on actual eligible credentials and distribution
policy. No credentials are created or purchases made as part of code repair.
The proposed independent pilot is seven days, ten sessions and thirty runs,
with a tester on each supported desktop platform. These are acceptance targets,
not completed tests. Keep the Beta classifier until these gates have evidence.

The detailed reviewed plan, recovery hashes and per-finding evidence are retained
locally under `build/stability-plan-2026-09-22` and
`build/diagnosis-verification-2026-09-22`. Those directories can contain local
diagnostic paths and are intentionally excluded from distribution.

## Native runtime maintenance

The initial 3.13.15 candidate bundled OpenSSL 3.0.21. Public support for 3.0
ended on 7 September 2026 ([OpenSSL notice](https://openssl-library.org/post/2026-09-16-eol30/)).
Desktop qualification therefore moved to Python 3.14.7; its Windows distribution
reports OpenSSL 3.5.7 on the supported 3.5 LTS line. The runtime inventory is
cross-checked against `runtime-info` from the actual executable, including after
metadata stripping. Existing Python 3.11–3.13 source compatibility is retained.

OpenSSL 3.5.8 contains newer fixes ([25 August advisory](https://openssl-library.org/news/secadv/20260825.txt)).
The advisory covers QUIC, CMS, CMP, raw-public-key configurations, DTLS and direct
EVP cipher operations. The default app uses HTTP locally and Python HTTPS clients;
it does not configure those specialist interfaces. This is a scoped code-review
assessment, not a claim that 3.5.7 has no advisories. Recheck the final native SBOM
and use a refreshed official Python build when available. Custom native bindings
or TLS deployments require their own applicability review.
