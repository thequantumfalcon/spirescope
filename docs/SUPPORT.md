# Support and release operations

Spirescope is a local companion. Game patches, save formats, source-site changes,
and desktop packaging can each affect compatibility independently. A data
refresh timestamp does not certify support for a game build.

## Supported paths and qualification

Source installs require Python 3.11 or later; CI checks 3.11, 3.12, 3.13 and 3.14.
Desktop candidates target Windows x64 and macOS on the GitHub-hosted build
runner architecture. Record that architecture from the artifact inventory for
each release; do not describe an ARM64 binary as an Intel-native build. Docker
uses the pinned base image and hashed runtime lock in the repository.

The stabilization candidate retains Beta status. Its local evidence and remaining
gates are in [STABILIZATION.md](STABILIZATION.md); build-specific coverage and
the remaining content work are in [GAME_COVERAGE.md](GAME_COVERAGE.md). No game build or OS should be
added to the verified support matrix solely because the program starts there.

## Reporting a problem

Include the app version, candidate commit if applicable, OS/architecture, game
build and branch, solo/co-op, and whether the issue repeats after restart.
Describe the action, expected result, actual result, and the last successful
step. For data problems, include the affected card/relic/enemy ID and displayed
text. Screenshots may help with visual failures.

Do not post authentication tokens, full save directories, Steam IDs, or private
filesystem paths in a public issue. Prefer a small sanitized example that still
reproduces the problem. Full logs and saves should not be collected by default.
Spirescope does not silently upload diagnostics.

## Backup and recovery

Keep separate copies of the configured `STS2_DATA_DIR` and `STS2_STATE_DIR`
before changing installation channels. User settings, hypotheses and imported
statistics live in the state directory. Game saves are read by the companion;
the repair procedure does not require changing them.

Updates stage and validate replacement data before swapping directories. The
previous dataset is retained as the sibling `<data-directory>.backup`.
Startup recovers that backup if an interrupted swap leaves the live directory
missing or unusable. Preserve both directories for diagnosis if recovery fails;
do not repeatedly delete files to force an update.

For a downloaded data bundle and its checksum file, use:

```text
spirescope install-data path/to/data.tar.gz --sha256 path/to/data.sha256
spirescope validate-data path/to/data-directory
```

In a desktop distribution, replace `spirescope` with the actual executable
(`Spirescope.exe` on Windows). The local installer uses the same checksum,
archive bounds, complete-dataset validation and rollback path as network updates.
Validation uses temporary state and does not need access to the player's game.

## Patch-response procedure

1. Reproduce against the precise app/game/source versions and record a minimal
   fixture. Distinguish a parser defect from missing source coverage.
2. Run a staged refresh against a copied dataset. A failed or partial source
   fetch must leave installed files and bundle freshness unchanged.
3. Review identity collisions and changed mechanical fields. Preserve explicit
   zero/false values; do not invent IDs or mechanics to fill unknowns.
4. Run semantic regressions, lint/types, browser checks and the existing coverage
   gate. Qualify the built artifacts with `scripts/qualify_artifact.py`.
5. Build a candidate using `workflow_dispatch`. Record numeric app version,
   commit, archive digests, runtime inventory and qualification results. Candidate
   dispatches do not create a release.
6. Complete the supported-platform/game-session matrix and the pilot. Publish
   only after reviewing that evidence and the actual candidate artifacts.

There is no guaranteed patch-to-catalog turnaround. Report a source outage or
unknown compatibility explicitly, retain the previous usable dataset, and
publish a correction when evidence and validation are ready.

## Signing and provenance

Signing and notarization are separate from checksum and build-provenance checks.
A checksum detects changed bytes; a verified build attestation identifies a
build. Neither substitutes for a platform publisher signature or independent
testing. Windows signing and Apple notarization require eligible maintainer
credentials. Record the actual status of each release rather than promising
that antivirus software will accept every build.
