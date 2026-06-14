"""Unit tests for Trendscope intelligence module."""

import pytest
from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendDatabase,
    NicheOpportunity,
)
from trendscope.intelligence import (
    TrendCorrelation,
    TrendDrift,
    TrendDriftDetector,
    OpportunityScorer,
    TrendIntelligenceManager,
)


# =============================================================================
# Data model tests
# =============================================================================


class TestTrendCorrelation:

    def test_to_dict(self):
        c = TrendCorrelation(
            trend_a_id="a1",
            trend_b_id="b2",
            correlation_score=0.85,
            shared_keywords=["ai", "ml"],
        )
        d = c.to_dict()
        assert d["trend_a_id"] == "a1"
        assert d["correlation_score"] == 0.85
        assert "ai" in d["shared_keywords"]


class TestTrendDrift:

    def test_to_dict(self):
        d = TrendDrift(
            trend_id="t1",
            trend_name="AI Agents",
            drift_type="surge",
            magnitude=0.45,
        )
        result = d.to_dict()
        assert result["drift_type"] == "surge"
        assert result["magnitude"] == 0.45
        assert "detected_at" in result


# =============================================================================
# TrendDriftDetector
# =============================================================================


class TestTrendDriftDetector:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "drift.db")

    @pytest.fixture
    def detector(self, db):
        return TrendDriftDetector(db)

    def test_no_drifts_on_empty_db(self, detector):
        drifts = detector.detect_drifts()
        assert drifts == []

    def test_detects_surge(self, detector, db):
        t = Trend(name="Surging", score=30)
        db.save_trend(t)
        t.score = 60
        db.save_trend(t)
        t.score = 100
        db.save_trend(t)
        drifts = detector.detect_drifts(min_magnitude=0.1)
        # Should detect surge from 30 -> 100
        surge_drifts = [d for d in drifts if d.drift_type == "surge"]
        assert len(surge_drifts) >= 1

    def test_detects_decline(self, detector, db):
        t = Trend(name="Declining", score=90)
        db.save_trend(t)
        t.score = 50
        db.save_trend(t)
        t.score = 30
        db.save_trend(t)
        drifts = detector.detect_drifts(min_magnitude=0.1)
        decline_drifts = [d for d in drifts if d.drift_type == "decline"]
        assert len(decline_drifts) >= 1

    def test_no_drift_for_stable(self, detector, db):
        t = Trend(name="Stable", score=50)
        db.save_trend(t)
        t.score = 51
        db.save_trend(t)
        drifts = detector.detect_drifts(min_magnitude=0.2)
        assert len(drifts) == 0


# =============================================================================
# OpportunityScorer
# =============================================================================


class TestOpportunityScorer:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "opp.db")

    @pytest.fixture
    def scorer(self, db):
        return OpportunityScorer(db)

    def test_score_with_parent_trends(self, scorer, db):
        t1 = Trend(name="T1", score=80, velocity=0.5)
        t2 = Trend(name="T2", score=70, velocity=0.3)
        db.save_trend(t1)
        db.save_trend(t2)

        niche = NicheOpportunity(
            name="Test",
            parent_trend_ids=[t1.id, t2.id],
            competition_density=0.3,
            storefront_fit=["tech_gadgets"],
            growth_rate=20,
        )
        score = scorer.score_opportunity(niche)
        assert 0 <= score <= 100

    def test_score_without_parent_trends(self, scorer):
        niche = NicheOpportunity(name="Orphan", parent_trend_ids=[])
        score = scorer.score_opportunity(niche)
        assert 0 <= score <= 100

    def test_rank_opportunities(self, scorer, db):
        t = Trend(name="T", score=80, velocity=0.5)
        db.save_trend(t)

        n1 = NicheOpportunity(name="High", parent_trend_ids=[t.id], competition_density=0.1, storefront_fit=["a", "b", "c"])
        n2 = NicheOpportunity(name="Low", parent_trend_ids=[], competition_density=0.9, storefront_fit=[])

        ranked = scorer.rank_opportunities([n1, n2])
        assert len(ranked) == 2
        assert ranked[0][1] >= ranked[1][1]


# =============================================================================
# TrendIntelligenceManager
# =============================================================================


class TestTrendIntelligenceManager:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "intel.db")

    @pytest.fixture
    def manager(self, db):
        return TrendIntelligenceManager(db)

    def test_find_correlations_empty(self, manager):
        corrs = manager.find_correlations([])
        assert corrs == []

    def test_find_correlations_with_overlap(self, manager):
        t1 = Trend(name="A", keywords=["ai", "ml", "data"], category=TrendCategory.TECHNOLOGY)
        t2 = Trend(name="B", keywords=["ai", "ml", "cloud"], category=TrendCategory.TECHNOLOGY)
        corrs = manager.find_correlations([t1, t2], min_correlation=0.1)
        assert len(corrs) == 1
        assert corrs[0].correlation_score > 0

    def test_find_correlations_no_overlap(self, manager):
        t1 = Trend(name="A", keywords=["ai"])
        t2 = Trend(name="B", keywords=["fashion"])
        corrs = manager.find_correlations([t1, t2], min_correlation=0.5)
        assert len(corrs) == 0

    def test_get_trend_signals_empty(self, manager):
        signals = manager.get_trend_signals()
        for key in ("strong_buy", "buy", "hold", "sell", "strong_sell"):
            assert key in signals
            assert signals[key] == []

    def test_analyze_all_empty(self, manager):
        result = manager.analyze_all()
        assert result["analyzed_trends"] == 0
        assert result["correlations_found"] == 0

    def test_analyze_all_with_data(self, manager, db):
        for i in range(3):
            db.save_trend(Trend(name=f"T{i}", score=50 + i * 10, keywords=["ai"]))
        result = manager.analyze_all()
        assert result["analyzed_trends"] == 3
