"""Hash-chain run integrity — Merkle proofs for provable run records."""
import hashlib


def compute_merkle_root(run):
    """Compute a Merkle root hash for a run's decision chain.

    Every decision is chained: hash_n = SHA256(hash_{n-1} + floor_data).
    The final hash proves the entire run is unmodified — change any
    single decision and the root changes completely.

    Genesis binds seed + character + ascension + build_id + total_players.
    Each floor binds the per-floor decisions including encounter, monsters,
    turns, HP delta, gold delta, card offered/picked, and potions used.
    Relic acquisitions across the run are chained at the end.
    """
    seed = run.seed or "unknown"
    character = run.character or "unknown"
    ascension = run.ascension if run.ascension is not None else 0
    build_id = getattr(run, "build_id", "") or ""
    total_players = getattr(run, "total_players", 1) or 1

    # Genesis hash
    genesis = f"{seed}:{character}:{ascension}:{build_id}:{total_players}"
    chain = hashlib.sha256(genesis.encode()).hexdigest()

    # Chain each floor's decisions (extended to cover encounter/monsters/turns
    # /hp_healed/cards_offered/potions_used — prior version only chained the
    # damage_taken/current_hp/gold/card_picked subset, so swap-attacks went
    # undetected).
    for floor in run.floors:
        encounter = floor.encounter or ""
        monsters = ",".join(floor.monsters or [])
        turns = floor.turns or 0
        hp_healed = floor.hp_healed or 0
        max_hp = floor.max_hp or 0
        cards_offered = ",".join(getattr(floor, "cards_offered", None) or [])
        potions_used = ",".join(getattr(floor, "potions_used", None) or [])
        potions_gained = ",".join(getattr(floor, "potions_gained", None) or [])
        event = (
            f"{floor.floor}:{floor.type}:{encounter}:{monsters}:"
            f"{turns}:{floor.damage_taken}:{hp_healed}:"
            f"{floor.current_hp}:{max_hp}:{floor.gold}:"
            f"{cards_offered}:{floor.card_picked}:"
            f"{potions_used}:{potions_gained}"
        )
        chain = hashlib.sha256(f"{chain}:{event}".encode()).hexdigest()

    # Chain final relics + deck so a relic swap or deck edit changes the root.
    final = (
        "FINAL:"
        + ",".join(run.relics or [])
        + "|"
        + ",".join(run.deck or [])
    )
    chain = hashlib.sha256(f"{chain}:{final}".encode()).hexdigest()

    return chain


def verify_run(run, expected_root):
    """Verify a run's integrity against an expected Merkle root."""
    actual = compute_merkle_root(run)
    return actual == expected_root
