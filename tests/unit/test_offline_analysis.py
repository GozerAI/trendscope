"""Tests for offline trend analysis (item 756)."""

import pytest

from trendscope.core import Trend, TrendSource, TrendCategory
from trendscope.offline.cache import OfflineTrendCache
from trendscope.offline.analysis import (
    OfflineTrendAnalyzer,
    OfflineAnalysisResult,
    OfflineCorrelation,
)


def _make_trend(name="test", score=60.0, velocity=0.3, momentum=0.2, volume=500, source=TrendSource.REDDIT, **kw):
    return Trend(
        name=name, score=score, velocity=velocity, momentum=momentum,
        volume=volume, source=source, category=TrendCategory.TECHNOLOGY, **kw
    )


@pytest.fixture
def cache(tmp_path):
    return OfflineTrendCache(db_path=tmp_path / "cache.db")


@pytest.fixture
def analyzer(cache):
    return OfflineTrendAnalyzer(cache)


class TestOfflineTrendAnalyzer:
    def test_analyze_empty(self, analyzer):
        results = analyzer.analyze_all()
        assert results == []

    def test_analyze_single(self, cache, analyzer):
        cache.store(_make_trend())
        results = analyzer.analyze_all()
        assert len(results) == 1
        assert results[0].rank == 1
        assert results[0].composite_score > 0

    def test_analyze_ranking(self, cache, analyzer):
        cache.store(_make_trend(name="high", score=90, velocity=0.8))
        cache.store(_make_trend(name="low", score=20, velocity=-0.5))
        results = analyzer.analyze_all()
        assert results[0].trend_name == "high"
        assert results[0].rank == 1
        assert results[1].rank == 2

    def test_analyze_one(self, cache, analyzer):
        t = _make_trend()
        cache.store(t)
        result = analyzer.analyze_one(t.id)
        assert result is not None
        assert result.trend_id == t.id

    def test_analyze_one_missing(self, analyzer):
        assert analyzer.analyze_one("nope") is None

    def test_analyze_by_source(self, cache, analyzer):
        cache.store(_make_trend(name="r1", source=TrendSource.REDDIT))
        cache.store(_make_trend(name="g1", source=TrendSource.GOOGLE_TRENDS))
        results = analyzer.analyze_by_source("reddit")
        assert len(results) == 1

    def test_analyze_by_category(self, cache, analyzer):
        cache.store(_make_trend())
        results = analyzer.analyze_by_category("technology")
        assert len(results) == 1

    def test_top_trends(self, cache, analyzer):
        for i in range(15):
            cache.store(_make_trend(name=f"t{i}", score=float(i * 5)))
        top = analyzer.top_trends(n=5)
        assert len(top) == 5
        assert top[0].composite_score >= top[4].composite_score

    def test_status_classification(self, cache, analyzer):
        cache.store(_make_trend(name="emerging", velocity=0.6))
        cache.store(_make_trend(name="stable", velocity=0.0))
        cache.store(_make_trend(name="declining", velocity=-0.4))
        results = analyzer.analyze_all()
        statuses = {r.trend_name: r.status for r in results}
        assert statuses["emerging"] == "emerging"
        assert statuses["stable"] == "stable"
        assert statuses["declining"] == "declining"

    def test_direction_classification(self, cache, analyzer):
        cache.store(_make_trend(name="up", velocity=0.5))
        cache.store(_make_trend(name="down", velocity=-0.5))
        cache.store(_make_trend(name="flat", velocity=0.0))
        results = analyzer.analyze_all()
        dirs = {r.trend_name: r.direction for r in results}
        assert dirs["up"] == "up"
        assert dirs["down"] == "down"
        assert dirs["flat"] == "stable"

    def test_find_emerging(self, cache, analyzer):
        cache.store(_make_trend(name="hot", velocity=0.7))
        cache.store(_make_trend(name="cold", velocity=-0.3))
        emerging = analyzer.find_emerging(velocity_threshold=0.2)
        assert len(emerging) == 1
        assert emerging[0].trend_name == "hot"

    def test_find_declining(self, cache, analyzer):
        cache.store(_make_trend(name="ok", velocity=0.1))
        cache.store(_make_trend(name="bad", velocity=-0.6))
        declining = analyzer.find_declining(velocity_threshold=-0.2)
        assert len(declining) == 1
        assert declining[0].trend_name == "bad"

    def test_correlate_with_history(self, cache, analyzer):
        t1 = _make_trend(name="a", history=[{"score": 10}, {"score": 20}, {"score": 30}])
        t2 = _make_trend(name="b", history=[{"score": 15}, {"score": 25}, {"score": 35}])
        cache.store(t1)
        cache.store(t2)
        corr = analyzer.correlate(t1.id, t2.id)
        assert corr is not None
        assert corr.correlation > 0.9  # nearly perfect positive correlation

    def test_correlate_missing(self, analyzer):
        assert analyzer.correlate("a", "b") is None

    def test_correlate_no_history(self, cache, analyzer):
        t1 = _make_trend(name="x")
        t2 = _make_trend(name="y")
        cache.store(t1)
        cache.store(t2)
        assert analyzer.correlate(t1.id, t2.id) is None

    def test_summary(self, cache, analyzer):
        cache.store(_make_trend())
        summary = analyzer.summary()
        assert summary["total_analyzed"] == 1
        assert "cache" in summary
        assert "status_distribution" in summary

    def test_result_to_dict(self):
        r = OfflineAnalysisResult(trend_id="t1", trend_name="x", composite_score=0.75)
        d = r.to_dict()
        assert d["trend_id"] == "t1"
        assert d["composite_score"] == 0.75

    def test_correlation_to_dict(self):
        c = OfflineCorrelation(trend_a_id="a", trend_b_id="b", correlation=0.95)
        d = c.to_dict()
        assert d["correlation"] == 0.95
