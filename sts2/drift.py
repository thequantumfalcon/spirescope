"""Archetype drift detection — track coherence within a single run."""


def compute_archetype_drift(run, kb):
    """Track archetype classification floor by floor during a run."""
    trajectory = []
    running_deck = list(run.deck[:10]) if hasattr(run, "deck") else []  # starter cards

    # For completed runs, reconstruct deck floor by floor
    if run.floors:
        running_deck = []
        # Add starter-like cards (those without a pick floor)
        for cid in run.deck:
            found_pick = any(f.card_picked == cid for f in run.floors)
            if not found_pick:
                running_deck.append(cid)

        for floor in run.floors:
            if floor.card_picked:
                running_deck.append(floor.card_picked)

            if len(running_deck) >= 5:
                archetype = kb.classify_archetype(running_deck, run.character)
                trajectory.append({
                    "floor": floor.floor,
                    "archetype": archetype.get("name", "None"),
                    "confidence": archetype.get("confidence", 0),
                    "card_added": floor.card_picked or "",
                    "deck_size": len(running_deck),
                })

    return trajectory


def detect_drift_alert(trajectory):
    """Alert if archetype shifted significantly between early and late run."""
    if len(trajectory) < 6:
        return None

    mid = len(trajectory) // 2
    early = trajectory[:mid]
    late = trajectory[mid:]

    early_archs = [t["archetype"] for t in early if t["archetype"] != "None"]
    late_archs = [t["archetype"] for t in late if t["archetype"] != "None"]

    if not early_archs or not late_archs:
        return None

    early_dominant = max(set(early_archs), key=early_archs.count)
    late_dominant = max(set(late_archs), key=late_archs.count)

    if early_dominant != late_dominant:
        return f"Deck started as {early_dominant} but drifted toward {late_dominant}"

    return None
