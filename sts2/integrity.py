"""Hash-chain run integrity — Merkle proofs for provable run records."""
import hashlib


def compute_merkle_root(run):
    """Compute a Merkle root hash for a run's decision chain.

    Every decision is chained: hash_n = SHA256(hash_{n-1} + floor_data).
    The final hash proves the entire run is unmodified — change any
    single decision and the root changes completely.
    """
    seed = run.seed or "unknown"
    character = run.character or "unknown"
    ascension = run.ascension

    # Genesis hash
    chain = hashlib.sha256(f"{seed}:{character}:{ascension}".encode()).hexdigest()

    # Chain each floor's decisions
    for floor in run.floors:
        event = (
            f"{floor.floor}:{floor.type}:{floor.card_picked}:"
            f"{floor.damage_taken}:{floor.current_hp}:{floor.gold}"
        )
        chain = hashlib.sha256(f"{chain}:{event}".encode()).hexdigest()

    return chain


def verify_run(run, expected_root):
    """Verify a run's integrity against an expected Merkle root."""
    actual = compute_merkle_root(run)
    return actual == expected_root
