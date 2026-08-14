"""Run integrity digest — tamper evidence over the complete run record.

This is a single SHA-256 over a versioned canonical serialization of the
whole exported run, not a Merkle tree and not a signature. It detects
accidental or casual edits to a shared run file; it does NOT prove
authorship, because anyone can recompute the digest for a run they altered.
Treat it as a checksum with a version tag, not as authenticity.

The earlier implementation was a linear hash chain that bound only a subset
of per-floor fields and omitted whole run-level fields — id, win, acts,
killed_by, run_time, timestamp, origin, enchantments — so two runs that
differed only in whether they were won, who killed the player, and how long
they took produced the same digest. It also joined fields with ':' and ','
without escaping, so ['Louse,Louse'] and ['Louse','Louse'] collided. Hashing
a canonical JSON serialization of the full model_dump() closes both holes:
every field is bound, and JSON quoting removes the separator ambiguity.
"""
import hashlib
import json

# Bump when the canonicalization changes so old and new digests never claim to
# describe each other. Carried in the export envelope and checked on import.
DIGEST_VERSION = 2

_PREFIX = f"spirescope-run-v{DIGEST_VERSION}\n"


def _canonical(run) -> str:
    """Deterministic JSON for the complete run DTO.

    sort_keys makes key order irrelevant; separators drop insignificant
    whitespace; ensure_ascii=False keeps non-ASCII names as themselves so an
    editor's re-encoding does not change the digest; allow_nan=False refuses
    non-finite numbers rather than emit nonstandard JSON.
    """
    return json.dumps(run.model_dump(), sort_keys=True, ensure_ascii=False,
                      separators=(",", ":"), allow_nan=False)


def _digest_text(canonical: str) -> str:
    try:
        return hashlib.sha256((_PREFIX + canonical).encode("utf-8")).hexdigest()
    except UnicodeEncodeError as exc:
        # Unpaired surrogates cannot be encoded. That is malformed text, not
        # a server fault, so callers turn this into a rejection.
        raise ValueError("run contains text that cannot be encoded") from exc


def compute_run_digest(run) -> str:
    """Version-prefixed SHA-256 over the canonical serialization of `run`."""
    return _digest_text(_canonical(run))


def compute_payload_digest(run_mapping) -> str:
    """Digest a raw exported run mapping exactly as it appears in the file.

    Verifying a parsed model instead of the file is not verifying the file:
    the model drops fields it does not declare, so anything added to an
    exported run vanished during validation and the original digest still
    matched. Hashing the mapping straight from the file closes that, and an
    untampered export canonicalizes identically to its own model dump.
    """
    if not isinstance(run_mapping, dict):
        raise ValueError("run payload is not an object")
    return _digest_text(json.dumps(run_mapping, sort_keys=True, ensure_ascii=False,
                                   separators=(",", ":"), allow_nan=False))


def verify_payload(run_mapping, expected_digest: str) -> bool:
    """True if the raw run mapping from a file reproduces `expected_digest`."""
    if not expected_digest:
        return False
    try:
        return compute_payload_digest(run_mapping) == expected_digest
    except ValueError:
        return False


def verify_run(run, expected_digest: str) -> bool:
    """True if `run` reproduces `expected_digest` under the current version."""
    if not expected_digest:
        return False
    return compute_run_digest(run) == expected_digest


# Backwards-compatible name for the one call site and older callers. The digest
# is not a Merkle root; new code should call compute_run_digest.
def compute_merkle_root(run) -> str:
    return compute_run_digest(run)
