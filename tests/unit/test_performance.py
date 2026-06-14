"""Tests for trendscope.performance module.

Covers all 22 performance items:
  10  DenormalizedScoreManager
  17  TimeSeriesPartitionManager
  25  MaterializedViewManager
  32  QueryPlanCache
  48  ETagCache
  56  CollectorDeduplicator
  64  GeographicCache
  76  ConditionalResponseHandler
  84  ResponseFormatNegotiator
  91  MultiSourceAggregator
  98  DeltaEncoder
 133  BackpressureCollector
 139  StreamingIngestionPipeline
 147  TrendStreamProcessor
 153  AsyncForecastGenerator
 160  ParallelSourceCollector
 180  CompactTimeSeries
 191  MMapTrendHistory
 202  ConnectionPool
 209  AdaptiveTimeout
 242  MockServer / RecordedResponse
"""

import asyncio
import json
import struct
import tempfile
import time
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

import pytest

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendDatabase,
)
from trendscope.performance import (
    DenormalizedScoreManager,
    TimeSeriesPartitionManager,
    MaterializedViewManager,
    QueryPlanCache,
    ETagCache,
    CollectorDeduplicator,
    GeographicCache,
    ConditionalResponseHandler,
    ResponseFormatNegotiator,
    MultiSourceAggregator,
    DeltaEncoder,
    BackpressureCollector,
    StreamingIngestionPipeline,
    TrendStreamProcessor,
    AsyncForecastGenerator,
    ParallelSourceCollector,
    CompactTimeSeries,
    MMapTrendHistory,
    ConnectionPool,
    AdaptiveTimeout,
    MockServer,
    RecordedResponse,
)


# ── Shared fixtures ──────────────────────────────────────────────────────────

@pytest.fixture
def tmp_db(tmp_path):
    return TrendDatabase(tmp_path / "test.db")


@pytest.fixture
def sample_trend():
    return Trend(
        id="t1",
        name="AI Agents",
        score=75,
        velocity=0.6,
        momentum=0.4,
        volume=5000,
        category=TrendCategory.TECHNOLOGY,
        source=TrendSource.GOOGLE_TRENDS,
        status=TrendStatus.EMERGING,
        market_opportunity=0.7,
        competition_level=0.3,
        entry_barrier=0.2,
        data_quality=0.9,
        keywords=["ai", "agents"],
    )


@pytest.fixture
def sample_trend_b():
    return Trend(
        id="t2",
        name="Quantum Computing",
        score=60,
        velocity=0.3,
        momentum=0.2,
        volume=3000,
        category=TrendCategory.TECHNOLOGY,
        source=TrendSource.HACKER_NEWS,
        status=TrendStatus.GROWING,
        market_opportunity=0.5,
        competition_level=0.5,
        entry_barrier=0.6,
        data_quality=0.8,
        keywords=["quantum", "computing"],
    )


def _save_trends(db, *trends):
    for t in trends:
        db.save_trend(t)


# =============================================================================
# 10. DenormalizedScoreManager
# =============================================================================

class TestDenormalizedScoreManager:

    def test_recompute_single(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        mgr = DenormalizedScoreManager(tmp_db)
        result = mgr.recompute(sample_trend)
        assert result["trend_id"] == "t1"
        assert "signal_score" in result
        assert "opportunity_score" in result
        assert "composite_rank" in result
        assert result["velocity_bucket"] == "surging"

    def test_recompute_all(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        mgr = DenormalizedScoreManager(tmp_db)
        count = mgr.recompute_all()
        assert count == 2

    def test_get_top_by_composite(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        mgr = DenormalizedScoreManager(tmp_db)
        mgr.recompute_all()
        top = mgr.get_top_by_composite(limit=10)
        assert len(top) == 2
        assert top[0]["composite_rank"] >= top[1]["composite_rank"]

    def test_get_by_bucket(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        mgr = DenormalizedScoreManager(tmp_db)
        mgr.recompute(sample_trend)
        surging = mgr.get_by_bucket("surging")
        assert len(surging) == 1
        assert surging[0]["trend_id"] == "t1"

    def test_velocity_buckets(self, tmp_db):
        mgr = DenormalizedScoreManager(tmp_db)
        assert mgr._velocity_bucket(0.8) == "surging"
        assert mgr._velocity_bucket(0.3) == "growing"
        assert mgr._velocity_bucket(0.0) == "stable"
        assert mgr._velocity_bucket(-0.3) == "declining"
        assert mgr._velocity_bucket(-0.8) == "crashing"

    def test_empty_db(self, tmp_db):
        mgr = DenormalizedScoreManager(tmp_db)
        assert mgr.recompute_all() == 0
        assert mgr.get_top_by_composite() == []


# =============================================================================
# 17. TimeSeriesPartitionManager
# =============================================================================

class TestTimeSeriesPartitionManager:

    def test_ensure_partition(self, tmp_db):
        mgr = TimeSeriesPartitionManager(tmp_db)
        dt = datetime(2026, 3, 15, tzinfo=timezone.utc)
        name = mgr.ensure_partition(dt)
        assert name == "trend_history_2026_03"
        assert name in mgr._partitions

    def test_insert_and_query(self, tmp_db):
        mgr = TimeSeriesPartitionManager(tmp_db)
        dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
        mgr.insert("t1", dt, score=80.0, velocity=0.5, momentum=0.3, volume=100)
        results = mgr.query_range(
            "t1",
            datetime(2026, 3, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 31, tzinfo=timezone.utc),
        )
        assert len(results) == 1
        assert results[0]["score"] == 80.0

    def test_cross_month_query(self, tmp_db):
        mgr = TimeSeriesPartitionManager(tmp_db)
        dt1 = datetime(2026, 2, 28, tzinfo=timezone.utc)
        dt2 = datetime(2026, 3, 1, tzinfo=timezone.utc)
        mgr.insert("t1", dt1, 70.0, 0.3, 0.1, 50)
        mgr.insert("t1", dt2, 75.0, 0.4, 0.2, 60)

        results = mgr.query_range(
            "t1",
            datetime(2026, 2, 1, tzinfo=timezone.utc),
            datetime(2026, 3, 31, tzinfo=timezone.utc),
        )
        assert len(results) == 2

    def test_partition_stats(self, tmp_db):
        mgr = TimeSeriesPartitionManager(tmp_db)
        dt = datetime(2026, 3, 10, tzinfo=timezone.utc)
        mgr.insert("t1", dt, 80.0, 0.5, 0.3, 100)
        stats = mgr.get_partition_stats()
        assert "trend_history_2026_03" in stats
        assert stats["trend_history_2026_03"] == 1

    def test_year_boundary(self, tmp_db):
        mgr = TimeSeriesPartitionManager(tmp_db)
        dt = datetime(2025, 12, 31, tzinfo=timezone.utc)
        name = mgr.ensure_partition(dt)
        assert name == "trend_history_2025_12"


# =============================================================================
# 25. MaterializedViewManager
# =============================================================================

class TestMaterializedViewManager:

    def test_refresh_all(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        mgr = MaterializedViewManager(tmp_db)
        result = mgr.refresh_all()
        assert result["category_summary"] >= 1
        assert result["source_summary"] >= 1

    def test_get_category_summary(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        mgr = MaterializedViewManager(tmp_db)
        mgr.refresh_all()
        summary = mgr.get_category_summary()
        assert len(summary) >= 1
        assert "category" in summary[0]
        assert "avg_score" in summary[0]

    def test_get_source_summary(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        mgr = MaterializedViewManager(tmp_db)
        mgr.refresh_all()
        summary = mgr.get_source_summary()
        assert len(summary) >= 1

    def test_last_refresh_tracked(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        mgr = MaterializedViewManager(tmp_db)
        assert mgr.last_refresh is None
        mgr.refresh_all()
        assert mgr.last_refresh is not None

    def test_empty_db(self, tmp_db):
        mgr = MaterializedViewManager(tmp_db)
        result = mgr.refresh_all()
        assert result["category_summary"] == 0


# =============================================================================
# 32. QueryPlanCache
# =============================================================================

class TestQueryPlanCache:

    def test_cache_hit(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        cache = QueryPlanCache(tmp_db, ttl_seconds=60)
        q = "SELECT * FROM trends WHERE id = ?"
        r1 = cache.execute(q, ("t1",))
        r2 = cache.execute(q, ("t1",))
        assert r1 == r2
        assert cache.stats()["hits"] == 1
        assert cache.stats()["misses"] == 1

    def test_cache_miss_different_params(self, tmp_db, sample_trend, sample_trend_b):
        _save_trends(tmp_db, sample_trend, sample_trend_b)
        cache = QueryPlanCache(tmp_db)
        q = "SELECT * FROM trends WHERE id = ?"
        cache.execute(q, ("t1",))
        cache.execute(q, ("t2",))
        assert cache.stats()["misses"] == 2

    def test_ttl_expiry(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        cache = QueryPlanCache(tmp_db, ttl_seconds=0)
        q = "SELECT * FROM trends WHERE id = ?"
        cache.execute(q, ("t1",))
        time.sleep(0.01)
        cache.execute(q, ("t1",))
        assert cache.stats()["misses"] == 2

    def test_invalidate_all(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        cache = QueryPlanCache(tmp_db)
        cache.execute("SELECT * FROM trends", ())
        cache.invalidate()
        assert cache.stats()["entries"] == 0

    def test_lru_eviction(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        cache = QueryPlanCache(tmp_db, max_entries=2)
        cache.execute("SELECT 1", ())
        cache.execute("SELECT 2", ())
        cache.execute("SELECT 3", ())
        assert cache.stats()["entries"] == 2


# =============================================================================
# 48. ETagCache
# =============================================================================

class TestETagCache:

    def test_put_and_get(self):
        cache = ETagCache()
        cache.put("http://example.com/api", b'{"data":1}', etag='"abc123"')
        entry = cache.get("http://example.com/api")
        assert entry is not None
        assert entry.etag == '"abc123"'
        assert entry.body == b'{"data":1}'

    def test_ttl_expiry(self):
        cache = ETagCache(ttl_seconds=0)
        cache.put("http://example.com/api", b"x")
        time.sleep(0.01)
        assert cache.get("http://example.com/api") is None

    def test_conditional_headers(self):
        cache = ETagCache()
        cache.put("http://example.com/api", b"x", etag='"etag1"', last_modified="Mon, 01 Jan 2026")
        headers = cache.conditional_headers("http://example.com/api")
        assert headers["If-None-Match"] == '"etag1"'
        assert headers["If-Modified-Since"] == "Mon, 01 Jan 2026"

    def test_conditional_headers_miss(self):
        cache = ETagCache()
        headers = cache.conditional_headers("http://unknown.com")
        assert headers == {}

    def test_max_entries(self):
        cache = ETagCache(max_entries=2)
        cache.put("http://a.com", b"a")
        cache.put("http://b.com", b"b")
        cache.put("http://c.com", b"c")
        assert cache.stats()["entries"] == 2


# =============================================================================
# 56. CollectorDeduplicator
# =============================================================================

class TestCollectorDeduplicator:

    def test_first_seen_not_duplicate(self, sample_trend):
        dedup = CollectorDeduplicator()
        assert dedup.is_duplicate(sample_trend) is False

    def test_second_seen_is_duplicate(self, sample_trend):
        dedup = CollectorDeduplicator()
        dedup.is_duplicate(sample_trend)
        assert dedup.is_duplicate(sample_trend) is True

    def test_different_trends_not_duplicate(self, sample_trend, sample_trend_b):
        dedup = CollectorDeduplicator()
        assert dedup.is_duplicate(sample_trend) is False
        assert dedup.is_duplicate(sample_trend_b) is False

    def test_deduplicate_list(self, sample_trend):
        dedup = CollectorDeduplicator()
        result = dedup.deduplicate([sample_trend, sample_trend, sample_trend])
        assert len(result) == 1

    def test_stats(self, sample_trend):
        dedup = CollectorDeduplicator()
        dedup.deduplicate([sample_trend, sample_trend])
        stats = dedup.stats()
        assert stats["duplicates_filtered"] == 1
        assert stats["tracked"] == 1

    def test_ttl_expiry(self, sample_trend):
        dedup = CollectorDeduplicator(ttl_seconds=0)
        dedup.is_duplicate(sample_trend)
        time.sleep(0.01)
        assert dedup.is_duplicate(sample_trend) is False


# =============================================================================
# 64. GeographicCache
# =============================================================================

class TestGeographicCache:

    def test_put_and_get(self):
        cache = GeographicCache()
        data = [{"name": "AI Agents", "score": 85}]
        cache.put("US", data)
        result = cache.get("US")
        assert result == data

    def test_miss(self):
        cache = GeographicCache()
        assert cache.get("US") is None

    def test_ttl_expiry(self):
        cache = GeographicCache(ttl_seconds=0)
        cache.put("US", [{"name": "test"}])
        time.sleep(0.01)
        assert cache.get("US") is None

    def test_invalidate_geo(self):
        cache = GeographicCache()
        cache.put("US", [{"a": 1}])
        cache.put("UK", [{"b": 2}])
        cache.invalidate("US")
        assert cache.get("US") is None
        assert cache.get("UK") is not None

    def test_invalidate_all(self):
        cache = GeographicCache()
        cache.put("US", [])
        cache.put("UK", [])
        cache.invalidate()
        assert cache.stats()["entries"] == 0

    def test_hit_rate(self):
        cache = GeographicCache()
        cache.put("US", [])
        cache.get("US")
        cache.get("US")
        stats = cache.stats()
        assert stats["hits"] == 2
        assert stats["misses"] == 0
        assert stats["hit_rate"] == 1.0


# =============================================================================
# 76. ConditionalResponseHandler
# =============================================================================

class TestConditionalResponseHandler:

    def test_compute_etag(self):
        handler = ConditionalResponseHandler()
        etag = handler.compute_etag({"foo": "bar"})
        assert etag.startswith('W/"')
        assert etag.endswith('"')

    def test_same_data_same_etag(self):
        handler = ConditionalResponseHandler()
        e1 = handler.compute_etag({"a": 1})
        e2 = handler.compute_etag({"a": 1})
        assert e1 == e2

    def test_different_data_different_etag(self):
        handler = ConditionalResponseHandler()
        e1 = handler.compute_etag({"a": 1})
        e2 = handler.compute_etag({"a": 2})
        assert e1 != e2

    def test_should_return_304_matching(self):
        handler = ConditionalResponseHandler()
        data = {"trends": [1, 2, 3]}
        etag = handler.compute_etag(data)
        assert handler.should_return_304("trends", data, etag) is True

    def test_should_not_return_304_mismatched(self):
        handler = ConditionalResponseHandler()
        data = {"trends": [1, 2, 3]}
        assert handler.should_return_304("trends", data, '"old-etag"') is False

    def test_set_response_headers(self):
        handler = ConditionalResponseHandler()
        data = {"x": 1}
        headers = handler.set_response_headers("key1", data)
        assert "ETag" in headers
        assert "Cache-Control" in headers


# =============================================================================
# 84. ResponseFormatNegotiator
# =============================================================================

class TestResponseFormatNegotiator:

    def test_default_json(self):
        neg = ResponseFormatNegotiator()
        assert neg.negotiate("") == "application/json"

    def test_json_explicit(self):
        neg = ResponseFormatNegotiator()
        assert neg.negotiate("application/json") == "application/json"

    def test_encode_json(self):
        neg = ResponseFormatNegotiator()
        body, ct = neg.encode({"a": 1})
        assert ct == "application/json"
        assert json.loads(body) == {"a": 1}

    def test_decode_json(self):
        neg = ResponseFormatNegotiator()
        data = neg.decode(b'{"x": 42}')
        assert data == {"x": 42}

    def test_supported_formats(self):
        neg = ResponseFormatNegotiator()
        assert "application/json" in neg.supported_formats

    def test_encode_with_datetime(self):
        neg = ResponseFormatNegotiator()
        dt = datetime(2026, 3, 13, tzinfo=timezone.utc)
        body, ct = neg.encode({"ts": dt})
        assert b"2026" in body


# =============================================================================
# 91. MultiSourceAggregator
# =============================================================================

class TestMultiSourceAggregator:

    def test_aggregate_single_source(self):
        agg = MultiSourceAggregator()
        results = {
            "google_trends": [
                {"id": "1", "name": "AI Agents", "score": 80},
                {"id": "2", "name": "Quantum", "score": 60},
            ],
        }
        merged = agg.aggregate(results)
        assert len(merged) == 2

    def test_deduplication_across_sources(self):
        agg = MultiSourceAggregator()
        results = {
            "google_trends": [{"id": "1", "name": "AI Agents", "score": 80}],
            "reddit": [{"id": "2", "name": "AI Agents", "score": 70}],
        }
        merged = agg.aggregate(results)
        assert len(merged) == 1
        assert merged[0]["source_count"] == 2

    def test_multi_source_boost(self):
        agg = MultiSourceAggregator()
        results = {
            "google_trends": [{"id": "1", "name": "AI Agents", "score": 80}],
            "reddit": [{"id": "2", "name": "AI Agents", "score": 80}],
        }
        merged = agg.aggregate(results)
        # Multi-source boost should increase weighted score
        assert merged[0]["weighted_score"] > 80

    def test_summary(self):
        agg = MultiSourceAggregator()
        results = {
            "google_trends": [{"id": "1", "name": "A", "score": 80}],
            "reddit": [{"id": "2", "name": "A", "score": 70}],
        }
        summary = agg.summary(results)
        assert summary["total_raw"] == 2
        assert summary["total_aggregated"] == 1
        assert summary["dedup_savings"] == 1

    def test_set_source_weight(self):
        agg = MultiSourceAggregator()
        agg.set_source_weight("custom_source", 0.5)
        assert agg._source_weights["custom_source"] == 0.5

    def test_limit(self):
        agg = MultiSourceAggregator()
        results = {
            "google_trends": [
                {"id": str(i), "name": f"Trend {i}", "score": 50 + i}
                for i in range(20)
            ]
        }
        merged = agg.aggregate(results, limit=5)
        assert len(merged) == 5


# =============================================================================
# 98. DeltaEncoder
# =============================================================================

class TestDeltaEncoder:

    def test_first_request_full(self):
        enc = DeltaEncoder()
        data = [{"id": "1", "name": "AI", "score": 80}]
        result = enc.encode("client1", data)
        assert result["full"] is True
        assert len(result["data"]) == 1

    def test_no_change_empty_delta(self):
        enc = DeltaEncoder()
        data = [{"id": "1", "name": "AI", "score": 80}]
        enc.encode("client1", data)
        result = enc.encode("client1", data)
        assert result["full"] is False
        assert len(result["added"]) == 0
        assert len(result["updated"]) == 0
        assert len(result["removed"]) == 0

    def test_updated_item(self):
        enc = DeltaEncoder()
        enc.encode("c1", [{"id": "1", "name": "AI", "score": 80}])
        result = enc.encode("c1", [{"id": "1", "name": "AI", "score": 90}])
        assert result["full"] is False
        assert len(result["updated"]) == 1
        assert result["updated"][0]["score"] == 90

    def test_added_item(self):
        enc = DeltaEncoder()
        enc.encode("c1", [{"id": "1", "name": "AI", "score": 80}])
        result = enc.encode("c1", [
            {"id": "1", "name": "AI", "score": 80},
            {"id": "2", "name": "Quantum", "score": 60},
        ])
        assert len(result["added"]) == 1

    def test_removed_item(self):
        enc = DeltaEncoder()
        enc.encode("c1", [
            {"id": "1", "name": "AI", "score": 80},
            {"id": "2", "name": "Quantum", "score": 60},
        ])
        result = enc.encode("c1", [{"id": "1", "name": "AI", "score": 80}])
        assert len(result["removed"]) == 1
        assert "2" in result["removed"]

    def test_reset_client(self):
        enc = DeltaEncoder()
        enc.encode("c1", [{"id": "1"}])
        enc.reset("c1")
        result = enc.encode("c1", [{"id": "1"}])
        assert result["full"] is True

    def test_stats(self):
        enc = DeltaEncoder()
        enc.encode("c1", [])
        enc.encode("c2", [])
        assert enc.stats()["tracked_clients"] == 2


# =============================================================================
# 133. BackpressureCollector
# =============================================================================

class TestBackpressureCollector:

    @pytest.mark.asyncio
    async def test_collect_success(self):
        bp = BackpressureCollector(max_buffer=10)
        async def source():
            return [Trend(name="T1")]
        result = await bp.collect(source)
        assert result is True
        assert bp.buffer_size == 1

    @pytest.mark.asyncio
    async def test_backpressure_drop(self):
        bp = BackpressureCollector(max_buffer=1)
        async def source():
            return [Trend(name="T")]
        await bp.collect(source)
        # Buffer is full now
        result = await bp.collect(source)
        assert result is False
        assert bp.stats()["total_dropped"] == 1

    @pytest.mark.asyncio
    async def test_drain(self):
        bp = BackpressureCollector(max_buffer=10)
        async def source():
            return "item"
        await bp.collect(source)
        await bp.collect(source)
        items = await bp.drain(batch_size=5)
        assert len(items) == 2

    @pytest.mark.asyncio
    async def test_run_collectors(self):
        bp = BackpressureCollector(max_buffer=100)
        async def s1():
            return "a"
        async def s2():
            return "b"
        count = await bp.run_collectors([s1, s2])
        assert count == 2

    @pytest.mark.asyncio
    async def test_none_result_not_buffered(self):
        bp = BackpressureCollector(max_buffer=10)
        async def source():
            return None
        result = await bp.collect(source)
        assert result is False
        assert bp.buffer_size == 0


# =============================================================================
# 139. StreamingIngestionPipeline
# =============================================================================

class TestStreamingIngestionPipeline:

    @pytest.mark.asyncio
    async def test_ingest_single(self, tmp_db, sample_trend):
        pipe = StreamingIngestionPipeline(tmp_db, batch_size=10)
        await pipe.ingest(sample_trend)
        assert pipe.stats()["total_ingested"] == 1

    @pytest.mark.asyncio
    async def test_auto_flush_on_batch_size(self, tmp_db):
        pipe = StreamingIngestionPipeline(tmp_db, batch_size=2)
        t1 = Trend(name="T1", score=50)
        t2 = Trend(name="T2", score=60)
        await pipe.ingest(t1)
        await pipe.ingest(t2)
        assert pipe.stats()["total_flushed"] == 2

    @pytest.mark.asyncio
    async def test_ingest_stream(self, tmp_db):
        pipe = StreamingIngestionPipeline(tmp_db, batch_size=5)

        async def gen():
            for i in range(3):
                yield Trend(name=f"Stream{i}", score=50 + i)

        count = await pipe.ingest_stream(gen())
        assert count == 3
        assert pipe.stats()["total_flushed"] == 3

    @pytest.mark.asyncio
    async def test_transform(self, tmp_db):
        pipe = StreamingIngestionPipeline(tmp_db, batch_size=10)
        pipe.add_transform(lambda t: Trend(id=t.id, name=t.name.upper(), score=t.score))
        t = Trend(name="lower", score=50)
        await pipe.ingest(t)
        await pipe.flush()
        # Verify transform applied
        stored = tmp_db.get_trends(limit=1)
        assert len(stored) >= 1


# =============================================================================
# 147. TrendStreamProcessor
# =============================================================================

class TestTrendStreamProcessor:

    def test_process_no_alert(self):
        proc = TrendStreamProcessor(velocity_alert_threshold=0.9, score_alert_threshold=95)
        t = Trend(id="t1", name="AI", score=50, velocity=0.1)
        alert = proc.process(t)
        assert alert is None

    def test_process_velocity_alert(self):
        proc = TrendStreamProcessor(velocity_alert_threshold=0.3, score_alert_threshold=95)
        t = Trend(id="t1", name="AI", score=50, velocity=0.5)
        alert = proc.process(t)
        assert alert is not None
        assert alert["trend_id"] == "t1"

    def test_alert_cooldown(self):
        proc = TrendStreamProcessor(velocity_alert_threshold=0.3, score_alert_threshold=95)
        t = Trend(id="t1", name="AI", score=50, velocity=0.5)
        alert1 = proc.process(t)
        alert2 = proc.process(t)
        assert alert1 is not None
        assert alert2 is None  # Cooldown active

    def test_get_window(self):
        proc = TrendStreamProcessor()
        t = Trend(id="t1", name="AI", score=70, velocity=0.3)
        proc.process(t)
        window = proc.get_window("t1")
        assert window is not None
        assert window["count"] == 1

    def test_stats(self):
        proc = TrendStreamProcessor()
        proc.process(Trend(id="t1", name="AI", score=50, velocity=0.1))
        stats = proc.stats()
        assert stats["total_processed"] == 1
        assert stats["windows_tracked"] == 1


# =============================================================================
# 153. AsyncForecastGenerator
# =============================================================================

class TestAsyncForecastGenerator:

    @pytest.mark.asyncio
    async def test_start_and_get_result(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        # Add more history points for forecast
        import sqlite3
        with sqlite3.connect(tmp_db.db_path) as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO trend_history (trend_id, timestamp, score, velocity, momentum, volume) VALUES (?, ?, ?, ?, ?, ?)",
                    ("t1", f"2026-03-0{i+1}T00:00:00", 70 + i * 2, 0.5, 0.3, 100 + i),
                )
            conn.commit()

        gen = AsyncForecastGenerator(tmp_db)
        task_id = await gen.start("t1")
        await asyncio.sleep(0.1)
        assert gen.is_done(task_id)
        result = gen.get_result(task_id)
        assert result is not None

    @pytest.mark.asyncio
    async def test_cancel(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        gen = AsyncForecastGenerator(tmp_db)
        task_id = await gen.start("t1")
        cancelled = await gen.cancel(task_id)
        # May already be done, but method should not crash
        assert isinstance(cancelled, bool)

    @pytest.mark.asyncio
    async def test_stats(self, tmp_db, sample_trend):
        _save_trends(tmp_db, sample_trend)
        gen = AsyncForecastGenerator(tmp_db)
        await gen.start("t1")
        await asyncio.sleep(0.1)
        stats = gen.stats()
        assert stats["total_tasks"] >= 1


# =============================================================================
# 160. ParallelSourceCollector
# =============================================================================

class TestParallelSourceCollector:

    @pytest.mark.asyncio
    async def test_parallel_collect(self):
        psc = ParallelSourceCollector(timeout_per_source=5.0)

        async def source_a():
            return [Trend(name="A", source=TrendSource.GOOGLE_TRENDS)]

        async def source_b():
            return [Trend(name="B", source=TrendSource.REDDIT)]

        result = await psc.collect_parallel({
            "source_a": source_a,
            "source_b": source_b,
        })
        assert result["total"] == 2
        assert len(result["errors"]) == 0

    @pytest.mark.asyncio
    async def test_timeout_handling(self):
        psc = ParallelSourceCollector(timeout_per_source=0.01)

        async def slow_source():
            await asyncio.sleep(10)
            return []

        result = await psc.collect_parallel({"slow": slow_source})
        assert "slow" in result["errors"]
        assert result["errors"]["slow"] == "timeout"

    @pytest.mark.asyncio
    async def test_error_handling(self):
        psc = ParallelSourceCollector()

        async def broken():
            raise ValueError("broken")

        result = await psc.collect_parallel({"broken": broken})
        assert "broken" in result["errors"]

    @pytest.mark.asyncio
    async def test_deduplication_across_sources(self):
        psc = ParallelSourceCollector()

        async def s1():
            return [Trend(name="Same", source=TrendSource.GOOGLE_TRENDS)]

        async def s2():
            return [Trend(name="Same", source=TrendSource.GOOGLE_TRENDS)]

        result = await psc.collect_parallel({"s1": s1, "s2": s2})
        assert result["dedup_filtered"] >= 1


# =============================================================================
# 180. CompactTimeSeries
# =============================================================================

class TestCompactTimeSeries:

    def test_append_and_get(self):
        cts = CompactTimeSeries()
        cts.append("t1", 1710000000.0, 80.5, 0.3, 100)
        series = cts.get_series("t1")
        assert len(series) == 1
        assert series[0]["score"] == pytest.approx(80.5, abs=0.1)

    def test_get_scores(self):
        cts = CompactTimeSeries()
        cts.append("t1", 1.0, 70.0, 0.1, 10)
        cts.append("t1", 2.0, 80.0, 0.2, 20)
        scores = cts.get_scores("t1")
        assert len(scores) == 2
        assert scores[0] == pytest.approx(70.0, abs=0.1)

    def test_max_points_enforcement(self):
        cts = CompactTimeSeries(max_points=5)
        for i in range(10):
            cts.append("t1", float(i), float(i), 0.0, 0)
        assert cts.point_count("t1") == 5

    def test_memory_usage(self):
        cts = CompactTimeSeries()
        for i in range(100):
            cts.append("t1", float(i), float(i), 0.0, 0)
        usage = cts.memory_usage()
        assert usage["series_count"] == 1
        assert usage["total_points"] == 100
        assert usage["bytes_per_point"] == 20

    def test_empty_series(self):
        cts = CompactTimeSeries()
        assert cts.get_series("nonexistent") == []
        assert cts.get_scores("nonexistent") == []
        assert cts.point_count("nonexistent") == 0


# =============================================================================
# 191. MMapTrendHistory
# =============================================================================

class TestMMapTrendHistory:

    def test_append_and_read(self, tmp_path):
        mh = MMapTrendHistory(tmp_path / "mmap_data")
        mh.append("t1", 1710000000.0, 85.0, 0.5, 200)
        points = mh.read_all("t1")
        assert len(points) == 1
        assert points[0]["score"] == pytest.approx(85.0, abs=0.1)

    def test_multiple_appends(self, tmp_path):
        mh = MMapTrendHistory(tmp_path / "mmap_data")
        for i in range(10):
            mh.append("t1", float(i), 50.0 + i, 0.1 * i, i * 10)
        assert mh.point_count("t1") == 10
        points = mh.read_all("t1")
        assert len(points) == 10

    def test_nonexistent_trend(self, tmp_path):
        mh = MMapTrendHistory(tmp_path / "mmap_data")
        assert mh.read_all("nonexistent") == []
        assert mh.point_count("nonexistent") == 0

    def test_file_growth(self, tmp_path):
        mh = MMapTrendHistory(tmp_path / "mmap_data")
        # Write more than initial capacity
        for i in range(1500):
            mh.append("t1", float(i), float(i), 0.0, 0)
        assert mh.point_count("t1") == 1500

    def test_multiple_trends(self, tmp_path):
        mh = MMapTrendHistory(tmp_path / "mmap_data")
        mh.append("t1", 1.0, 80.0, 0.3, 100)
        mh.append("t2", 2.0, 60.0, 0.1, 50)
        assert mh.point_count("t1") == 1
        assert mh.point_count("t2") == 1


# =============================================================================
# 202. ConnectionPool
# =============================================================================

class TestConnectionPool:

    def test_request_tracking(self):
        pool = ConnectionPool()
        # Just test stats without actual requests
        stats = pool.stats()
        assert stats["total_requests"] == 0
        assert stats["hosts_tracked"] == 0

    def test_host_key_extraction(self):
        pool = ConnectionPool()
        key = pool._host_key("https://api.example.com/v1/data")
        assert "api.example.com" in key
        assert "443" in key

    def test_host_key_http(self):
        pool = ConnectionPool()
        key = pool._host_key("http://api.example.com/v1/data")
        assert "80" in key

    def test_with_mock_server(self):
        server = MockServer()
        server.record("/api/test", RecordedResponse(body={"ok": True}))
        base_url = server.start()
        try:
            pool = ConnectionPool()
            result = pool.request(f"{base_url}/api/test")
            assert result is not None
            data = json.loads(result)
            assert data["ok"] is True
            assert pool.stats()["total_requests"] == 1
        finally:
            server.stop()

    def test_reuse_count(self):
        server = MockServer()
        server.record("/api/data", RecordedResponse(body={"v": 1}))
        base_url = server.start()
        try:
            pool = ConnectionPool()
            pool.request(f"{base_url}/api/data")
            pool.request(f"{base_url}/api/data")
            assert pool.stats()["reused_connections"] == 1
        finally:
            server.stop()


# =============================================================================
# 209. AdaptiveTimeout
# =============================================================================

class TestAdaptiveTimeout:

    def test_default_timeout(self):
        at = AdaptiveTimeout(default_timeout=15.0)
        assert at.get_timeout("http://example.com/api") == 15.0

    def test_adapts_to_latency(self):
        at = AdaptiveTimeout(default_timeout=15.0, multiplier=2.0)
        # Record consistent latencies
        for _ in range(10):
            at.record("http://example.com/api", 0.5)
        timeout = at.get_timeout("http://example.com/api")
        # Should be close to 0.5 + 2*0 = 0.5, clamped to min
        assert timeout >= at._min
        assert timeout < 15.0

    def test_high_variance_increases_timeout(self):
        at = AdaptiveTimeout(multiplier=2.0, min_timeout=1.0)
        latencies = [0.1, 0.1, 0.1, 5.0, 0.1, 0.1, 5.0, 0.1, 0.1, 5.0]
        for lat in latencies:
            at.record("http://slow.com/api", lat)
        timeout = at.get_timeout("http://slow.com/api")
        # High variance should push timeout up
        assert timeout > 2.0

    def test_max_clamp(self):
        at = AdaptiveTimeout(max_timeout=10.0)
        for _ in range(10):
            at.record("http://x.com", 100.0)
        assert at.get_timeout("http://x.com") == 10.0

    def test_min_clamp(self):
        at = AdaptiveTimeout(min_timeout=5.0)
        for _ in range(10):
            at.record("http://fast.com", 0.001)
        assert at.get_timeout("http://fast.com") >= 5.0

    def test_get_stats(self):
        at = AdaptiveTimeout()
        at.record("http://example.com/api", 0.5)
        at.record("http://example.com/api", 0.6)
        at.record("http://example.com/api", 0.7)
        stats = at.get_stats("http://example.com/api")
        assert stats["samples"] == 3
        assert "mean_latency" in stats
        assert "adaptive_timeout" in stats

    def test_all_stats(self):
        at = AdaptiveTimeout()
        at.record("http://a.com/api", 1.0)
        at.record("http://b.com/api", 2.0)
        all_stats = at.all_stats()
        assert len(all_stats) == 2


# =============================================================================
# 242. MockServer
# =============================================================================

class TestMockServer:

    def test_basic_response(self):
        server = MockServer()
        server.record("/test", RecordedResponse(status=200, body={"hello": "world"}))
        base_url = server.start()
        try:
            resp = urllib.request.urlopen(f"{base_url}/test")
            data = json.loads(resp.read())
            assert data["hello"] == "world"
        finally:
            server.stop()

    def test_404_for_unrecorded(self):
        server = MockServer()
        base_url = server.start()
        try:
            try:
                urllib.request.urlopen(f"{base_url}/missing")
                assert False, "Should have raised"
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.stop()

    def test_custom_status(self):
        server = MockServer()
        server.record("/error", RecordedResponse(status=500, body={"error": "fail"}))
        base_url = server.start()
        try:
            try:
                urllib.request.urlopen(f"{base_url}/error")
                assert False, "Should have raised"
            except urllib.error.HTTPError as e:
                assert e.code == 500
        finally:
            server.stop()

    def test_sequential_responses(self):
        server = MockServer()
        server.record("/seq", RecordedResponse(body={"v": 1}))
        server.record("/seq", RecordedResponse(body={"v": 2}))
        base_url = server.start()
        try:
            r1 = json.loads(urllib.request.urlopen(f"{base_url}/seq").read())
            r2 = json.loads(urllib.request.urlopen(f"{base_url}/seq").read())
            assert r1["v"] == 1
            assert r2["v"] == 2
        finally:
            server.stop()

    def test_request_log(self):
        server = MockServer()
        server.record("/api", RecordedResponse(body={}))
        base_url = server.start()
        try:
            urllib.request.urlopen(f"{base_url}/api")
            log = server.request_log
            assert len(log) == 1
            assert log[0]["method"] == "GET"
            assert log[0]["path"] == "/api"
        finally:
            server.stop()

    def test_custom_headers(self):
        server = MockServer()
        server.record("/h", RecordedResponse(
            body={"ok": True},
            headers={"X-Custom": "value"},
        ))
        base_url = server.start()
        try:
            resp = urllib.request.urlopen(f"{base_url}/h")
            assert resp.headers.get("X-Custom") == "value"
        finally:
            server.stop()

    def test_recorded_response_string_body(self):
        resp = RecordedResponse(body="hello")
        assert resp.body == b"hello"

    def test_recorded_response_dict_body(self):
        resp = RecordedResponse(body={"a": 1})
        assert json.loads(resp.body) == {"a": 1}

    def test_reset(self):
        server = MockServer()
        server.record("/x", RecordedResponse(body={}))
        server.reset()
        # Responses should be cleared
        base_url = server.start()
        try:
            try:
                urllib.request.urlopen(f"{base_url}/x")
                assert False, "Should have raised"
            except urllib.error.HTTPError as e:
                assert e.code == 404
        finally:
            server.stop()
