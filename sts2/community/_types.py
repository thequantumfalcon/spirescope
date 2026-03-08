"""Shared types, constants, and extraction functions for community scrapers."""
import re
from collections import defaultdict
from dataclasses import dataclass, field

# Keywords that indicate tier list or strategy content
TIER_KEYWORDS = re.compile(
    r"tier\s*list|card\s*ranking|best\s*cards|worst\s*cards|"
    r"s[\s-]*tier|a[\s-]*tier|card\s*tier|relic\s*tier|"
    r"relic\s*ranking|best\s*relics|worst\s*relics|"
    r"meta\s*report|win\s*rate|power\s*ranking",
    re.IGNORECASE,
)
STRATEGY_KEYWORDS = re.compile(
    r"strategy|guide|tips|how\s*to|deck\s*building|archetype|"
    r"synergy|combo|build\s*guide|new\s*player|beginner|advanced|"
    r"ironclad|silent|defect|necrobinder|regent",
    re.IGNORECASE,
)

# Standard tier labels
TIER_LABELS = {"s", "a", "b", "c", "d", "f"}
TIER_PATTERN = re.compile(
    r"(?:^|\n)\s*\*?\*?\[?\s*([SABCDF])\s*[\]\-:)]*\s*(?:tier)?[\s:\-]*(.+?)(?:\n|$)",
    re.IGNORECASE | re.MULTILINE,
)

# STS2 content indicators
STS2_INDICATORS = re.compile(
    r"slay\s*the\s*spire\s*2|sts\s*2|spire\s*2|sts2|"
    r"necrobinder|regent|early\s*access",
    re.IGNORECASE,
)

USER_AGENT = "Spirescope/2.0 (community data collector)"
REQUEST_DELAY = 2.0  # seconds between requests (respect rate limits)


@dataclass
class SourceResult:
    """Uniform output from any community source scraper."""
    source_name: str
    tier_votes: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    tips: dict[str, list[str]] = field(default_factory=lambda: defaultdict(list))
    meta_posts: list[dict] = field(default_factory=list)
    post_count: int = 0
    errors: list[str] = field(default_factory=list)


def extract_tier_ratings(text: str, existing_names: set[str]) -> dict[str, list[str]]:
    """Extract tier ratings from text.

    Returns {card_or_relic_name_lower: [tier_label, ...]} for each mention.
    """
    ratings: dict[str, list[str]] = defaultdict(list)
    for match in TIER_PATTERN.finditer(text):
        tier = match.group(1).upper()
        items_text = match.group(2).strip()
        items = re.split(r"[,/•|]+", items_text)
        for item in items:
            name = item.strip().strip("*_[]()").strip()
            if len(name) < 2 or len(name) > 50:
                continue
            name_lower = name.lower()
            if name_lower in existing_names:
                ratings[name_lower].append(tier)
    return ratings


def extract_tips(text: str, entity_names: set[str]) -> dict[str, list[str]]:
    """Extract strategy tips mentioning specific cards/relics."""
    tips: dict[str, list[str]] = defaultdict(list)
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


def compute_consensus_tier(tier_votes: list[str]) -> str:
    """Determine consensus tier from multiple community votes."""
    if not tier_votes:
        return ""
    tier_order = {"S": 5, "A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
    total_score = sum(tier_order.get(t, 2) for t in tier_votes)
    avg = total_score / len(tier_votes)
    reverse_order = {5: "S", 4: "A", 3: "B", 2: "C", 1: "D", 0: "F"}
    return reverse_order.get(round(avg), "B")
