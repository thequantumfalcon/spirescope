"""Tests for multi-source community scraper (Steam + merge logic)."""
import json
from unittest.mock import patch

from sts2.community._merge import merge_results
from sts2.community._types import (
    SourceResult,
    extract_tier_ratings,
    extract_tips,
)

# ── SourceResult ─────────────────────────────────────────────────────────

def _empty_result(name: str = "test") -> SourceResult:
    return SourceResult(source_name=name)


# ── Steam reviews ────────────────────────────────────────────────────────

def test_steam_reviews_parse():
    """Mock Steam reviews JSON and verify tips are extracted."""
    from sts2.community.steam import _scrape_reviews

    mock_json = {
        "reviews": [
            {
                "recommendationid": "1",
                "review": "Bash is incredibly strong in early game. Iron Wave provides good defense.",
                "votes_up": 15,
                "comment_count": 2,
                "timestamp_created": 1700000000,
                "author": {"steamid": "123"},
            },
            {
                "recommendationid": "2",
                "review": "fun game",
                "votes_up": 1,
                "comment_count": 0,
                "timestamp_created": 1700000000,
                "author": {"steamid": "456"},
            },
        ]
    }
    names = {"bash", "iron wave"}
    result = SourceResult(source_name="steam")

    with patch("sts2.community.steam._fetch_json", return_value=mock_json):
        _scrape_reviews(names, result)

    assert "bash" in result.tips
    assert result.post_count == 2


def test_steam_reviews_network_error():
    """Network error returns empty result, does not raise."""
    import urllib.error

    from sts2.community.steam import _scrape_reviews

    result = SourceResult(source_name="steam")
    with patch("sts2.community.steam._fetch_json", side_effect=urllib.error.URLError("timeout")):
        _scrape_reviews({"bash"}, result)

    assert result.post_count == 0
    assert len(result.errors) == 1


# ── Steam guides ─────────────────────────────────────────────────────────

def test_steam_guides_parse_index():
    """Mock guide index HTML and verify titles are extracted."""
    from sts2.community.steam import _GuideListParser

    html = '''
    <div class="workshopItem">
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=123">
        <div class="workshopItemTitle">Best Cards Tier List</div>
      </a>
    </div>
    <div class="workshopItem">
      <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=456">
        <div class="workshopItemTitle">How to mod the game</div>
      </a>
    </div>
    '''
    parser = _GuideListParser()
    parser.feed(html)

    assert len(parser.guides) == 2
    assert parser.guides[0]["title"] == "Best Cards Tier List"
    assert "filedetails/?id=123" in parser.guides[0]["url"]


def test_steam_guide_detail_parse():
    """Mock guide detail HTML and verify body text is extracted."""
    from sts2.community.steam import _GuideDetailParser

    html = '''
    <div class="workshopItemDescription">
      <div>S: Bash, Inflame</div>
      <div>A: Defend, Iron Wave</div>
      <div>Bash is the best starter card for Ironclad builds</div>
    </div>
    '''
    parser = _GuideDetailParser()
    parser.feed(html)
    text = parser.get_text()

    assert "Bash" in text
    assert "Iron Wave" in text


def test_steam_discussions_parse():
    """Mock discussion index HTML and verify topic filtering."""
    from sts2.community.steam import _DiscussionListParser

    html = '''
    <a class="forum_topic_overlay" href="https://steam.example/topic/1">Ironclad strategy guide</a>
    <a class="forum_topic_overlay" href="https://steam.example/topic/2">Bug report: crash on startup</a>
    <a class="forum_topic_overlay" href="https://steam.example/topic/3">Best deck building tips</a>
    '''
    parser = _DiscussionListParser()
    parser.feed(html)

    assert len(parser.topics) == 3
    assert parser.topics[0]["title"] == "Ironclad strategy guide"


# ── Merge logic ──────────────────────────────────────────────────────────

def test_merge_empty_results():
    """Merging two empty SourceResults produces empty output."""
    merged = merge_results([_empty_result("reddit"), _empty_result("steam")])
    assert merged["card_tiers"] == {}
    assert merged["community_tips"] == {}
    assert merged["meta_posts"] == []
    assert merged["sources"] == 0


def test_merge_tier_votes():
    """Tier votes from multiple sources are combined for consensus."""
    r1 = SourceResult(source_name="reddit")
    r1.tier_votes["bash"] = ["S", "S", "A"]

    r2 = SourceResult(source_name="steam")
    r2.tier_votes["bash"] = ["S", "A"]

    merged = merge_results([r1, r2])
    # 4 S-votes (5) + 2 A-votes (4) = 28/5 = 4.8 -> rounds to 5 -> S
    assert merged["card_tiers"]["bash"] == "S"


def test_merge_deduplicates_tips():
    """Same tip from two sources appears only once."""
    r1 = SourceResult(source_name="reddit")
    r1.tips["bash"] = ["Bash is great for early damage output in act one"]

    r2 = SourceResult(source_name="steam")
    r2.tips["bash"] = ["Bash is great for early damage output in act one"]

    merged = merge_results([r1, r2])
    assert len(merged["community_tips"]["bash"]) == 1


def test_merge_meta_posts_sorted():
    """Meta posts from mixed sources are sorted by score descending."""
    r1 = SourceResult(source_name="reddit")
    r1.meta_posts = [{"title": "Reddit post", "score": 50, "source": "reddit"}]

    r2 = SourceResult(source_name="steam")
    r2.meta_posts = [{"title": "Steam guide", "score": 100, "source": "steam_guide"}]

    merged = merge_results([r1, r2])
    assert merged["meta_posts"][0]["source"] == "steam_guide"
    assert merged["meta_posts"][1]["source"] == "reddit"


def test_merge_source_attribution():
    """Each meta_post retains its source field."""
    r1 = SourceResult(source_name="reddit")
    r1.meta_posts = [{"title": "A", "score": 10, "source": "reddit", "type": "strategy"}]

    r2 = SourceResult(source_name="steam")
    r2.meta_posts = [{"title": "B", "score": 5, "source": "steam_guide", "type": "strategy"}]

    merged = merge_results([r1, r2])
    sources = {p["source"] for p in merged["meta_posts"]}
    assert "reddit" in sources
    assert "steam_guide" in sources


def test_merge_source_names():
    """Merged result includes list of source names."""
    merged = merge_results([_empty_result("reddit"), _empty_result("steam")])
    assert "reddit" in merged["source_names"]
    assert "steam" in merged["source_names"]


# ── Orchestrator ─────────────────────────────────────────────────────────

def test_source_enable_disable():
    """STS2_COMMUNITY_SOURCES env var controls which sources run."""
    from sts2.community import _enabled_sources
    with patch("sts2.community.COMMUNITY_SOURCES", "reddit"):
        assert _enabled_sources() == ["reddit"]
    with patch("sts2.community.COMMUNITY_SOURCES", "steam"):
        assert _enabled_sources() == ["steam"]
    with patch("sts2.community.COMMUNITY_SOURCES", "all"):
        result = _enabled_sources()
        assert "reddit" in result
        assert "steam" in result


def test_unknown_source_ignored():
    """Unknown source names in env var are silently filtered out."""
    from sts2.community import _enabled_sources
    with patch("sts2.community.COMMUNITY_SOURCES", "reddit,discord"):
        result = _enabled_sources()
    assert result == ["reddit"]
    assert "discord" not in result


def test_empty_sources():
    """Empty sources string results in empty merge."""
    from sts2.community import _enabled_sources
    with patch("sts2.community.COMMUNITY_SOURCES", ""):
        assert _enabled_sources() == []
    # merge_results with empty list still works
    merged = merge_results([])
    assert merged["card_tiers"] == {}
    assert merged["meta_posts"] == []


def test_one_source_fails_others_continue():
    """If Reddit fails, Steam still runs and vice versa."""
    from sts2.community import scrape_community_data

    def mock_reddit_fail(names):
        raise ConnectionError("Reddit down")

    mock_steam_result = SourceResult(source_name="steam", post_count=5)
    mock_steam_result.meta_posts = [{"title": "Test", "score": 10, "source": "steam_guide", "type": "strategy"}]

    with patch("sts2.community.COMMUNITY_SOURCES", "all"), \
         patch("sts2.community.reddit.scrape", side_effect=mock_reddit_fail), \
         patch("sts2.community.steam.scrape", return_value=mock_steam_result):
        data = scrape_community_data({"bash"})

    assert data["sources"] == 5
    assert len(data["meta_posts"]) == 1


# ── Backward compatibility ───────────────────────────────────────────────

def test_backward_compat_imports():
    """All old imports from sts2.community still work."""
    from sts2.community import (
        _compute_consensus_tier,
        _extract_tier_ratings,
        _extract_tips,
        _is_sts2_post,
        run_community_scraper,
    )

    # Verify they're callable
    assert callable(_compute_consensus_tier)
    assert callable(_extract_tier_ratings)
    assert callable(_extract_tips)
    assert callable(_is_sts2_post)
    assert callable(run_community_scraper)


def test_consensus_tier_via_package():
    """_compute_consensus_tier still works through package re-export."""
    from sts2.community import _compute_consensus_tier
    assert _compute_consensus_tier(["S", "S", "A"]) == "S"
    assert _compute_consensus_tier(["A", "B", "C"]) == "B"
    assert _compute_consensus_tier([]) == ""


# ── Orchestrator: save, apply, load ──────────────────────────────────────

def test_save_community_data(tmp_path):
    """save_community_data writes JSON to disk."""
    from sts2.community import save_community_data
    data = {"card_tiers": {"bash": "S"}, "community_tips": {}, "meta_posts": []}
    with patch("sts2.community.DATA_DIR", tmp_path):
        save_community_data(data)
    saved = json.loads((tmp_path / "community.json").read_text(encoding="utf-8"))
    assert saved["card_tiers"]["bash"] == "S"


def test_load_cached_community_data(tmp_path):
    """_load_cached_community_data reads existing JSON."""
    from sts2.community import _load_cached_community_data
    data = {"card_tiers": {"bash": "A"}, "meta_posts": []}
    (tmp_path / "community.json").write_text(json.dumps(data), encoding="utf-8")
    with patch("sts2.community.DATA_DIR", tmp_path):
        loaded = _load_cached_community_data()
    assert loaded["card_tiers"]["bash"] == "A"


def test_load_cached_community_data_missing(tmp_path):
    """_load_cached_community_data returns None when file missing."""
    from sts2.community import _load_cached_community_data
    with patch("sts2.community.DATA_DIR", tmp_path):
        assert _load_cached_community_data() is None


def test_load_cached_community_data_invalid_json(tmp_path):
    """_load_cached_community_data returns None for invalid JSON."""
    from sts2.community import _load_cached_community_data
    (tmp_path / "community.json").write_text("not json", encoding="utf-8")
    with patch("sts2.community.DATA_DIR", tmp_path):
        assert _load_cached_community_data() is None


def test_apply_community_tiers(tmp_path):
    """apply_community_tiers updates cards.json tiers."""
    from sts2.community import apply_community_tiers
    cards = [
        {"name": "Bash", "tier": ""},
        {"name": "Defend", "tier": "A"},  # already set, should not be overwritten
    ]
    (tmp_path / "cards.json").write_text(json.dumps(cards), encoding="utf-8")
    community_data = {"card_tiers": {"bash": "S", "defend": "B"}}
    with patch("sts2.community.DATA_DIR", tmp_path):
        apply_community_tiers(community_data)
    updated = json.loads((tmp_path / "cards.json").read_text(encoding="utf-8"))
    assert updated[0]["tier"] == "S"
    assert updated[1]["tier"] == "A"  # preserved


def test_apply_community_tiers_empty():
    """apply_community_tiers with no tiers is a no-op."""
    from sts2.community import apply_community_tiers
    apply_community_tiers({})  # should not crash
    apply_community_tiers({"card_tiers": {}})


def test_run_community_scraper_fallback_cached(tmp_path):
    """run_community_scraper falls back to cached data when scrape returns nothing."""
    from sts2.community import run_community_scraper
    cached_data = {"card_tiers": {"bash": "S"}, "sources": 10}

    empty_merged = {"sources": 0, "card_tiers": {}, "community_tips": {}, "meta_posts": [],
                    "tier_post_count": 0, "strategy_post_count": 0, "source_names": []}
    with patch("sts2.community.DATA_DIR", tmp_path), \
         patch("sts2.community.scrape_community_data", return_value=empty_merged), \
         patch("sts2.community._load_cached_community_data", return_value=cached_data):
        run_community_scraper()


# ── Steam: full flow tests ──────────────────────────────────────────────

def test_steam_scrape_guides_full_flow():
    """Mock full guide scrape flow: index + detail page."""
    from sts2.community.steam import _scrape_guides

    index_html = '''
    <a href="https://steamcommunity.com/sharedfiles/filedetails/?id=123">
      <div class="workshopItemTitle">Best Strategy Guide</div>
    </a>
    '''
    detail_html = '''
    <div class="workshopItemDescription">
      <div>S: Bash, Inflame</div>
      <div>Bash is incredibly powerful for Ironclad builds</div>
    </div>
    '''
    result = SourceResult(source_name="steam")
    names = {"bash", "inflame"}

    with patch("sts2.community.steam._fetch_url", side_effect=[index_html, detail_html]), \
         patch("sts2.community.steam.time.sleep"):
        _scrape_guides(names, result)

    assert len(result.meta_posts) >= 1
    assert result.meta_posts[0]["source"] == "steam_guide"


def test_steam_scrape_guides_network_error():
    """Guide scrape handles network errors gracefully."""
    import urllib.error

    from sts2.community.steam import _scrape_guides

    result = SourceResult(source_name="steam")
    with patch("sts2.community.steam._fetch_url", side_effect=urllib.error.URLError("timeout")):
        _scrape_guides({"bash"}, result)
    assert len(result.errors) == 1


def test_steam_scrape_discussions_full_flow():
    """Mock discussion index scrape."""
    from sts2.community.steam import _scrape_discussions

    html = '''
    <a class="forum_topic_overlay" href="https://steam.example/t/1">Best Ironclad strategy</a>
    <a class="forum_topic_overlay" href="https://steam.example/t/2">Bug report</a>
    <a class="forum_topic_overlay" href="https://steam.example/t/3">Deck building tips</a>
    '''
    result = SourceResult(source_name="steam")
    with patch("sts2.community.steam._fetch_url", return_value=html):
        _scrape_discussions({"bash"}, result)

    assert len(result.meta_posts) >= 2
    assert result.meta_posts[0]["source"] == "steam_discussion"


def test_steam_scrape_discussions_network_error():
    """Discussion scrape handles network errors gracefully."""
    import urllib.error

    from sts2.community.steam import _scrape_discussions

    result = SourceResult(source_name="steam")
    with patch("sts2.community.steam._fetch_url", side_effect=urllib.error.URLError("timeout")):
        _scrape_discussions({"bash"}, result)
    assert len(result.errors) == 1


def test_steam_scrape_top_level():
    """Top-level scrape() calls all sub-scrapers."""
    from sts2.community.steam import scrape

    with patch("sts2.community.steam._scrape_reviews") as mock_reviews, \
         patch("sts2.community.steam._scrape_guides") as mock_guides, \
         patch("sts2.community.steam._scrape_discussions") as mock_discussions, \
         patch("sts2.community.steam.time.sleep"):
        result = scrape({"bash"})

    mock_reviews.assert_called_once()
    mock_guides.assert_called_once()
    mock_discussions.assert_called_once()
    assert result.source_name == "steam"


# ── Reddit: mocked scrape ───────────────────────────────────────────────

def test_reddit_scrape_mocked():
    """Reddit scrape with mocked network returns SourceResult."""
    from sts2.community.reddit import scrape

    mock_posts_data = {
        "data": {
            "children": [
                {"data": {
                    "id": "abc123", "title": "STS2 tier list S: Bash A: Defend",
                    "selftext": "Bash is great. Necrobinder is fun.",
                    "score": 50, "num_comments": 10, "url": "", "permalink": "/r/slaythespire2/abc123",
                    "link_flair_text": "", "created_utc": 1700000000, "subreddit": "slaythespire2",
                }},
            ]
        }
    }

    with patch("sts2.community.reddit._fetch_reddit_json", return_value=mock_posts_data), \
         patch("sts2.community.reddit.time.sleep"):
        result = scrape({"bash", "defend"})

    assert result.source_name == "reddit"
    assert result.post_count > 0


def test_reddit_fetch_post_comments_mocked():
    """_fetch_post_comments returns comment bodies."""
    from sts2.community.reddit import _fetch_post_comments

    mock_data = [
        {"data": {"children": []}},
        {"data": {"children": [
            {"data": {"body": "Bash is incredibly strong against this boss"}},
            {"data": {"body": "short"}},  # too short, filtered
        ]}},
    ]
    with patch("sts2.community.reddit._fetch_reddit_json", return_value=mock_data):
        comments = _fetch_post_comments("/r/test/abc")
    assert len(comments) == 1
    assert "Bash" in comments[0]


def test_reddit_fetch_post_comments_error():
    """_fetch_post_comments returns empty list on error."""
    import urllib.error

    from sts2.community.reddit import _fetch_post_comments
    with patch("sts2.community.reddit._fetch_reddit_json", side_effect=urllib.error.URLError("fail")):
        assert _fetch_post_comments("/r/test/abc") == []


def test_reddit_fetch_subreddit_posts_error():
    """_fetch_subreddit_posts returns empty list on error."""
    import urllib.error

    from sts2.community.reddit import _fetch_subreddit_posts
    with patch("sts2.community.reddit._fetch_reddit_json", side_effect=urllib.error.URLError("fail")):
        assert _fetch_subreddit_posts("slaythespire") == []


# ── Extract functions edge cases ─────────────────────────────────────────

def test_extract_tier_ratings_no_matches():
    """extract_tier_ratings returns empty for text without tier patterns."""
    result = extract_tier_ratings("This is just regular text.", {"bash"})
    assert result == {}


def test_extract_tips_no_matches():
    """extract_tips returns empty for text without entity mentions."""
    result = extract_tips("This is some text about games.", {"bash"})
    assert result == {}


def test_extract_tips_too_short_sentence():
    """extract_tips skips sentences shorter than 20 chars."""
    result = extract_tips("Bash ok.", {"bash"})
    assert result == {}


def test_merge_tips_capped_at_five():
    """Merge should cap tips at 5 per entity."""
    r = SourceResult(source_name="test")
    r.tips["bash"] = [f"Tip number {i} about bash is really useful" for i in range(10)]
    merged = merge_results([r])
    assert len(merged["community_tips"]["bash"]) == 5


def test_merge_post_type_counts():
    """Merge correctly counts tier_list and strategy post types."""
    r = SourceResult(source_name="test")
    r.meta_posts = [
        {"title": "A", "score": 10, "type": "tier_list"},
        {"title": "B", "score": 5, "type": "strategy"},
        {"title": "C", "score": 3, "type": "strategy"},
    ]
    merged = merge_results([r])
    assert merged["tier_post_count"] == 1
    assert merged["strategy_post_count"] == 2
