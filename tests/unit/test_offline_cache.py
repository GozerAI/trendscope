"""Tests for offline trend cache (item 756 foundation)."""

import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path

import pytest

from trendscope.core import Trend, TrendSource, TrendCategory
from trendscope.offline.cache import (
    CachedTrendData,
    OfflineTrendCache,
    DEFAULT_CACHE_TTL_HOURS,
    MAX_STALE_HOURS,
)


def _make_trend(name="test-trend", score=75.0, source=TrendSource.REDDIT, **kw):
    return Trend(name=name, score=score, source=source, category=TrendCategory.TECHNOLOGY, **kw)


@pytest.fixture
def cache(tmp_path):
    return OfflineTrendCache(db_path=tmp_path / "cache.db")


class TestCachedTrendData:
    def test_freshness_score_new(self):
        entry = CachedTrendData(trend_id="t1", trend_name="x", cached_at=datetime.now(timezone.utc))
        assert entry.freshness_score > 0.99
        assert entry.is_fresh
        assert not entry.is_stale

    def test_freshness_score_stale(self):
        old = datetime.now(timezone.utc) - timedelta(hours=MAX_STALE_HOURS + 1)
        entry = CachedTrendData(trend_id="t1", trend_name="x", cached_at=old)
        assert entry.freshness_score == 0.0
        assert entry.is_stale

    def test_to_trend_roundtrip(self):
        entry = CachedTrendData(
            trend_id="t1", trend_name="AI Trend", category="technology",
            source="reddit", score=80.0, velocity=0.5,
        )
        trend = entry.to_trend()
        assert trend.id == "t1"
        assert trend.name == "AI Trend"
        assert trend.score == 80.0

    def test_to_dict(self):
        entry = CachedTrendData(trend_id="t1", trend_name="x")
        d = entry.to_dict()
        assert "trend_id" in d
        assert "is_fresh" in d
        assert "freshness_score" in d


class TestOfflineTrendCache:
    def test_store_and_get(self, cache):
        trend = _make_trend()
        cache.store(trend)
        entry = cache.get(trend.id)
        assert entry is not None
        assert entry.trend_name == "test-trend"
        assert entry.score == 75.0

    def test_get_missing(self, cache):
        assert cache.get("nonexistent") is None

    def test_get_fresh_within_ttl(self, cache):
        trend = _make_trend()
        cache.store(trend, ttl_hours=24)
        assert cache.get_fresh(trend.id) is not None

    def test_store_many(self, cache):
        trends = [_make_trend(name=f"t-{i}") for i in range(5)]
        count = cache.store_many(trends)
        assert count == 5
        assert len(cache.get_all()) == 5

    def test_get_by_source(self, cache):
        cache.store(_make_trend(name="r1", source=TrendSource.REDDIT))
        cache.store(_make_trend(name="g1", source=TrendSource.GOOGLE_TRENDS))
        reddit = cache.get_by_source("reddit")
        assert len(reddit) == 1
        assert reddit[0].source == "reddit"

    def test_get_by_category(self, cache):
        cache.store(_make_trend(name="t1"))
        results = cache.get_by_category("technology")
        assert len(results) == 1

    def test_get_all_fresh_only(self, cache):
        cache.store(_make_trend(name="fresh"), ttl_hours=24)
        all_entries = cache.get_all(fresh_only=True)
        assert len(all_entries) == 1

    def test_evict_stale(self, cache):
        # Manually insert old entry
        import sqlite3
        old_time = (datetime.now(timezone.utc) - timedelta(hours=MAX_STALE_HOURS + 10)).isoformat()
        with sqlite3.connect(str(cache.db_path)) as conn:
            conn.execute(
                "INSERT INTO trend_cache (trend_id, trend_name, cached_at, ttl_hours) VALUES (?, ?, ?, ?)",
                ("old-1", "old", old_time, 1),
            )
        assert len(cache.get_all()) >= 1
        removed = cache.evict_stale()
        assert removed >= 1

    def test_clear(self, cache):
        cache.store(_make_trend(name="a"))
        cache.store(_make_trend(name="b"))
        removed = cache.clear()
        assert removed == 2
        assert len(cache.get_all()) == 0

    def test_stats(self, cache):
        cache.store(_make_trend(name="s1"))
        stats = cache.stats()
        assert stats["total_entries"] == 1
        assert stats["fresh_entries"] == 1

    def test_access_count_increments(self, cache):
        trend = _make_trend()
        cache.store(trend)
        cache.get(trend.id)
        cache.get(trend.id)
        entry = cache.get(trend.id)
        assert entry.access_count >= 2

    def test_store_replaces(self, cache):
        trend = _make_trend(score=50.0)
        cache.store(trend)
        trend.score = 90.0
        cache.store(trend)
        entry = cache.get(trend.id)
        assert entry.score == 90.0
        assert len(cache.get_all()) == 1
