"""Community data scraper: pull tier lists, tips, and meta from Reddit.

Reddit's public JSON API (append .json to any URL) provides post data
without authentication. Discord requires a bot token and is not supported.

Usage: python -m sts2 community
"""
import json
import logging
import re
import time
import urllib.request
import urllib.error
from collections import Counter, defaultdict

from sts2.config import DATA_DIR

log = logging.getLogger(__name__)

_USER_AGENT = "Spirescope/1.0 (community data collector)"
_REQUEST_DELAY = 2.0  # seconds between Reddit requests (respect rate limits)

# Subreddits to search
_SUBREDDITS = ["slaythespire", "slaythespire2"]

# Keywords that indicate tier list or strategy content
_TIER_KEYWORDS = re.compile(
    r"tier\s*list|card\s*ranking|best\s*cards|worst\s*cards|"
    r"s[\s-]*tier|a[\s-]*tier|card\s*tier|relic\s*tier|"
    r"relic\s*ranking|best\s*relics|worst\s*relics|"
    r"meta\s*report|win\s*rate|power\s*ranking",
    re.IGNORECASE,
)
_STRATEGY_KEYWORDS = re.compile(
    r"strategy|guide|tips|how\s*to|deck\s*building|archetype|"
    r"synergy|combo|build\s*guide|new\s*player|beginner|advanced|"
    r"ironclad|silent|defect|necrobinder|regent",
    re.IGNORECASE,
)

# Standard tier labels
_TIER_LABELS = {"s", "a", "b", "c", "d", "f"}
_TIER_PATTERN = re.compile(
    r"(?:^|\n)\s*\*?\*?\[?\s*([SABCDF])\s*[\]\-:)]*\s*(?:tier)?[\s:\-]*(.+?)(?:\n|$)",
    re.IGNORECASE | re.MULTILINE,
)

# STS2 flair filter (some subreddits use flairs for game version)
_STS2_INDICATORS = re.compile(
    r"slay\s*the\s*spire\s*2|sts\s*2|spire\s*2|sts2|"
    r"necrobinder|regent|early\s*access",
    re.IGNORECASE,
)


def _fetch_reddit_json(url: str, retries: int = 2) -> dict:
    """Fetch a Reddit JSON endpoint with retry on network/HTTP error."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                try:
                    wait = min(int(e.headers.get("Retry-After", 10)), 60)
                except (ValueError, TypeError):
                    wait = 10
                log.warning("Reddit 429 rate limited, waiting %ds (attempt %d/%d)", wait, attempt + 1, retries + 1)
                if attempt < retries:
                    time.sleep(wait)
                    continue
                raise
            if attempt < retries:
                log.warning("Reddit HTTP %d (attempt %d/%d): %s", e.code, attempt + 1, retries + 1, e)
                time.sleep(2 * (attempt + 1))
            else:
                raise
        except urllib.error.URLError as e:
            if attempt < retries:
                log.warning("Reddit fetch failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
                time.sleep(2 * (attempt + 1))
            else:
                raise


def _fetch_subreddit_posts(subreddit: str, sort: str = "top",
                           time_filter: str = "month", limit: int = 50) -> list[dict]:
    """Fetch posts from a subreddit using the public JSON API."""
    url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?t={time_filter}&limit={limit}"
    try:
        data = _fetch_reddit_json(url)
        posts = []
        for child in data.get("data", {}).get("children", []):
            post = child.get("data", {})
            if post.get("removed_by_category"):
                continue
            posts.append({
                "id": post.get("id", ""),
                "title": post.get("title", ""),
                "selftext": post.get("selftext", ""),
                "score": post.get("score", 0),
                "num_comments": post.get("num_comments", 0),
                "url": post.get("url", ""),
                "permalink": post.get("permalink", ""),
                "flair": post.get("link_flair_text", ""),
                "created_utc": post.get("created_utc", 0),
                "subreddit": subreddit,
            })
        return posts
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        log.warning("Failed to fetch r/%s: %s", subreddit, e)
        print(f"    Skipped r/{subreddit}/{sort} (network error, will continue)")
        return []


def _fetch_post_comments(permalink: str, limit: int = 50) -> list[str]:
    """Fetch top comments from a post for additional card/relic mentions."""
    url = f"https://www.reddit.com{permalink}.json?limit={limit}&sort=top"
    try:
        data = _fetch_reddit_json(url)
        comments = []
        if len(data) >= 2:
            for child in data[1].get("data", {}).get("children", []):
                body = child.get("data", {}).get("body", "")
                if body and len(body) > 20:
                    comments.append(body)
        return comments[:limit]
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        log.debug("Failed to fetch comments for %s: %s", permalink, e)
        return []
    except Exception:
        return []


def _is_sts2_post(post: dict) -> bool:
    """Check if a post is about STS2 (not STS1)."""
    if post["subreddit"] == "slaythespire2":
        return True
    combined = f"{post['title']} {post['selftext']} {post['flair']}"
    return bool(_STS2_INDICATORS.search(combined))


def _extract_tier_ratings(text: str, existing_names: set[str]) -> dict[str, list[str]]:
    """Extract tier ratings from post text.

    Returns {card_or_relic_name_lower: [tier_label, ...]} for each mention.
    Multiple tier labels per name are possible across different posts.
    """
    ratings = defaultdict(list)
    for match in _TIER_PATTERN.finditer(text):
        tier = match.group(1).upper()
        items_text = match.group(2).strip()
        # Split on commas, slashes, or bullet-like separators
        items = re.split(r"[,/•|]+", items_text)
        for item in items:
            name = item.strip().strip("*_[]()").strip()
            if len(name) < 2 or len(name) > 50:
                continue
            name_lower = name.lower()
            # Only count if it matches a known game entity
            if name_lower in existing_names:
                ratings[name_lower].append(tier)
    return ratings


def _extract_tips(text: str, entity_names: set[str]) -> dict[str, list[str]]:
    """Extract strategy tips mentioning specific cards/relics."""
    tips = defaultdict(list)
    sentences = re.split(r"[.!?\n]+", text)
    for sentence in sentences:
        sentence = sentence.strip()
        if len(sentence) < 20 or len(sentence) > 300:
            continue
        sentence_lower = sentence.lower()
        for name in entity_names:
            if name in sentence_lower:
                tips[name].append(sentence)
    return tips


def _compute_consensus_tier(tier_votes: list[str]) -> str:
    """Determine consensus tier from multiple community votes."""
    if not tier_votes:
        return ""
    tier_order = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    # Weighted average, then round to nearest tier
    total_score = sum(tier_order.get(t, 2) for t in tier_votes)
    avg = total_score / len(tier_votes)
    reverse_order = {5: "S", 4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
    return reverse_order.get(round(avg), "B")


def scrape_community_data(existing_names: set[str] = None) -> dict:
    """Scrape Reddit for STS2 community tier lists, ratings, and tips.

    Args:
        existing_names: set of lowercased entity names from the knowledge base.
            If None, skips name matching (collects raw data only).

    Returns dict with:
        - card_tiers: {name_lower: consensus_tier}
        - relic_tiers: {name_lower: consensus_tier}
        - community_tips: {name_lower: [tip_strings]}
        - meta_posts: [{title, url, score, type}] — high-value strategy posts
        - sources: count of posts analyzed
    """
    if existing_names is None:
        existing_names = set()

    all_posts = []
    tier_votes = defaultdict(list)    # name_lower -> [tier_label, ...]
    community_tips = defaultdict(list)
    meta_posts = []

    print("\n  Spirescope Community Data Collector")
    print("  ===================================\n")

    for subreddit in _SUBREDDITS:
        # Fetch top posts from multiple time ranges
        for time_filter in ("month", "year"):
            print(f"  Fetching r/{subreddit} top/{time_filter} ...")
            posts = _fetch_subreddit_posts(subreddit, "top", time_filter, limit=100)
            all_posts.extend(posts)
            time.sleep(_REQUEST_DELAY)

        # Also fetch recent hot posts
        print(f"  Fetching r/{subreddit} hot ...")
        hot_posts = _fetch_subreddit_posts(subreddit, "hot", limit=50)
        all_posts.extend(hot_posts)
        time.sleep(_REQUEST_DELAY)

    # Deduplicate by post ID
    seen_ids = set()
    unique_posts = []
    for post in all_posts:
        if post["id"] not in seen_ids:
            seen_ids.add(post["id"])
            unique_posts.append(post)

    print(f"\n  Collected {len(unique_posts)} unique posts")

    # Filter to STS2 posts
    sts2_posts = [p for p in unique_posts if _is_sts2_post(p)]
    print(f"  {len(sts2_posts)} posts identified as STS2-related")

    # Process tier list posts
    tier_posts = [p for p in sts2_posts if _TIER_KEYWORDS.search(f"{p['title']} {p['selftext']}")]
    strategy_posts = [p for p in sts2_posts if _STRATEGY_KEYWORDS.search(f"{p['title']} {p['selftext']}")]

    print(f"  {len(tier_posts)} tier list posts, {len(strategy_posts)} strategy posts\n")

    # Extract tier ratings from tier list posts
    processed_tier = 0
    for post in tier_posts:
        combined_text = f"{post['title']}\n{post['selftext']}"
        ratings = _extract_tier_ratings(combined_text, existing_names)
        if ratings:
            processed_tier += 1
            for name_lower, tiers in ratings.items():
                tier_votes[name_lower].extend(tiers)

        # For high-score tier posts, also check comments
        if post["score"] > 20 and post["permalink"]:
            time.sleep(_REQUEST_DELAY)
            comments = _fetch_post_comments(post["permalink"], limit=30)
            for comment in comments:
                ratings = _extract_tier_ratings(comment, existing_names)
                for name_lower, tiers in ratings.items():
                    tier_votes[name_lower].extend(tiers)

    # Extract tips from strategy posts
    processed_strategy = 0
    for post in strategy_posts[:30]:  # cap to avoid too many requests
        combined_text = f"{post['title']}\n{post['selftext']}"
        tips = _extract_tips(combined_text, existing_names)
        if tips:
            processed_strategy += 1
            for name_lower, tip_list in tips.items():
                community_tips[name_lower].extend(tip_list)

        # Track high-value meta posts
        if post["score"] > 10:
            post_type = "tier_list" if _TIER_KEYWORDS.search(post["title"]) else "strategy"
            meta_posts.append({
                "title": post["title"],
                "url": f"https://reddit.com{post['permalink']}",
                "score": post["score"],
                "comments": post["num_comments"],
                "type": post_type,
                "date": int(post["created_utc"]),
            })

    # Compute consensus tiers
    card_tiers = {}
    for name_lower, votes in tier_votes.items():
        consensus = _compute_consensus_tier(votes)
        if consensus:
            card_tiers[name_lower] = consensus

    # Deduplicate tips (keep unique, max 5 per entity)
    for name_lower in community_tips:
        unique_tips = []
        seen = set()
        for tip in community_tips[name_lower]:
            tip_key = tip.lower().strip()[:80]
            if tip_key not in seen:
                seen.add(tip_key)
                unique_tips.append(tip)
        community_tips[name_lower] = unique_tips[:5]

    # Sort meta posts by score
    meta_posts.sort(key=lambda x: -x["score"])

    print(f"  Processed {processed_tier} tier list posts")
    print(f"  Processed {processed_strategy} strategy posts")
    print(f"  Found {len(card_tiers)} entity tier ratings")
    print(f"  Found {sum(len(v) for v in community_tips.values())} tips for {len(community_tips)} entities")
    print(f"  Found {len(meta_posts)} high-value meta posts")

    result = {
        "card_tiers": card_tiers,
        "community_tips": dict(community_tips),
        "meta_posts": meta_posts[:50],
        "sources": len(sts2_posts),
        "tier_post_count": len(tier_posts),
        "strategy_post_count": len(strategy_posts),
    }

    return result


def save_community_data(data: dict) -> None:
    """Save community data to disk."""
    path = DATA_DIR / "community.json"
    tmp_path = path.with_suffix(".tmp")
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    tmp_path.replace(path)
    print(f"\n  Saved community data to {path}")


def apply_community_tiers(community_data: dict) -> None:
    """Apply community tier ratings to cards.json and relics.json.

    Only updates the 'tier' field on cards that have a community consensus.
    Does NOT overwrite tiers that were already set manually.
    """
    tiers = community_data.get("card_tiers", {})
    if not tiers:
        return

    updated_cards = 0

    # Update cards
    cards_path = DATA_DIR / "cards.json"
    if cards_path.exists():
        cards = json.loads(cards_path.read_text(encoding="utf-8"))
        for card in cards:
            name_lower = card.get("name", "").lower().strip()
            if name_lower in tiers and not card.get("tier"):
                card["tier"] = tiers[name_lower]
                updated_cards += 1
        tmp_path = cards_path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(cards, f, indent=2, ensure_ascii=False)
        tmp_path.replace(cards_path)

    print(f"  Applied tiers to {updated_cards} cards")


def _load_cached_community_data() -> dict | None:
    """Load previously saved community data as fallback."""
    path = DATA_DIR / "community.json"
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
    return None


def run_community_scraper():
    """Main entry point: scrape, save, and apply community data."""
    # Build name set from existing data
    existing_names = set()
    for filename in ("cards.json", "relics.json", "potions.json", "enemies.json"):
        path = DATA_DIR / filename
        if path.exists():
            for item in json.loads(path.read_text(encoding="utf-8")):
                name = item.get("name", "").lower().strip()
                if name:
                    existing_names.add(name)

    data = scrape_community_data(existing_names)

    # If scrape returned nothing useful, fall back to cached data
    if not data.get("sources") and not data.get("card_tiers"):
        cached = _load_cached_community_data()
        if cached:
            print("\n  Reddit unavailable — using cached community data.")
            print("  Restart Spirescope to see existing tiers.\n")
            return

    save_community_data(data)
    apply_community_tiers(data)

    print("\n  Done! Community data collected and applied.")
    print("  Restart Spirescope to see updated tiers.\n")
