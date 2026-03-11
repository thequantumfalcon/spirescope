"""Reddit community scraper for STS2 tier lists and strategy posts."""
import json
import logging
import time
import urllib.error
import urllib.request

from ._types import (
    REQUEST_DELAY,
    STRATEGY_KEYWORDS,
    STS2_INDICATORS,
    TIER_KEYWORDS,
    USER_AGENT,
    SourceResult,
    extract_tier_ratings,
    extract_tips,
)

log = logging.getLogger(__name__)

_SUBREDDITS = ["slaythespire", "slaythespire2"]


def _fetch_reddit_json(url: str, retries: int = 2) -> dict:
    """Fetch a Reddit JSON endpoint with retry on network/HTTP error."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
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
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return []
    except Exception:
        return []


def _is_sts2_post(post: dict) -> bool:
    """Check if a post is about STS2 (not STS1)."""
    if post["subreddit"] == "slaythespire2":
        return True
    combined = f"{post['title']} {post['selftext']} {post['flair']}"
    return bool(STS2_INDICATORS.search(combined))


def scrape(existing_names: set[str]) -> SourceResult:
    """Scrape Reddit for STS2 community tier lists and strategy posts."""
    result = SourceResult(source_name="reddit")
    all_posts: list[dict] = []

    print("  [Reddit] Fetching posts...")

    for subreddit in _SUBREDDITS:
        for time_filter in ("month", "year"):
            print(f"    r/{subreddit} top/{time_filter}")
            posts = _fetch_subreddit_posts(subreddit, "top", time_filter, limit=100)
            all_posts.extend(posts)
            time.sleep(REQUEST_DELAY)

        print(f"    r/{subreddit} hot")
        hot_posts = _fetch_subreddit_posts(subreddit, "hot", limit=50)
        all_posts.extend(hot_posts)
        time.sleep(REQUEST_DELAY)

    # Deduplicate by post ID
    seen_ids: set[str] = set()
    unique_posts = []
    for post in all_posts:
        if post["id"] not in seen_ids:
            seen_ids.add(post["id"])
            unique_posts.append(post)

    # Filter to STS2 posts
    sts2_posts = [p for p in unique_posts if _is_sts2_post(p)]
    result.post_count = len(sts2_posts)
    print(f"    {len(unique_posts)} unique posts, {len(sts2_posts)} STS2-related")

    # Separate tier lists and strategy posts
    tier_posts = [p for p in sts2_posts if TIER_KEYWORDS.search(f"{p['title']} {p['selftext']}")]
    strategy_posts = [p for p in sts2_posts if STRATEGY_KEYWORDS.search(f"{p['title']} {p['selftext']}")]

    # Extract tier ratings
    for post in tier_posts:
        combined_text = f"{post['title']}\n{post['selftext']}"
        ratings = extract_tier_ratings(combined_text, existing_names)
        if ratings:
            for name_lower, tiers in ratings.items():
                result.tier_votes[name_lower].extend(tiers)

        if post["score"] > 20 and post["permalink"]:
            time.sleep(REQUEST_DELAY)
            comments = _fetch_post_comments(post["permalink"], limit=30)
            for comment in comments:
                ratings = extract_tier_ratings(comment, existing_names)
                for name_lower, tiers in ratings.items():
                    result.tier_votes[name_lower].extend(tiers)

    # Extract tips from strategy posts
    for post in strategy_posts[:30]:
        combined_text = f"{post['title']}\n{post['selftext']}"
        tips = extract_tips(combined_text, existing_names)
        if tips:
            for name_lower, tip_list in tips.items():
                result.tips[name_lower].extend(tip_list)

        if post["score"] > 10:
            post_type = "tier_list" if TIER_KEYWORDS.search(post["title"]) else "strategy"
            result.meta_posts.append({
                "title": post["title"],
                "url": f"https://reddit.com{post['permalink']}",
                "score": post["score"],
                "comments": post["num_comments"],
                "type": post_type,
                "date": int(post["created_utc"]),
                "source": "reddit",
            })

    print(f"    {len(tier_posts)} tier posts, {len(strategy_posts)} strategy posts")
    return result
