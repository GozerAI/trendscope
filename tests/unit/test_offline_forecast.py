"""Tests for offline forecast generation (item 784)."""

import pytest

from trendscope.core import Trend, TrendSource, TrendCategory
from trendscope.offline.cache import OfflineTrendCache
from trendscope.offline.forecast import OfflineForecastGenerator, OfflineForecast


def _make_trend(name="test", score=60.0, velocity=0.3, history=None, source=TrendSource.REDDIT, **kw):
    return Trend(
        name=name, score=score, velocity=velocity,
        source=source, category=TrendCategory.TECHNOLOGY,
        history=history or [], **kw
    )


@pytest.fixture
def cache(tmp_path):
    return OfflineTrendCache(db_path=tmp_path / "cache.db")


@pytest.fixture
def generator(cache):
    return OfflineForecastGenerator(cache)


class TestOfflineForecast:
    def test_effective_confidence(self):
        fc = OfflineForecast(trend_id="t1", trend_name="x", freshness=0.8, confidence_penalty=0.1)
        assert fc.effective_confidence == pytest.approx(0.7)

    def test_effective_confidence_floor(self):
        fc = OfflineForecast(trend_id="t1", trend_name="x", freshness=0.1, confidence_penalty=0.5)
        assert fc.effective_confidence == 0.0

    def test_to_dict(self):
        fc = OfflineForecast(trend_id="t1", trend_name="x")
        d = fc.to_dict()
        assert "effective_confidence" in d
        assert "warnings" in d


class TestOfflineForecastGenerator:
    def test_forecast_missing(self, generator):
        assert generator.forecast("nonexistent") is None

    def test_forecast_no_history_uses_score(self, cache, generator):
        t = _make_trend(score=80.0)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc is not None
        assert "insufficient_history_using_current_score" in fc.warnings
        assert fc.data_points == 1

    def test_forecast_with_history(self, cache, generator):
        history = [{"score": 50}, {"score": 55}, {"score": 60}, {"score": 65}, {"score": 70}]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc is not None
        assert fc.data_points == 5
        assert "7d" in fc.horizons
        assert "30d" in fc.horizons
        assert fc.direction == "up"

    def test_forecast_upward_trend(self, cache, generator):
        history = [{"score": float(i * 10)} for i in range(1, 8)]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc.direction == "up"
        assert fc.current_trend > 0

    def test_forecast_downward_trend(self, cache, generator):
        history = [{"score": float(100 - i * 10)} for i in range(8)]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc.direction == "down"
        assert fc.current_trend < 0

    def test_forecast_custom_horizons(self, cache, generator):
        history = [{"score": float(i)} for i in range(10)]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id, horizons=[3, 14])
        assert "3d" in fc.horizons
        assert "14d" in fc.horizons
        assert "7d" not in fc.horizons

    def test_forecast_confidence_interval_grows(self, cache, generator):
        history = [{"score": float(i * 5 + 10)} for i in range(10)]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id, horizons=[7, 30, 90])
        ci_7 = fc.horizons["7d"]["confidence_interval"]
        ci_30 = fc.horizons["30d"]["confidence_interval"]
        ci_90 = fc.horizons["90d"]["confidence_interval"]
        assert ci_7 <= ci_30 <= ci_90

    def test_forecast_all(self, cache, generator):
        for i in range(5):
            history = [{"score": float(j)} for j in range(3)]
            cache.store(_make_trend(name=f"t{i}", history=history))
        forecasts = generator.forecast_all()
        assert len(forecasts) == 5

    def test_forecast_all_fresh_only(self, cache, generator):
        t = _make_trend(history=[{"score": 1}, {"score": 2}])
        cache.store(t, ttl_hours=24)
        forecasts = generator.forecast_all(fresh_only=True)
        assert len(forecasts) == 1

    def test_forecast_by_source(self, cache, generator):
        cache.store(_make_trend(name="r1", source=TrendSource.REDDIT, history=[{"score": 1}, {"score": 2}]))
        cache.store(_make_trend(name="g1", source=TrendSource.GOOGLE_TRENDS, history=[{"score": 3}, {"score": 4}]))
        reddit_fc = generator.forecast_by_source("reddit")
        assert len(reddit_fc) == 1

    def test_batch_summary(self, cache, generator):
        for i in range(3):
            cache.store(_make_trend(name=f"t{i}", history=[{"score": float(j)} for j in range(4)]))
        summary = generator.batch_summary()
        assert summary["total_forecasts"] == 3
        assert "direction_distribution" in summary

    def test_batch_summary_empty(self, generator):
        summary = generator.batch_summary()
        assert summary["total_forecasts"] == 0

    def test_single_point_with_velocity(self, cache, generator):
        t = _make_trend(score=50.0, velocity=0.5)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc is not None
        assert "single_point_flat_projection" in fc.warnings

    def test_zero_score_no_forecast(self, cache, generator):
        t = _make_trend(score=0.0)
        cache.store(t)
        fc = generator.forecast(t.id)
        assert fc is None

    def test_horizon_bounds(self, cache, generator):
        history = [{"score": float(i)} for i in range(5)]
        t = _make_trend(history=history)
        cache.store(t)
        fc = generator.forecast(t.id)
        for key, val in fc.horizons.items():
            assert val["lower_bound"] >= 0  # floor at 0
            assert val["lower_bound"] <= val["predicted_score"]
