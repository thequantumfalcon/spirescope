# 2. Keep the CodeQL threat model on `remote`

Date: 2026-09-14
Status: Accepted

## Context

CodeQL default setup exposes a threat-model setting. Under `remote` the
analysis treats network input as untrusted. Under `remote_and_local` it
additionally treats local file contents, filesystem paths and environment
variables as untrusted sources.

Spirescope reads a great deal off local disk: save directories, the game
install, a mods directory, `godot.log`, and every one of those locations is
configurable by environment variable. Enabling the local model therefore looks
apt on first reading, and it was enabled on 2026-09-14 to find out.

It reported **146 alerts** where `remote` reported 0: 119 `py/path-injection`
(high), 20 `py/log-injection` (medium), 4 `py/polynomial-redos` (high) and 3
SSRF (critical). 134 in `sts2/`, 12 in `tests/`.

Nearly all of them say the same thing: the user configured a path, and the
application then read from it. That is the product. A local-first desktop tool
whose entire job is to read the player's own save files cannot treat the
player's own save files as an attacker.

## Decision

Keep `threat_model: remote`. Keep `query_suite: extended`, which costs one
medium finding and is worth having.

Do not re-enable `remote_and_local` without first deciding what to do with the
119 path alerts, because the alternative to triaging them is a permanently
noisy security tab, which is worse than no signal at all.

## Rationale

The useful question is not "is a path influenced by a value" but "is a path
influenced by something the user does not control". Those inputs were
enumerated and checked individually rather than inferred from the alert count:

| Source the user does not control | Guard |
| --- | --- |
| Downloaded data bundle (tar) | `tarfile.extractall(..., filter="data")` — blocks absolute paths, traversal, symlinks, device files — plus member-count, per-file and total-expanded size caps in `_extract_capped` |
| File access after extraction | iterates the fixed `_REQUIRED_DATA_FILES` constant |
| fsync of the extracted tree | `os.walk` over output the filter already vetted |
| Third-party mod files | `MODS_DIR.glob("*.json")`; mod-supplied `mod_id` is used to namespace entity ids (`mod:<modid>:<entity>`), never to build a path |
| Locale files | the directory is enumerated and the requested code compared against the names found, so the code is never a path component |

Every remote or third-party input that reaches the filesystem is guarded at the
point it arrives. What the local threat model adds on top is a very large
number of reports that the user may configure their own data directory.

The one medium finding the extended suite adds is `py/log-injection` in the
language-change POST handler in `routes.py` (the knowledge-base rebuild failure
path; `routes.py:2140` at the time of writing, though that line moves).
Dismissed as a false positive: the call sits behind `set_language()` returning
true, which requires `is_valid_code` — a `[a-z]{2,8}` full match admitting no
newline or control character — and a matching locale file to exist, so the
logged value is provably a short lowercase locale name.

## Consequences

- The security tab stays meaningful: a non-zero count means something to look
  at.
- Taint reaching the filesystem *from local files specifically* is not analysed
  automatically. The table above is the manual substitute, and it needs
  revisiting whenever a new untrusted-input path is added — a new archive
  format, a new mod loader, a new import.
- If the local model is ever wanted, the honest sequence is to triage the 119
  first and suppress the configured-path class deliberately, not to enable it
  and leave the alerts standing.
