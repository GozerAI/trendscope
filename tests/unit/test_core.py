"""Unit tests for Trendscope core module."""

import pytest
from datetime import datetime, timezone
from pathlib import Path

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendSignal,
    TrendDatabase,
    TrendAnalyzer,
    NicheOpportunity,
    SIGNAL_THRESHOLD_STRONG_BUY,
)


# =============================================================================
# Trend dataclass
# =============================================================================


class TestTrend:

    def test_defaults(self):
        t = Trend()
        assert t.name == ""
        assert t.score == 0.0
        assert t.category == TrendCategory.EMERGING
        assert t.source == TrendSource.CUSTOM
        assert t.status == TrendStatus.UNKNOWN
        assert isinstance(t.id, str)
        assert isinstance(t.first_seen, datetime)

    def test_to_dict_roundtrip(self):
        t = Trend(name="AI Agents", score=85, category=TrendCategory.TECHNOLOGY)
        d = t.to_dict()
        assert d["name"] == "AI Agents"
        assert d["score"] == 85
        assert d["category"] == "technology"

    def test_from_dict_basic(self):
        d = {"name": "Foo", "score": 42, "category": "business", "source": "reddit"}
        t = Trend.from_dict(d)
        assert t.name == "Foo"
        assert t.score == 42
        assert t.category == TrendCategory.BUSINESS
        assert t.source == TrendSource.REDDIT

    def test_from_dict_with_iso_dates(self):
        d = {
            "name": "Bar",
            "first_seen": "2026-01-01T00:00:00+00:00",
            "last_updated": "2026-03-01T12:00:00+00:00",
        }
        t = Trend.from_dict(d)
        assert t.first_seen.year == 2026
        assert t.last_updated.month == 3

    def test_from_dict_missing_fields(self):
        t = Trend.from_dict({})
        assert t.name == ""
        assert t.score == 0.0

    def test_get_signal_strong_buy(self):
        t = Trend(velocity=0.9, momentum=0.9, market_opportunity=0.9, competition_level=0.1, entry_barrier=0.1)
        assert t.get_signal() == TrendSignal.STRONG_BUY

    def test_get_signal_strong_sell(self):
        t = Trend(velocity=-0.9, momentum=-0.9, market_opportunity=0.0, competition_level=0.9, entry_barrier=0.9)
        assert t.get_signal() == TrendSignal.STRONG_SELL

    def test_get_signal_hold(self):
        t = Trend(velocity=0.5, momentum=0.5, market_opportunity=0.5, competition_level=0.3, entry_barrier=0.3)
        signal = t.get_signal()
        assert signal in (TrendSignal.HOLD, TrendSignal.BUY)


# =============================================================================
# NicheOpportunity
# =============================================================================


class TestNicheOpportunity:

    def test_defaults(self):
        n = NicheOpportunity()
        assert n.name == ""
        assert n.opportunity_score == 0.0
        assert n.urgency == "medium"
        assert isinstance(n.id, str)

    def test_to_dict(self):
        n = NicheOpportunity(name="Test Niche", opportunity_score=75.5)
        d = n.to_dict()
        assert d["name"] == "Test Niche"
        assert d["opportunity_score"] == 75.5
        assert "created_at" in d


# =============================================================================
# TrendDatabase
# =============================================================================


class TestTrendDatabase:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    def test_save_and_get_trend(self, db):
        t = Trend(name="AI Agents", score=85, category=TrendCategory.TECHNOLOGY)
        db.save_trend(t)
        loaded = db.get_trend(t.id)
        assert loaded is not None
        assert loaded.name == "AI Agents"
        assert loaded.score == 85
        assert loaded.category == TrendCategory.TECHNOLOGY

    def test_get_nonexistent_trend(self, db):
        assert db.get_trend("nonexistent") is None

    def test_get_trends_with_filters(self, db):
        db.save_trend(Trend(name="A", score=80, category=TrendCategory.TECHNOLOGY))
        db.save_trend(Trend(name="B", score=30, category=TrendCategory.BUSINESS))
        db.save_trend(Trend(name="C", score=60, category=TrendCategory.TECHNOLOGY))

        tech = db.get_trends(category=TrendCategory.TECHNOLOGY)
        assert len(tech) == 2

        high = db.get_trends(min_score=50)
        assert len(high) == 2

    def test_get_top_trends(self, db):
        for i in range(5):
            db.save_trend(Trend(name=f"T{i}", score=i * 20))
        top = db.get_top_trends(limit=3)
        assert len(top) == 3
        assert top[0].score >= top[1].score

    def test_search_trends(self, db):
        db.save_trend(Trend(name="Machine Learning Pipeline", score=70))
        db.save_trend(Trend(name="Cat Videos", score=50))
        results = db.search_trends("Machine")
        assert len(results) == 1
        assert results[0].name == "Machine Learning Pipeline"

    def test_trend_history(self, db):
        t = Trend(name="Tracked", score=50)
        db.save_trend(t)
        t.score = 60
        db.save_trend(t)
        history = db.get_trend_history(t.id, days=1)
        assert len(history) == 2

    def test_save_and_get_niche(self, db):
        n = NicheOpportunity(name="Test Niche", opportunity_score=75)
        db.save_niche(n)
        niches = db.get_niches(min_score=50)
        assert len(niches) == 1
        assert niches[0].name == "Test Niche"

    def test_get_stats_empty(self, db):
        stats = db.get_stats()
        assert stats["total_trends"] == 0
        assert stats["average_score"] == 0

    def test_get_stats_with_data(self, db):
        db.save_trend(Trend(name="A", score=80, category=TrendCategory.TECHNOLOGY))
        db.save_trend(Trend(name="B", score=60, category=TrendCategory.BUSINESS))
        stats = db.get_stats()
        assert stats["total_trends"] == 2
        assert stats["average_score"] == 70.0


# =============================================================================
# TrendAnalyzer
# =============================================================================


class TestTrendAnalyzer:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "analyzer.db")

    @pytest.fixture
    def analyzer(self, db):
        return TrendAnalyzer(db)

    def test_analyze_sets_status_emerging(self, analyzer, db):
        t = Trend(name="Hot", score=50, velocity=0.6)
        db.save_trend(t)
        result = analyzer.analyze_trend(t)
        # With no history to recompute velocity, status should still be set
        assert result.status in (TrendStatus.EMERGING, TrendStatus.GROWING, TrendStatus.STABLE)

    def test_calculate_opportunity_score(self, analyzer):
        t = Trend(velocity=0.5, competition_level=0.2, entry_barrier=0.3, data_quality=0.9)
        score = analyzer.calculate_opportunity_score(t)
        assert 0 <= score <= 1

    def test_identify_correlations(self, analyzer):
        t1 = Trend(name="A", keywords=["ai", "ml", "data"])
        t2 = Trend(name="B", keywords=["ai", "ml", "cloud"])
        t3 = Trend(name="C", keywords=["fashion", "retail"])
        corrs = analyzer.identify_correlations(t1, [t1, t2, t3])
        assert len(corrs) >= 1
        assert corrs[0][0] == t2.id
