"""Merge multiple SourceResults into unified community data."""
from collections import defaultdict

from ._types import SourceResult, compute_consensus_tier


def merge_results(sources: list[SourceResult]) -> dict:
    """Merge SourceResults from multiple scrapers into the community.json format.

    Returns dict with: card_tiers, community_tips, meta_posts, sources,
    tier_post_count, strategy_post_count, source_names.
    """
    all_tier_votes: dict[str, list[str]] = defaultdict(list)
    all_tips: dict[str, list[str]] = defaultdict(list)
    all_meta_posts: list[dict] = []
    total_posts = 0
    source_names: list[str] = []

    for sr in sources:
        source_names.append(sr.source_name)
        total_posts += sr.post_count

        # Merge tier votes (already weighted by source scrapers)
        for name_lower, votes in sr.tier_votes.items():
            all_tier_votes[name_lower].extend(votes)

        # Merge tips
        for name_lower, tip_list in sr.tips.items():
            all_tips[name_lower].extend(tip_list)

        # Merge meta posts (source field already set by each scraper)
        all_meta_posts.extend(sr.meta_posts)

    # Compute consensus tiers
    card_tiers = {}
    for name_lower, votes in all_tier_votes.items():
        consensus = compute_consensus_tier(votes)
        if consensus:
            card_tiers[name_lower] = consensus

    # Deduplicate tips (keep unique by 80-char prefix, max 5 per entity)
    deduped_tips: dict[str, list[str]] = {}
    for name_lower, tip_list in all_tips.items():
        unique: list[str] = []
        seen: set[str] = set()
        for tip in tip_list:
            tip_key = tip.lower().strip()[:80]
            if tip_key not in seen:
                seen.add(tip_key)
                unique.append(tip)
        deduped_tips[name_lower] = unique[:5]

    # Sort meta posts by score descending
    all_meta_posts.sort(key=lambda x: -x.get("score", 0))

    # Count post types
    tier_count = sum(1 for p in all_meta_posts if p.get("type") == "tier_list")
    strategy_count = sum(1 for p in all_meta_posts if p.get("type") == "strategy")

    return {
        "card_tiers": card_tiers,
        "community_tips": deduped_tips,
        "meta_posts": all_meta_posts[:50],
        "sources": total_posts,
        "tier_post_count": tier_count,
        "strategy_post_count": strategy_count,
        "source_names": source_names,
    }
