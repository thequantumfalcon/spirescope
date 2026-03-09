"""Steam community scraper for STS2 reviews, guides, and discussions."""
import json
import logging
import re
import time
import urllib.error
import urllib.request
from html.parser import HTMLParser

from ._types import (
    STRATEGY_KEYWORDS, TIER_KEYWORDS, SourceResult,
    USER_AGENT, REQUEST_DELAY, extract_tier_ratings, extract_tips,
)

log = logging.getLogger(__name__)

_APP_ID = "2868840"  # Slay the Spire 2
_REVIEWS_URL = (
    f"https://store.steampowered.com/appreviews/{_APP_ID}"
    "?json=1&num_per_page=100&filter=recent&review_type=all&purchase_type=all"
)
_GUIDES_URL = f"https://steamcommunity.com/app/{_APP_ID}/guides/"
_DISCUSSIONS_URL = f"https://steamcommunity.com/app/{_APP_ID}/discussions/"


def _fetch_url(url: str, retries: int = 1) -> str:
    """Fetch URL content as string with retry."""
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except (urllib.error.URLError, OSError) as e:
            if attempt < retries:
                log.warning("Steam fetch failed (attempt %d/%d): %s", attempt + 1, retries + 1, e)
                time.sleep(2)
            else:
                raise


def _fetch_json(url: str) -> dict:
    """Fetch and parse JSON from URL."""
    return json.loads(_fetch_url(url))


# ── Steam Reviews (JSON API) ────────────────────────────────────────────

def _scrape_reviews(existing_names: set[str], result: SourceResult) -> None:
    """Fetch recent Steam reviews and extract tips."""
    try:
        data = _fetch_json(_REVIEWS_URL)
    except (urllib.error.URLError, json.JSONDecodeError, OSError) as e:
        result.errors.append(f"Steam reviews: {e}")
        print(f"    Reviews: network error, skipping")
        return

    reviews = data.get("reviews", [])
    strategy_reviews = []

    for review in reviews:
        text = review.get("review", "")
        votes_up = review.get("votes_up", 0)

        if not text or votes_up < 3:
            continue

        # Extract tips from substantive reviews
        if len(text) > 50:
            tips = extract_tips(text, existing_names)
            for name_lower, tip_list in tips.items():
                result.tips[name_lower].extend(tip_list)

        # Collect strategy-relevant reviews as meta_posts
        if votes_up >= 10 and STRATEGY_KEYWORDS.search(text):
            strategy_reviews.append(review)

    for review in strategy_reviews[:10]:
        result.meta_posts.append({
            "title": review["review"][:100].strip() + ("..." if len(review["review"]) > 100 else ""),
            "url": f"https://steamcommunity.com/profiles/{review.get('author', {}).get('steamid', '')}/recommended/{_APP_ID}/",
            "score": review.get("votes_up", 0),
            "comments": review.get("comment_count", 0),
            "type": "strategy",
            "date": review.get("timestamp_created", 0),
            "source": "steam_review",
        })

    result.post_count += len(reviews)
    print(f"    Reviews: {len(reviews)} fetched, {len(strategy_reviews)} strategy-relevant")


# ── Steam Guides (HTML) ─────────────────────────────────────────────────

class _GuideListParser(HTMLParser):
    """Parse Steam guide listing page for guide titles and URLs."""

    def __init__(self):
        super().__init__()
        self.guides: list[dict] = []
        self._in_title = False
        self._current: dict = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        # Guide links are <a> tags pointing to /sharedfiles/filedetails/
        if tag == "a" and attr_dict.get("href", "").startswith("https://steamcommunity.com/sharedfiles/filedetails/"):
            self._current = {"url": attr_dict["href"], "title": ""}
        # Guide title is inside a div with class containing "workshopItemTitle"
        if tag == "div" and "workshopItemTitle" in attr_dict.get("class", ""):
            self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title and self._current:
            self._current["title"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "div" and self._in_title:
            self._in_title = False
            if self._current.get("title"):
                self.guides.append(self._current)
            self._current = {}


class _GuideDetailParser(HTMLParser):
    """Parse a Steam guide detail page for body text."""

    def __init__(self):
        super().__init__()
        self.text_parts: list[str] = []
        self._in_description = False
        self._depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        if tag == "div" and "workshopItemDescription" in attr_dict.get("class", ""):
            self._in_description = True
            self._depth = 0
        if self._in_description and tag == "div":
            self._depth += 1

    def handle_data(self, data: str) -> None:
        if self._in_description:
            stripped = data.strip()
            if stripped:
                self.text_parts.append(stripped)

    def handle_endtag(self, tag: str) -> None:
        if self._in_description and tag == "div":
            self._depth = max(0, self._depth - 1)
            if self._depth == 0:
                self._in_description = False

    def get_text(self) -> str:
        return "\n".join(self.text_parts)


def _scrape_guides(existing_names: set[str], result: SourceResult) -> None:
    """Fetch Steam guides index, filter strategy/tier guides, extract content."""
    try:
        html = _fetch_url(_GUIDES_URL)
    except (urllib.error.URLError, OSError) as e:
        result.errors.append(f"Steam guides: {e}")
        print(f"    Guides: network error, skipping")
        return

    parser = _GuideListParser()
    try:
        parser.feed(html)
    except Exception as e:
        result.errors.append(f"Steam guides parse: {e}")
        print(f"    Guides: parse error, skipping")
        return

    # Filter guides with strategy/tier keywords in title
    matching = []
    for guide in parser.guides:
        title = guide.get("title", "")
        if TIER_KEYWORDS.search(title) or STRATEGY_KEYWORDS.search(title):
            matching.append(guide)

    print(f"    Guides: {len(parser.guides)} found, {len(matching)} strategy-relevant")

    # Fetch detail pages for matching guides (up to 5)
    for guide in matching[:5]:
        time.sleep(REQUEST_DELAY)
        try:
            detail_html = _fetch_url(guide["url"])
        except (urllib.error.URLError, OSError):
            continue

        detail_parser = _GuideDetailParser()
        try:
            detail_parser.feed(detail_html)
        except Exception:
            continue

        body_text = detail_parser.get_text()
        if not body_text:
            continue

        # Extract tier ratings and tips from guide body
        ratings = extract_tier_ratings(body_text, existing_names)
        for name_lower, tiers in ratings.items():
            # Weight guide tier votes at 1.5x (curated content)
            result.tier_votes[name_lower].extend(tiers)
            # Add an extra half-vote for each (round up)
            extra = [t for i, t in enumerate(tiers) if i % 2 == 0]
            result.tier_votes[name_lower].extend(extra)

        tips = extract_tips(body_text, existing_names)
        for name_lower, tip_list in tips.items():
            result.tips[name_lower].extend(tip_list)

        result.meta_posts.append({
            "title": guide["title"],
            "url": guide["url"],
            "score": 50,  # Normalized score for guides (curated content)
            "comments": 0,
            "type": "strategy",
            "date": 0,
            "source": "steam_guide",
        })
        result.post_count += 1


# ── Steam Discussions (HTML) ────────────────────────────────────────────

class _DiscussionListParser(HTMLParser):
    """Parse Steam discussion listing for topic titles and reply counts."""

    def __init__(self):
        super().__init__()
        self.topics: list[dict] = []
        self._in_title = False
        self._current: dict = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_dict = dict(attrs)
        # Discussion topic links
        if tag == "a" and "forum_topic_overlay" in attr_dict.get("class", ""):
            href = attr_dict.get("href", "")
            if href.startswith("https://"):
                self._current = {"url": href, "title": ""}
                self._in_title = True

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._current["title"] = data.strip()

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._in_title:
            self._in_title = False
            if self._current.get("title"):
                self.topics.append(self._current)
            self._current = {}


def _scrape_discussions(existing_names: set[str], result: SourceResult) -> None:
    """Fetch Steam discussions index page and extract strategy topics."""
    try:
        html = _fetch_url(_DISCUSSIONS_URL)
    except (urllib.error.URLError, OSError) as e:
        result.errors.append(f"Steam discussions: {e}")
        print(f"    Discussions: network error, skipping")
        return

    parser = _DiscussionListParser()
    try:
        parser.feed(html)
    except Exception as e:
        result.errors.append(f"Steam discussions parse: {e}")
        print(f"    Discussions: parse error, skipping")
        return

    matching = []
    for topic in parser.topics:
        title = topic.get("title", "")
        if STRATEGY_KEYWORDS.search(title) or TIER_KEYWORDS.search(title):
            matching.append(topic)

    for topic in matching[:10]:
        result.meta_posts.append({
            "title": topic["title"],
            "url": topic["url"],
            "score": 10,  # Base score for discussion topics
            "comments": 0,
            "type": "strategy",
            "date": 0,
            "source": "steam_discussion",
        })

    result.post_count += len(parser.topics)
    print(f"    Discussions: {len(parser.topics)} found, {len(matching)} strategy-relevant")


# ── Public API ───────────────────────────────────────────────────────────

def scrape(existing_names: set[str]) -> SourceResult:
    """Scrape all Steam sources for STS2 community data."""
    result = SourceResult(source_name="steam")
    print("  [Steam] Fetching data...")

    _scrape_reviews(existing_names, result)
    time.sleep(REQUEST_DELAY)

    _scrape_guides(existing_names, result)
    time.sleep(REQUEST_DELAY)

    _scrape_discussions(existing_names, result)

    print(f"    Total: {result.post_count} items, {len(result.meta_posts)} meta posts")
    return result
