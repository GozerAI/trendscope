"""Tests for source credibility weighting."""

import pytest

from trendscope.core import Trend, TrendSource, TrendCategory, TrendStatus
from trendscope.credibility import (
    SourceCredibilityScorer,
    SOURCE_WEIGHTS,
    DEFAULT_SOURCE_WEIGHT,
    CONFIRMATION_BONUS_PER_SOURCE,
    MAX_CONFIRMATION_BONUS,
)


@pytest.fixture
def scorer():
    return SourceCredibilityScorer()


# =============================================================================
# get_source_weight
# =============================================================================


class TestGetSourceWeight:

    def test_google_trends_weight(self, scorer):
        assert scorer.get_source_weight("GOOGLE_TRENDS") == 0.9

    def test_hacker_news_weight(self, scorer):
        assert scorer.get_source_weight("HACKER_NEWS") == 0.85

    def test_product_hunt_weight(self, scorer):
        assert scorer.get_source_weight("PRODUCT_HUNT") == 0.8

    def test_reddit_weight(self, scorer):
        assert scorer.get_source_weight("REDDIT") == 0.65

    def test_internal_weight(self, scorer):
        assert scorer.get_source_weight("INTERNAL") == 0.7

    def test_custom_weight(self, scorer):
        assert scorer.get_source_weight("CUSTOM") == 0.5

    def test_unknown_source_returns_default(self, scorer):
        assert scorer.get_source_weight("UNKNOWN_SRC") == DEFAULT_SOURCE_WEIGHT

    def test_custom_weights_override(self):
        custom = {"GOOGLE_TRENDS": 0.5, "REDDIT": 1.0}
        s = SourceCredibilityScorer(source_weights=custom)
        assert s.get_source_weight("GOOGLE_TRENDS") == 0.5
        assert s.get_source_weight("REDDIT") == 1.0
        # Unlisted still falls back to default
        assert s.get_source_weight("HACKER_NEWS") == DEFAULT_SOURCE_WEIGHT


# =============================================================================
# calculate_confirmation_count
# =============================================================================


class TestCalculateConfirmationCount:

    def test_no_overlap_returns_zero(self, scorer):
        t1 = Trend(id="t1", keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["cooking", "recipes"], source=TrendSource.REDDIT)
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 0
        assert sources == []

    def test_overlap_above_threshold(self, scorer):
        # Jaccard overlap: intersection=2, union=3 => 0.667 > 0.3
        t1 = Trend(id="t1", keywords=["ai", "ml", "deep"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["ai", "ml"], source=TrendSource.REDDIT)
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 1
        assert "REDDIT" in sources

    def test_overlap_at_boundary(self, scorer):
        # Exact boundary: overlap=0.3 should be included (>=)
        # We need intersection/union = 0.3 exactly
        # 3 shared out of 10 total union = 0.3
        t1 = Trend(id="t1", keywords=["a", "b", "c", "d", "e", "f", "g"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["a", "b", "c", "h", "i", "j", "k"], source=TrendSource.REDDIT)
        # intersection = {a,b,c} = 3, union = {a..k minus duplicates} = 10 => 3/10 = 0.3
        # Wait: t1 has 7 unique, t2 has 7 unique, overlap=3 => union = 7+7-3 = 11? No.
        # Let me recalculate: union = t1_set | t2_set
        # t1 = {a,b,c,d,e,f,g}, t2 = {a,b,c,h,i,j,k}
        # union = {a,b,c,d,e,f,g,h,i,j,k} = 11, intersection = {a,b,c} = 3
        # 3/11 = 0.2727 < 0.3 -- not enough
        # Need: intersection/union >= 0.3
        # Let's use: t1 = {a,b,c,d,e}, t2 = {a,b,c,f,g} => inter=3, union=7, 3/7=0.4286 > 0.3
        # Actually let's just pick values that give exactly 0.3:
        # inter=3, union=10 => need |t1|+|t2|-3 = 10 => |t1|+|t2| = 13
        # t1 = 7, t2 = 6: t1={a,b,c,d,e,f,g}, t2={a,b,c,h,i,j} => inter=3, union=10 => 0.3
        pass

    def test_overlap_at_exact_boundary(self, scorer):
        """Overlap of exactly 0.3 (>=) should confirm."""
        t1 = Trend(id="t1", keywords=["a", "b", "c", "d", "e", "f", "g"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["a", "b", "c", "h", "i", "j"], source=TrendSource.REDDIT)
        # intersection = {a,b,c} = 3, union = 10, ratio = 0.3 exactly
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 1

    def test_excludes_same_source_trends(self, scorer):
        t1 = Trend(id="t1", keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 0

    def test_empty_keywords_returns_zero(self, scorer):
        t1 = Trend(id="t1", keywords=[], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", keywords=["ai", "ml"], source=TrendSource.REDDIT)
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 0

    def test_no_other_trends(self, scorer):
        t1 = Trend(id="t1", keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        count, sources = scorer.calculate_confirmation_count(t1, [t1])
        assert count == 0
        assert sources == []


# =============================================================================
# apply_weighting
# =============================================================================


class TestApplyWeighting:

    def test_no_confirmation(self, scorer):
        t1 = Trend(id="t1", score=80.0, keywords=["ai"], source=TrendSource.GOOGLE_TRENDS)
        weighted, count, sources, multiplier = scorer.apply_weighting(t1, [t1])
        assert count == 0
        assert sources == []
        assert multiplier == 0.9  # Google Trends weight only
        assert weighted == pytest.approx(80.0 * 0.9)

    def test_single_confirmation(self, scorer):
        t1 = Trend(id="t1", score=80.0, keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", score=60.0, keywords=["ai", "ml"], source=TrendSource.REDDIT)
        weighted, count, sources, multiplier = scorer.apply_weighting(t1, [t1, t2])
        assert count == 1
        expected_multiplier = 0.9 * (1.0 + CONFIRMATION_BONUS_PER_SOURCE)
        assert multiplier == pytest.approx(expected_multiplier)
        assert weighted == pytest.approx(80.0 * expected_multiplier)

    def test_max_confirmation_bonus_cap(self, scorer):
        """Confirmation bonus should not exceed MAX_CONFIRMATION_BONUS."""
        trends = [Trend(id="t0", score=80.0, keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)]
        # Add 10 confirming sources (exceeds cap)
        extra_sources = [
            TrendSource.REDDIT, TrendSource.HACKER_NEWS, TrendSource.PRODUCT_HUNT,
            TrendSource.TWITTER, TrendSource.YOUTUBE, TrendSource.TIKTOK,
            TrendSource.NEWS, TrendSource.GITHUB, TrendSource.NPM, TrendSource.PYPI,
        ]
        for i, src in enumerate(extra_sources):
            trends.append(Trend(id=f"t{i+1}", keywords=["ai", "ml"], source=src))

        weighted, count, sources, multiplier = scorer.apply_weighting(trends[0], trends)
        expected_multiplier = 0.9 * (1.0 + MAX_CONFIRMATION_BONUS)
        assert multiplier == pytest.approx(expected_multiplier)
        assert count >= 5  # At least enough to hit the cap

    def test_high_credibility_source(self, scorer):
        t1 = Trend(id="t1", score=100.0, keywords=["x"], source=TrendSource.GOOGLE_TRENDS)
        weighted, _, _, multiplier = scorer.apply_weighting(t1, [t1])
        assert multiplier == 0.9
        assert weighted == pytest.approx(90.0)

    def test_low_credibility_source(self, scorer):
        t1 = Trend(id="t1", score=100.0, keywords=["x"], source=TrendSource.CUSTOM)
        weighted, _, _, multiplier = scorer.apply_weighting(t1, [t1])
        assert multiplier == 0.5
        assert weighted == pytest.approx(50.0)

    def test_preserves_zero_score(self, scorer):
        t1 = Trend(id="t1", score=0.0, keywords=["ai"], source=TrendSource.GOOGLE_TRENDS)
        weighted, _, _, _ = scorer.apply_weighting(t1, [t1])
        assert weighted == 0.0

    def test_end_to_end_multiple_sources(self, scorer):
        """Multiple trends from different sources with various overlaps."""
        t1 = Trend(id="t1", score=80.0, keywords=["ai", "ml", "deep"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(id="t2", score=60.0, keywords=["ai", "ml"], source=TrendSource.REDDIT)
        t3 = Trend(id="t3", score=70.0, keywords=["ai", "ml", "nlp"], source=TrendSource.HACKER_NEWS)
        t4 = Trend(id="t4", score=50.0, keywords=["cooking", "recipes"], source=TrendSource.PRODUCT_HUNT)

        all_trends = [t1, t2, t3, t4]

        # t1 should be confirmed by REDDIT and HACKER_NEWS (keyword overlap)
        w1, c1, s1, m1 = scorer.apply_weighting(t1, all_trends)
        assert c1 == 2  # REDDIT and HACKER_NEWS confirm
        assert "REDDIT" in s1
        assert "HACKER_NEWS" in s1
        assert w1 > 80.0 * 0.9  # Higher than base weight due to confirmation

        # t4 should have no confirmations
        w4, c4, s4, m4 = scorer.apply_weighting(t4, all_trends)
        assert c4 == 0
        assert m4 == 0.8  # PRODUCT_HUNT weight
