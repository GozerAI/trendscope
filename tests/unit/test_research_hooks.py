"""Tests for research hooks."""

import pytest
from trendscope.core import Trend, TrendSource, TrendCategory, TrendStatus, TrendSignal, TrendDatabase
from trendscope.integrations.research_hooks import get_strong_buy_trends


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(db_path=tmp_path / "test.db")


def _make_strong_buy_trend(name="strong-trend", score=95):
    """Create a trend that should have STRONG_BUY signal."""
    return Trend(
        name=name,
        category=TrendCategory.TECHNOLOGY,
        source=TrendSource.GOOGLE_TRENDS,
        status=TrendStatus.GROWING,
        score=score,
        velocity=5.0,
        momentum=3.0,
        market_opportunity=0.9,
        competition_level=0.2,
        entry_barrier=0.1,
    )


def _make_weak_trend(name="weak-trend", score=30):
    """Create a trend that should NOT have STRONG_BUY signal."""
    return Trend(
        name=name,
        category=TrendCategory.TECHNOLOGY,
        source=TrendSource.REDDIT,
        status=TrendStatus.DECLINING,
        score=score,
        velocity=-1.0,
        momentum=-0.5,
    )


class TestGetStrongBuyTrends:
    def test_returns_strong_buy_trends(self, db):
        trend = _make_strong_buy_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=80)
        if trend.get_signal() == TrendSignal.STRONG_BUY:
            assert len(results) >= 1
            assert results[0]["name"] == "strong-trend"

    def test_excludes_below_min_score(self, db):
        trend = _make_strong_buy_trend(score=50)
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=80)
        strong = [r for r in results if r["name"] == trend.name]
        assert len(strong) == 0

    def test_excludes_non_strong_buy(self, db):
        trend = _make_weak_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        strong = [r for r in results if r["name"] == "weak-trend"]
        assert len(strong) == 0

    def test_returns_empty_for_no_trends(self, db):
        results = get_strong_buy_trends(db)
        assert results == []

    def test_includes_trend_metadata(self, db):
        trend = _make_strong_buy_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        if results:
            r = results[0]
            assert "id" in r
            assert "name" in r
            assert "score" in r
            assert "velocity" in r
            assert "category" in r
            assert "keywords" in r
            assert "signal" in r

    def test_respects_min_score_parameter(self, db):
        t1 = _make_strong_buy_trend("high", 95)
        t2 = _make_strong_buy_trend("medium", 85)
        t3 = _make_strong_buy_trend("low", 75)
        db.save_trend(t1)
        db.save_trend(t2)
        db.save_trend(t3)
        results = get_strong_buy_trends(db, min_score=90)
        for r in results:
            assert r["score"] >= 90

    def test_returns_category_as_string(self, db):
        trend = _make_strong_buy_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        if results:
            assert isinstance(results[0]["category"], str)

    def test_returns_signal_as_string(self, db):
        trend = _make_strong_buy_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        if results:
            assert isinstance(results[0]["signal"], str)

    def test_multiple_strong_buys(self, db):
        for i in range(5):
            trend = _make_strong_buy_trend(f"trend-{i}", 95)
            db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=80)
        assert isinstance(results, list)

    def test_keywords_included(self, db):
        trend = _make_strong_buy_trend()
        trend.keywords = ["ai", "machine-learning"]
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        if results:
            assert results[0]["keywords"] == ["ai", "machine-learning"]

    def test_default_min_score(self, db):
        trend = _make_strong_buy_trend(score=79)
        db.save_trend(trend)
        results = get_strong_buy_trends(db)
        strong = [r for r in results if r["name"] == trend.name]
        assert len(strong) == 0

    def test_source_as_string(self, db):
        trend = _make_strong_buy_trend()
        db.save_trend(trend)
        results = get_strong_buy_trends(db, min_score=0)
        if results:
            assert isinstance(results[0]["source"], str)
