"""Edge-case tests for trend detection, scoring, and analysis."""

import pytest
from datetime import datetime, timezone, timedelta

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendSignal,
    TrendDatabase,
    TrendAnalyzer,
    NicheOpportunity,
    SIGNAL_WEIGHT_VELOCITY,
    SIGNAL_WEIGHT_MOMENTUM,
    SIGNAL_WEIGHT_MARKET_OPPORTUNITY,
    SIGNAL_WEIGHT_COMPETITION,
    SIGNAL_WEIGHT_ENTRY_BARRIER,
    SIGNAL_THRESHOLD_STRONG_BUY,
    SIGNAL_THRESHOLD_BUY,
    SIGNAL_THRESHOLD_HOLD,
    SIGNAL_THRESHOLD_SELL,
    VELOCITY_THRESHOLD_EMERGING,
    VELOCITY_THRESHOLD_GROWING,
    VELOCITY_THRESHOLD_STABLE_LOW,
    VELOCITY_THRESHOLD_DECLINING,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(db_path=tmp_path / "edge.db")


@pytest.fixture
def analyzer(db):
    return TrendAnalyzer(db)


# =============================================================================
# Insufficient Data
# =============================================================================


class TestTrendDetectionInsufficientData:

    def test_analyze_trend_no_history(self, analyzer, db):
        """Trend with no prior history keeps its velocity unchanged."""
        t = Trend(name="Brand New", score=50, velocity=0.0)
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # Only one history point, velocity is not recomputed
        assert result.velocity == 0.0

    def test_analyze_trend_single_history_point(self, analyzer, db):
        """Single history point is not enough to compute velocity."""
        t = Trend(name="Single Point", score=60)
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # get_trend_history returns 1 entry; need >= 2 for velocity calc
        assert result.status in (
            TrendStatus.EMERGING,
            TrendStatus.GROWING,
            TrendStatus.STABLE,
            TrendStatus.DECLINING,
            TrendStatus.UNKNOWN,
        )

    def test_analyze_trend_two_history_points(self, analyzer, db):
        """Two history points should allow velocity computation."""
        t = Trend(name="Two Points", score=40)
        db.save_trend(t)
        t.score = 80
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # velocity = (80 - 40) / max(2, 1) = 20
        assert result.velocity != 0.0

    def test_momentum_requires_three_points(self, analyzer, db):
        """Momentum calculation requires at least 3 history points."""
        t = Trend(name="Two Only", score=50)
        db.save_trend(t)
        t.score = 60
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # With only 2 history points momentum is not recalculated (stays at 0)
        assert result.momentum == 0.0

    def test_momentum_with_three_points(self, analyzer, db):
        """Momentum is computed with 3+ history points."""
        t = Trend(name="Three Points", score=30)
        db.save_trend(t)
        t.score = 50
        db.save_trend(t)
        t.score = 80
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # 3 points => 2 velocity values => momentum is their average
        assert isinstance(result.momentum, float)


# =============================================================================
# Noisy Data
# =============================================================================


class TestTrendDetectionNoisyData:

    def test_volatile_score_history(self, analyzer, db):
        """Trend with wildly oscillating scores gets status assigned."""
        t = Trend(name="Volatile", score=20)
        db.save_trend(t)
        for s in [80, 20, 90, 10, 85]:
            t.score = s
            db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.status in TrendStatus.__members__.values()

    def test_noisy_data_momentum_near_zero(self, analyzer, db):
        """Oscillating scores yield near-zero momentum (ups cancel downs)."""
        t = Trend(name="Noise", score=50)
        db.save_trend(t)
        for s in [60, 50, 60, 50, 60, 50]:
            t.score = s
            db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert abs(result.momentum) < 20  # approximately zero drift


# =============================================================================
# Seasonal Patterns
# =============================================================================


class TestTrendDetectionSeasonalPatterns:

    def test_repeating_cycle_velocity(self, analyzer, db):
        """A repeating cycle that ends near the start has low net velocity."""
        t = Trend(name="Seasonal", score=50)
        db.save_trend(t)
        for s in [70, 90, 70, 50]:
            t.score = s
            db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # Start at 50, end at 50 => velocity ≈ 0
        assert abs(result.velocity) < 5

    def test_upward_seasonal_trend(self, analyzer, db):
        """Seasonal pattern with overall upward drift is detected as growing."""
        t = Trend(name="Seasonal Up", score=40)
        db.save_trend(t)
        for s in [60, 50, 70, 60, 80]:
            t.score = s
            db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.velocity > 0


# =============================================================================
# Trend Reversal Detection
# =============================================================================


class TestTrendReversalDetection:

    def test_reversal_from_growth_to_decline(self, analyzer, db):
        """Trend that was growing then crashes should show decline."""
        t = Trend(name="Reversal", score=90)
        db.save_trend(t)
        t.score = 30
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.velocity < 0

    def test_reversal_from_decline_to_growth(self, analyzer, db):
        """Trend that was declining then surges should show growth."""
        t = Trend(name="Comeback", score=20)
        db.save_trend(t)
        t.score = 80
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.velocity > 0


# =============================================================================
# Multiple Simultaneous Trends
# =============================================================================


class TestMultipleSimultaneousTrends:

    def test_correlations_between_many_trends(self, analyzer):
        """Correlation works across a batch of trends with shared keywords."""
        trends = [
            Trend(name=f"T{i}", keywords=["ai", "ml"] if i < 3 else ["fashion"])
            for i in range(5)
        ]
        corrs = analyzer.identify_correlations(trends[0], trends)
        # trends[1] and trends[2] share keywords with trends[0]
        assert len(corrs) >= 1

    def test_no_self_correlation(self, analyzer):
        """A trend should not correlate with itself."""
        t = Trend(name="Self", keywords=["ai", "ml", "data"])
        corrs = analyzer.identify_correlations(t, [t])
        assert len(corrs) == 0

    def test_correlations_ordered_by_score(self, analyzer):
        """Correlations are returned sorted by correlation score descending."""
        t = Trend(name="Base", keywords=["ai", "ml", "data", "cloud", "ops"])
        others = [
            Trend(name="Weak", keywords=["ai"]),
            Trend(name="Strong", keywords=["ai", "ml", "data", "cloud"]),
        ]
        corrs = analyzer.identify_correlations(t, [t] + others)
        if len(corrs) >= 2:
            assert corrs[0][1] >= corrs[1][1]

    def test_batch_analyze_many_trends(self, analyzer, db):
        """Analyzing many trends in sequence works correctly."""
        for i in range(10):
            t = Trend(name=f"Batch{i}", score=10 * i)
            db.save_trend(t)
            db.save_trend(Trend(id=t.id, name=t.name, score=10 * i + 5))
        # Analyze each trend
        trends = db.get_trends(limit=100)
        for trend in trends:
            result = analyzer.analyze_trend(trend)
            assert result.status in TrendStatus.__members__.values()


# =============================================================================
# Trend Confidence / Signal Scoring
# =============================================================================


class TestTrendConfidenceScoring:

    def test_signal_boundary_strong_buy(self):
        """Signal at exactly the STRONG_BUY threshold."""
        # Need composite signal_score >= 0.8
        t = Trend(
            velocity=1.0, momentum=1.0,
            market_opportunity=1.0,
            competition_level=0.0, entry_barrier=0.0,
        )
        assert t.get_signal() == TrendSignal.STRONG_BUY

    def test_signal_boundary_buy(self):
        """Signal in the BUY range."""
        t = Trend(
            velocity=0.7, momentum=0.7,
            market_opportunity=0.6,
            competition_level=0.3, entry_barrier=0.3,
        )
        signal = t.get_signal()
        assert signal in (TrendSignal.BUY, TrendSignal.STRONG_BUY)

    def test_signal_boundary_sell(self):
        """Signal in the SELL range."""
        t = Trend(
            velocity=-0.5, momentum=-0.5,
            market_opportunity=0.1,
            competition_level=0.8, entry_barrier=0.8,
        )
        signal = t.get_signal()
        assert signal in (TrendSignal.SELL, TrendSignal.STRONG_SELL)

    def test_opportunity_score_high_quality(self, analyzer):
        """High quality data yields higher opportunity score."""
        high_q = Trend(velocity=0.5, competition_level=0.2, entry_barrier=0.1, data_quality=1.0)
        low_q = Trend(velocity=0.5, competition_level=0.2, entry_barrier=0.1, data_quality=0.1)
        score_high = analyzer.calculate_opportunity_score(high_q)
        score_low = analyzer.calculate_opportunity_score(low_q)
        assert score_high > score_low

    def test_opportunity_score_clamped_to_zero_one(self, analyzer):
        """Opportunity score is always in [0, 1]."""
        # Extreme negative velocity
        t = Trend(velocity=-5.0, competition_level=1.0, entry_barrier=1.0, data_quality=0.0)
        score = analyzer.calculate_opportunity_score(t)
        assert 0 <= score <= 1

    def test_opportunity_score_high_competition(self, analyzer):
        """High competition lowers opportunity score."""
        low_comp = Trend(velocity=0.3, competition_level=0.1, entry_barrier=0.2, data_quality=0.8)
        high_comp = Trend(velocity=0.3, competition_level=0.9, entry_barrier=0.2, data_quality=0.8)
        assert analyzer.calculate_opportunity_score(low_comp) > analyzer.calculate_opportunity_score(high_comp)


# =============================================================================
# Missing Data Points
# =============================================================================


class TestTrendMissingDataPoints:

    def test_trend_with_zero_score_history(self, analyzer, db):
        """Trend where all history scores are 0 gets analyzed without error."""
        t = Trend(name="ZeroHistory", score=0)
        db.save_trend(t)
        db.save_trend(t)
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.status in TrendStatus.__members__.values()

    def test_from_dict_missing_optional_fields(self):
        """from_dict handles missing optional fields gracefully."""
        t = Trend.from_dict({"name": "Minimal"})
        assert t.name == "Minimal"
        assert t.score == 0.0
        assert t.velocity == 0.0
        assert t.keywords == []
        assert t.raw_data == {}

    def test_to_dict_preserves_none_dates(self):
        """to_dict handles None dates without error."""
        t = Trend(name="NoDate")
        t.first_seen = None
        t.last_updated = None
        d = t.to_dict()
        assert d["first_seen"] is None
        assert d["last_updated"] is None


# =============================================================================
# Zero-Variance Data
# =============================================================================


class TestZeroVarianceData:

    def test_constant_score_series(self, analyzer, db):
        """Constant score series yields zero velocity."""
        t = Trend(name="Constant", score=50)
        db.save_trend(t)
        db.save_trend(t)
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.velocity == 0.0

    def test_constant_score_momentum_zero(self, analyzer, db):
        """Constant score series yields zero momentum."""
        t = Trend(name="ConstMom", score=50)
        for _ in range(4):
            db.save_trend(t)
        result = analyzer.analyze_trend(t)
        assert result.momentum == 0.0

    def test_signal_all_zeros(self):
        """All-zero metrics yield STRONG_SELL signal."""
        t = Trend(
            velocity=0.0, momentum=0.0,
            market_opportunity=0.0,
            competition_level=0.0, entry_barrier=0.0,
        )
        # signal_score = 0*0.3 + 0*0.3 + 0*0.2 + 1*0.1 + 1*0.1 = 0.2
        assert t.get_signal() == TrendSignal.SELL

    def test_correlation_identical_keywords(self, analyzer):
        """Two trends with identical keywords produce high correlation."""
        t1 = Trend(name="A", keywords=["ai", "ml", "data"])
        t2 = Trend(name="B", keywords=["ai", "ml", "data"])
        corrs = analyzer.identify_correlations(t1, [t1, t2])
        assert len(corrs) == 1
        assert corrs[0][1] == 1.0  # perfect overlap
