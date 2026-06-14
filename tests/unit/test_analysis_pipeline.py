"""Tests for the analysis pipeline: intelligence manager, drift detection,
opportunity scoring, credibility weighting, anomaly detection, and forecasting."""

import pytest
from unittest.mock import patch, MagicMock

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendSignal,
    TrendDatabase,
    TrendAnalyzer,
    NicheOpportunity,
)
from trendscope.intelligence import (
    TrendCorrelation,
    TrendDrift,
    TrendDriftDetector,
    OpportunityScorer,
    TrendIntelligenceManager,
)
from trendscope.anomaly import (
    AnomalyDetector,
    AnomalyResult,
    zscore_detect,
    iqr_detect,
    moving_average_detect,
    composite_anomaly_score,
    classify_severity,
    mean,
    std_dev,
)
from trendscope.credibility import SourceCredibilityScorer
from trendscope.forecasting import TrendForecaster


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(db_path=tmp_path / "pipeline.db")


@pytest.fixture
def intelligence(db):
    return TrendIntelligenceManager(db)


@pytest.fixture
def forecaster(db):
    return TrendForecaster(db)


# =============================================================================
# Pipeline Stage Execution Order
# =============================================================================


class TestPipelineStageExecution:

    def test_analyze_all_runs_analysis_then_credibility(self, intelligence, db):
        """analyze_all analyzes trends and then applies credibility weighting."""
        t1 = Trend(name="T1", score=80, keywords=["ai"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="T2", score=70, keywords=["ai"], source=TrendSource.REDDIT)
        db.save_trend(t1)
        db.save_trend(t2)
        result = intelligence.analyze_all()
        assert result["analyzed_trends"] == 2
        # After analysis, trends should have confidence_multiplier applied
        updated = db.get_trend(t1.id)
        assert updated.confidence_multiplier > 0

    def test_analyze_all_returns_correlation_count(self, intelligence, db):
        """analyze_all returns count of discovered correlations."""
        t1 = Trend(name="A", score=80, keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="B", score=70, keywords=["ai", "ml"], source=TrendSource.REDDIT)
        db.save_trend(t1)
        db.save_trend(t2)
        result = intelligence.analyze_all()
        assert "correlations_found" in result
        assert isinstance(result["correlations_found"], int)

    def test_analyze_all_returns_drift_count(self, intelligence, db):
        """analyze_all reports detected drifts."""
        t = Trend(name="Surging", score=20)
        db.save_trend(t)
        t.score = 80
        db.save_trend(t)
        t.score = 100
        db.save_trend(t)
        result = intelligence.analyze_all()
        assert "drifts_detected" in result

    def test_generate_intelligence_report_structure(self, intelligence, db):
        """Full intelligence report has all required sections."""
        db.save_trend(Trend(name="T", score=60, keywords=["ai"]))
        report = intelligence.generate_intelligence_report()
        assert "report_id" in report
        assert "generated_at" in report
        assert "summary" in report
        assert "signals" in report
        assert "top_opportunities" in report
        assert "alerts" in report
        assert "recommendations" in report
        assert "forecast_summary" in report


# =============================================================================
# Pipeline with Failing Stage
# =============================================================================


class TestPipelineFailingStage:

    def test_analyze_all_survives_empty_db(self, intelligence):
        """analyze_all works on an empty database."""
        result = intelligence.analyze_all()
        assert result["analyzed_trends"] == 0
        assert result["correlations_found"] == 0
        assert result["drifts_detected"] == 0

    def test_drift_detector_no_history(self, db):
        """Drift detector handles trends with no history gracefully."""
        detector = TrendDriftDetector(db)
        t = Trend(name="NoHistory", score=50)
        db.save_trend(t)
        drifts = detector.detect_drifts()
        # One history point is not enough
        assert len(drifts) == 0

    def test_drift_detector_zero_first_score(self, db):
        """Drift detector handles zero first score (avoid division by zero)."""
        detector = TrendDriftDetector(db)
        t = Trend(name="ZeroStart", score=0)
        db.save_trend(t)
        t.score = 50
        db.save_trend(t)
        drifts = detector.detect_drifts(min_magnitude=0.1)
        # first_score == 0 => _analyze_drift returns None
        assert len(drifts) == 0

    def test_forecaster_insufficient_history(self, forecaster, db):
        """Forecaster returns None when history is too short."""
        t = Trend(name="Short", score=50)
        db.save_trend(t)
        result = forecaster.forecast_trend(t.id)
        assert result is None

    def test_forecaster_nonexistent_trend(self, forecaster):
        """Forecaster returns None for a trend ID not in DB."""
        result = forecaster.forecast_trend("nonexistent-id")
        assert result is None


# =============================================================================
# Pipeline Stage Skip on Condition
# =============================================================================


class TestPipelineSkipCondition:

    def test_find_correlations_skips_below_threshold(self, intelligence):
        """Correlations below min_correlation are excluded."""
        t1 = Trend(name="A", keywords=["unique1"])
        t2 = Trend(name="B", keywords=["unique2"])
        corrs = intelligence.find_correlations([t1, t2], min_correlation=0.9)
        assert len(corrs) == 0

    def test_drift_detector_skips_below_min_magnitude(self, db):
        """Drifts below min_magnitude are excluded."""
        detector = TrendDriftDetector(db)
        t = Trend(name="SmallDrift", score=50)
        db.save_trend(t)
        t.score = 55
        db.save_trend(t)
        drifts = detector.detect_drifts(min_magnitude=0.5)
        assert len(drifts) == 0

    def test_opportunity_scorer_no_parent_trends(self, db):
        """Scorer uses defaults when parent trends don't exist in DB."""
        scorer = OpportunityScorer(db)
        niche = NicheOpportunity(
            name="Orphan",
            parent_trend_ids=["nonexistent-1", "nonexistent-2"],
        )
        score = scorer.score_opportunity(niche)
        assert 0 <= score <= 100


# =============================================================================
# Pipeline Result Aggregation
# =============================================================================


class TestPipelineResultAggregation:

    def test_get_trend_signals_categorized(self, intelligence, db):
        """Signals are categorized into buy/sell/hold buckets."""
        # Strong buy: high velocity + momentum + opportunity, low competition
        db.save_trend(Trend(
            name="Hot", score=90, velocity=0.9, momentum=0.9,
            market_opportunity=0.9, competition_level=0.1, entry_barrier=0.1,
        ))
        # Strong sell: negative velocity + momentum
        db.save_trend(Trend(
            name="Cold", score=10, velocity=-0.9, momentum=-0.9,
            market_opportunity=0.0, competition_level=0.9, entry_barrier=0.9,
        ))
        signals = intelligence.get_trend_signals()
        total = sum(len(v) for v in signals.values())
        assert total == 2

    def test_rank_opportunities_sorted_descending(self, db):
        """rank_opportunities returns niches sorted by score descending."""
        scorer = OpportunityScorer(db)
        n1 = NicheOpportunity(name="A", competition_density=0.1, storefront_fit=["a", "b", "c"])
        n2 = NicheOpportunity(name="B", competition_density=0.9, storefront_fit=[])
        ranked = scorer.rank_opportunities([n1, n2])
        assert ranked[0][1] >= ranked[1][1]

    def test_rank_opportunities_includes_breakdown(self, db):
        """Each ranked opportunity includes a score breakdown dict."""
        scorer = OpportunityScorer(db)
        niche = NicheOpportunity(name="Test")
        ranked = scorer.rank_opportunities([niche])
        assert len(ranked) == 1
        _, score, breakdown = ranked[0]
        assert "competition_level" in breakdown
        assert "growth_rate" in breakdown


# =============================================================================
# Pipeline Timeout / Edge Case Handling
# =============================================================================


class TestPipelineTimeoutHandling:

    def test_anomaly_detect_all_empty_db(self, db):
        """Anomaly detector on empty DB returns empty list."""
        detector = AnomalyDetector(db)
        results = detector.detect_all()
        assert results == []

    def test_anomaly_detect_for_trend_insufficient_history(self, db):
        """Anomaly detector with insufficient history returns empty."""
        detector = AnomalyDetector(db)
        t = Trend(name="Short", score=50)
        db.save_trend(t)
        results = detector.detect_for_trend(t.id, t.name)
        assert results == []

    def test_anomaly_detect_with_spike(self, db):
        """Anomaly detector finds an extreme spike."""
        detector = AnomalyDetector(db)
        t = Trend(name="Spike", score=50)
        for s in [50, 51, 49, 50, 52, 48, 50, 200]:
            t.score = s
            db.save_trend(t)
        results = detector.detect_for_trend(t.id, t.name)
        # The spike at 200 should be flagged
        assert len(results) >= 1
        assert any(r.value == 200 for r in results)

    def test_zscore_detect_short_series(self):
        """zscore_detect requires at least 3 data points."""
        assert zscore_detect([1, 2]) == []
        assert zscore_detect([]) == []

    def test_iqr_detect_short_series(self):
        """iqr_detect requires at least 4 data points."""
        assert iqr_detect([1, 2, 3]) == []

    def test_moving_average_detect_short_series(self):
        """moving_average_detect needs more than window+1 points."""
        assert moving_average_detect([1, 2, 3, 4, 5]) == []  # window=5, needs 6

    def test_classify_severity_levels(self):
        assert classify_severity(1.0) == "critical"
        assert classify_severity(0.67) == "high"
        assert classify_severity(0.34) == "medium"
        assert classify_severity(0.1) == "low"


# =============================================================================
# Pipeline with No Data
# =============================================================================


class TestPipelineNoData:

    def test_signals_empty_db(self, intelligence):
        signals = intelligence.get_trend_signals()
        for key in ("strong_buy", "buy", "hold", "sell", "strong_sell"):
            assert signals[key] == []

    def test_correlations_empty_list(self, intelligence):
        corrs = intelligence.find_correlations([])
        assert corrs == []

    def test_recommendations_empty_signals(self, intelligence):
        """Recommendations handle empty signal lists gracefully."""
        signals = {"strong_buy": [], "buy": [], "hold": [], "sell": [], "strong_sell": []}
        recs = intelligence._generate_recommendations(signals, [])
        # Should get diversification recommendation since < 3 categories
        assert any("DIVERSIFICATION" in r for r in recs)

    def test_mean_empty_list(self):
        assert mean([]) == 0.0

    def test_std_dev_single_element(self):
        assert std_dev([5.0]) == 0.0


# =============================================================================
# Pipeline Metrics Collection
# =============================================================================


class TestPipelineMetrics:

    def test_credibility_scorer_source_weights(self):
        scorer = SourceCredibilityScorer()
        assert scorer.get_source_weight("GOOGLE_TRENDS") == 0.9
        assert scorer.get_source_weight("REDDIT") == 0.65
        assert scorer.get_source_weight("UNKNOWN_SOURCE") == 0.5

    def test_credibility_confirmation_count(self):
        """Two trends from different sources with keyword overlap are confirmations."""
        scorer = SourceCredibilityScorer()
        t1 = Trend(name="A", keywords=["ai", "ml"], source=TrendSource.GOOGLE_TRENDS)
        t2 = Trend(name="B", keywords=["ai", "ml"], source=TrendSource.REDDIT)
        count, sources = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count >= 1
        assert "REDDIT" in sources

    def test_credibility_no_self_confirmation(self):
        """A trend does not confirm itself."""
        scorer = SourceCredibilityScorer()
        t = Trend(name="Self", keywords=["ai"], source=TrendSource.GOOGLE_TRENDS)
        count, _ = scorer.calculate_confirmation_count(t, [t])
        assert count == 0

    def test_credibility_same_source_no_confirmation(self):
        """Two trends from the same source don't count as confirmation."""
        scorer = SourceCredibilityScorer()
        t1 = Trend(name="A", keywords=["ai", "ml"], source=TrendSource.REDDIT)
        t2 = Trend(name="B", keywords=["ai", "ml"], source=TrendSource.REDDIT)
        count, _ = scorer.calculate_confirmation_count(t1, [t1, t2])
        assert count == 0

    def test_credibility_apply_weighting(self):
        """apply_weighting returns correct tuple structure."""
        scorer = SourceCredibilityScorer()
        t = Trend(name="T", score=80, keywords=["ai"], source=TrendSource.GOOGLE_TRENDS)
        weighted_score, count, sources, multiplier = scorer.apply_weighting(t, [t])
        assert weighted_score == 80 * multiplier
        assert isinstance(count, int)
        assert isinstance(sources, list)
        assert multiplier > 0

    def test_forecaster_holt_linear_single_point(self, forecaster):
        """Holt linear with single data point returns level = that point, trend = 0."""
        smoothed, level, trend = forecaster.holt_linear([50.0])
        assert smoothed == [50.0]
        assert level == 50.0
        assert trend == 0.0

    def test_forecaster_holt_linear_empty(self, forecaster):
        """Holt linear with empty series returns empty."""
        smoothed, level, trend = forecaster.holt_linear([])
        assert smoothed == []
        assert level == 0.0
        assert trend == 0.0

    def test_forecaster_ses_empty(self, forecaster):
        assert forecaster.exponential_smoothing([]) == []

    def test_forecaster_ses_single(self, forecaster):
        result = forecaster.exponential_smoothing([42.0])
        assert result == [42.0]

    def test_forecaster_confidence_interval_empty(self, forecaster):
        assert forecaster.calculate_confidence_interval([], 7) == 0.0

    def test_forecaster_full_forecast(self, db, forecaster):
        """Full forecast returns expected structure."""
        t = Trend(name="Forecast Me", score=50)
        for s in [50, 55, 60, 65, 70]:
            t.score = s
            db.save_trend(t)
        result = forecaster.forecast_trend(t.id)
        assert result is not None
        assert "trend_id" in result
        assert "direction" in result
        assert "forecasts" in result
        assert "7d" in result["forecasts"]
        assert "30d" in result["forecasts"]

    def test_composite_anomaly_score_no_anomaly(self):
        """Uniform series has no anomalies."""
        scores = composite_anomaly_score([50, 50, 50, 50, 50, 50, 50])
        assert len(scores) == 0
