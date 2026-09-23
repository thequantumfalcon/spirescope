# Data maintenance loop

Aim to review each game patch promptly; no fixed turnaround is guaranteed.
Publish compatibility only after source review and validation (see [SUPPORT.md](SUPPORT.md)).
App releases and data releases are decoupled — packaged-app users receive
data through in-app data bundles, not new executables.

## On each STS2 patch

1. `python -m sts2 update` — fetches from the sources in
   [DATA_SOURCES.md](DATA_SOURCES.md) (primary wins per entity, secondary
   fills compatible gaps), stages the complete refresh and applies guarded
   text corrections. Adapter rarity normalization runs during extraction.
2. **If the patch changed card/relic rarities:** verify the new values against
   that patch. The historical map in `sts2/corrections/rarity.py` is an explicit
   maintenance tool, not an automatic override of future source data. Its
   `scripts/fix_card_rarity.py` wrapper accepts `--dry-run`; review its proposed
   changes before applying it to the selected data directory.
3. Eyeball the diff: `git diff --stat sts2/data/` and spot-check a few
   reworked entities against the patch notes
   (https://slaythespire.wiki.gg/wiki/Slay_the_Spire_2:Patch_Notes).
4. Append the patch to `sts2/data/patches.json`: new entry with `patch`,
   `date`, `branch`, `build_ids` (usually the patch version string), and
   `changed` entity-id lists. Stamp `introduced` / `last_changed` on affected
   entities.
5. `pytest -q` — the manifest schema test and data-integrity tests must pass.
6. Commit, push, then cut a data release:

   ```sh
   git tag data-v$(date +%Y.%m.%d) && git push origin data-v$(date +%Y.%m.%d)
   ```

   The `Data Release` workflow packages `sts2/data/` into
   `spirescope-data-vYYYY.MM.DD.tar.gz` + `.sha256` and publishes a GitHub release.

## How users receive it

On `serve` startup spirescope checks the newest `data-v*` release (same
opt-out as app-update checks: `SPIRESCOPE_CHECK_UPDATES`). If its date is
newer than local `last_updated.txt`, the home page shows an **Update game
data** banner; one click downloads, sha256-verifies, atomically swaps the
data dir, and hot-reloads the knowledge base. Failures leave existing data
untouched.

## Known sharp edges

- `python -m sts2 update` runs `scripts/fix_card_rarity.py` AFTER fetching;
  its hardcoded map wins over scraped rarities. Forgetting step 2 silently
  reverts rarity changes (this is how v2.9.7 served stale rarities).
- The primary source's RSC markup drifts without warning; when extraction
  degrades the pipeline logs which source produced each count — read the
  update output, don't assume.
- Data descriptions must never contain newlines, double spaces, or unresolved
  `{...}` template tokens (tests enforce this).
