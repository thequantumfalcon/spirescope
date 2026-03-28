"""Deck health analysis — synergy graph connectivity scoring."""


def deck_spectral_health(card_ids, kb):
    """Compute health of a deck by analyzing its synergy graph.

    Builds a graph where cards are nodes and shared keywords are edges.
    The connectivity score measures how well-connected the deck is internally.

    Returns:
        health_score: 0-100 (higher = more coherent)
        connectivity: raw algebraic connectivity of the synergy graph
        orphans: list of card names with zero connections
        total_edges: number of synergy connections
        avg_degree: average connections per card
    """
    cards = []
    for cid in card_ids:
        card = kb.get_card_by_id(cid) if kb else None
        if card:
            cards.append(card)

    n = len(cards)
    if n < 3:
        return {"health_score": 50, "connectivity": 0, "orphans": [], "total_edges": 0, "avg_degree": 0}

    # Build adjacency matrix: shared keywords = edges
    adj = [[0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            weight = _connection_weight(cards[i], cards[j])
            if weight > 0:
                adj[i][j] = weight
                adj[j][i] = weight

    # Synergy difference matrix: D - A
    degree = [sum(row) for row in adj]
    diff_matrix = [[0.0] * n for _ in range(n)]
    for i in range(n):
        diff_matrix[i][i] = float(degree[i])
        for j in range(n):
            if i != j:
                diff_matrix[i][j] = -float(adj[i][j])

    # Compute connectivity (second-smallest component)
    components = _compute_components(diff_matrix)
    components.sort()
    connectivity = components[1] if len(components) > 1 else 0

    # Orphans: cards with zero connections
    orphans = [cards[i].name for i in range(n) if degree[i] == 0]

    total_edges = sum(sum(row) for row in adj) // 2

    # Health score: blend of connectivity metrics
    # 1. Fraction of non-orphan cards (0-50 points)
    non_orphan_ratio = (n - len(orphans)) / n if n else 0
    orphan_score = int(non_orphan_ratio * 50)

    # 2. Edge density relative to possible edges (0-30 points)
    max_edges = n * (n - 1) // 2
    density = total_edges / max_edges if max_edges else 0
    density_score = int(min(density * 10, 1) * 30)  # Cap at density=0.1

    # 3. Connectivity bonus if graph is connected (0-20 points)
    connectivity_score = min(20, int(connectivity * 10)) if connectivity > 0.01 else 0

    health = orphan_score + density_score + connectivity_score // 2

    return {
        "health_score": max(0, min(100, health)),
        "connectivity": round(connectivity, 3),
        "orphans": orphans,
        "total_edges": total_edges,
        "avg_degree": round(sum(degree) / n, 1) if n else 0,
    }


def _connection_weight(card_a, card_b):
    """Compute connection weight between two cards.

    Primary: shared keywords (strongest signal).
    Fallback: same type + similar cost (weaker signal for keywordless cards).
    """
    kw_a = set(card_a.keywords) if card_a.keywords else set()
    kw_b = set(card_b.keywords) if card_b.keywords else set()

    # Keyword overlap (strong signal)
    shared = len(kw_a & kw_b)
    if shared > 0:
        return shared

    # Fallback: same type + similar cost (weak signal for keywordless cards)
    if not kw_a and not kw_b:
        if card_a.type == card_b.type and card_a.type in ("Attack", "Skill", "Power"):
            cost_a = int(card_a.cost) if card_a.cost.isdigit() else -1
            cost_b = int(card_b.cost) if card_b.cost.isdigit() else -1
            if cost_a >= 0 and cost_b >= 0 and abs(cost_a - cost_b) <= 1:
                return 0.5  # Weak connection

    return 0


def _compute_components(matrix, max_iter=100):
    """Compute components of a symmetric matrix using iterative rotation.

    Pure Python implementation suitable for small matrices (n < 50).
    """
    import math
    n = len(matrix)
    if n == 0:
        return []
    if n == 1:
        return [matrix[0][0]]

    # Copy matrix
    A = [row[:] for row in matrix]

    for _ in range(max_iter):
        # Find largest off-diagonal element
        max_val = 0
        p, q = 0, 1
        for i in range(n):
            for j in range(i + 1, n):
                if abs(A[i][j]) > max_val:
                    max_val = abs(A[i][j])
                    p, q = i, j

        if max_val < 1e-10:
            break  # Converged

        # Compute rotation angle
        if abs(A[p][p] - A[q][q]) < 1e-15:
            theta = math.pi / 4
        else:
            theta = 0.5 * math.atan2(2 * A[p][q], A[p][p] - A[q][q])

        c = math.cos(theta)
        s = math.sin(theta)

        # Apply rotation
        new_A = [row[:] for row in A]
        for i in range(n):
            if i != p and i != q:
                new_A[i][p] = c * A[i][p] + s * A[i][q]
                new_A[p][i] = new_A[i][p]
                new_A[i][q] = -s * A[i][p] + c * A[i][q]
                new_A[q][i] = new_A[i][q]
        new_A[p][p] = c * c * A[p][p] + 2 * s * c * A[p][q] + s * s * A[q][q]
        new_A[q][q] = s * s * A[p][p] - 2 * s * c * A[p][q] + c * c * A[q][q]
        new_A[p][q] = 0
        new_A[q][p] = 0
        A = new_A

    return [A[i][i] for i in range(n)]
