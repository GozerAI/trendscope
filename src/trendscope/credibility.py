"""Source credibility weighting for trend analysis."""

from dataclasses import dataclass, field


# Per-source credibility weights (0.0-1.0)
SOURCE_WEIGHTS = {
    "GOOGLE_TRENDS": 0.9,
    "HACKER_NEWS": 0.85,
    "PRODUCT_HUNT": 0.8,
    "REDDIT": 0.65,
    "INTERNAL": 0.7,  # KH source
    "CUSTOM": 0.5,
    # Defaults for unlisted sources
}
DEFAULT_SOURCE_WEIGHT = 0.5

CONFIRMATION_KEYWORD_OVERLAP_THRESHOLD = 0.3
CONFIRMATION_BONUS_PER_SOURCE = 0.05
MAX_CONFIRMATION_BONUS = 0.25


class SourceCredibilityScorer:
    """Calculates credibility-weighted scores for trends."""

    def __init__(self, source_weights=None):
        self.source_weights = source_weights or SOURCE_WEIGHTS

    def get_source_weight(self, source_name):
        """Get credibility weight for a source."""
        return self.source_weights.get(source_name, DEFAULT_SOURCE_WEIGHT)

    def calculate_confirmation_count(self, trend, all_trends):
        """Count distinct sources that confirm this trend via keyword overlap > 30%."""
        if not trend.keywords:
            return 0, []

        trend_keywords = set(trend.keywords) if isinstance(trend.keywords, list) else set()
        if not trend_keywords:
            return 0, []

        confirming_sources = set()
        for other in all_trends:
            if other.id == trend.id:
                continue
            if other.source.name == trend.source.name:
                continue
            other_keywords = set(other.keywords) if isinstance(other.keywords, list) else set()
            if not other_keywords:
                continue
            union = trend_keywords | other_keywords
            if not union:
                continue
            overlap = len(trend_keywords & other_keywords) / len(union)
            if overlap >= CONFIRMATION_KEYWORD_OVERLAP_THRESHOLD:
                confirming_sources.add(other.source.name)

        return len(confirming_sources), list(confirming_sources)

    def apply_weighting(self, trend, all_trends):
        """Apply credibility weighting to a trend's score.

        Returns (weighted_score, confirmation_count, confirming_sources, confidence_multiplier).
        The weighted_score = original_score * source_weight * (1 + confirmation_bonus).
        """
        source_weight = self.get_source_weight(trend.source.name)
        count, sources = self.calculate_confirmation_count(trend, all_trends)
        confirmation_bonus = min(count * CONFIRMATION_BONUS_PER_SOURCE, MAX_CONFIRMATION_BONUS)
        confidence_multiplier = source_weight * (1.0 + confirmation_bonus)
        weighted_score = trend.score * confidence_multiplier
        return weighted_score, count, sources, confidence_multiplier
