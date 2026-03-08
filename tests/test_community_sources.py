"""Tests for multi-source community scraper (Steam + merge logic)."""
import json
from collections import defaultdict
from unittest.mock import patch, MagicMock

import pytest

from sts2.community._types import SourceResult, extract_tier_ratings, extract_tips, compute_consensus_tier
from sts2.community._merge import merge_results


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
    from sts2.community.steam import _scrape_reviews
    import urllib.error

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
    from sts2.community import _compute_consensus_tier
    from sts2.community import _extract_tier_ratings
    from sts2.community import _extract_tips
    from sts2.community import _is_sts2_post
    from sts2.community import run_community_scraper
    from sts2.community import save_community_data
    from sts2.community import apply_community_tiers
    from sts2.community import _load_cached_community_data

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
