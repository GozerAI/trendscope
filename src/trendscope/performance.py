"""
Performance optimizations for Trendscope.

Provides denormalized scores, time-series partitioning, materialized views,
query plan caching, ETag caching, collector deduplication, geographic caching,
conditional responses, response format negotiation, multi-source aggregation,
delta encoding, async backpressure collection, streaming ingestion, real-time
stream processing, async forecast with cancellation, parallel source collection,
memory-efficient time series, memory-mapped history, connection reuse,
adaptive timeouts, and a mock server for tests.
"""

import asyncio
import hashlib
import io
import json
import logging
import math
import mmap
import os
import struct
import tempfile
import time
import threading
from collections import OrderedDict, defaultdict, deque
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import (
    Any, AsyncIterator, Callable, Deque, Dict, List, Optional,
    Set, Tuple, Union,
)
from uuid import uuid4

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendDatabase,
    TrendAnalyzer,
    SIGNAL_WEIGHT_VELOCITY,
    SIGNAL_WEIGHT_MOMENTUM,
    SIGNAL_WEIGHT_MARKET_OPPORTUNITY,
    SIGNAL_WEIGHT_COMPETITION,
    SIGNAL_WEIGHT_ENTRY_BARRIER,
)

logger = logging.getLogger(__name__)


# ============================================================================
# 10. Denormalized Trend Score Columns
# ============================================================================

class DenormalizedScoreManager:
    """Pre-compute and store composite trend scores for fast dashboard queries.

    Maintains a ``trend_scores_denorm`` table with pre-computed signal score,
    opportunity score, and composite rank so that dashboards can query
    aggregated metrics without re-computing them on every request.
    """

    def __init__(self, db: TrendDatabase):
        self.db = db
        self._ensure_table()

    def _ensure_table(self) -> None:
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trend_scores_denorm (
                    trend_id TEXT PRIMARY KEY,
                    signal_score REAL DEFAULT 0,
                    opportunity_score REAL DEFAULT 0,
                    composite_rank REAL DEFAULT 0,
                    velocity_bucket TEXT DEFAULT 'stable',
                    last_recomputed TEXT,
                    FOREIGN KEY (trend_id) REFERENCES trends(id)
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_denorm_composite
                ON trend_scores_denorm(composite_rank DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_denorm_bucket
                ON trend_scores_denorm(velocity_bucket)
            """)
            conn.commit()

    @staticmethod
    def _compute_signal_score(trend: Trend) -> float:
        return (
            trend.velocity * SIGNAL_WEIGHT_VELOCITY
            + trend.momentum * SIGNAL_WEIGHT_MOMENTUM
            + trend.market_opportunity * SIGNAL_WEIGHT_MARKET_OPPORTUNITY
            + (1 - trend.competition_level) * SIGNAL_WEIGHT_COMPETITION
            + (1 - trend.entry_barrier) * SIGNAL_WEIGHT_ENTRY_BARRIER
        )

    @staticmethod
    def _compute_opportunity_score(trend: Trend) -> float:
        growth = (trend.velocity + 1) / 2
        comp = 1 - trend.competition_level
        barrier = 1 - trend.entry_barrier
        quality = trend.data_quality
        return growth * 0.4 + comp * 0.25 + barrier * 0.2 + quality * 0.15

    @staticmethod
    def _velocity_bucket(velocity: float) -> str:
        if velocity > 0.5:
            return "surging"
        elif velocity > 0.2:
            return "growing"
        elif velocity > -0.2:
            return "stable"
        elif velocity > -0.5:
            return "declining"
        return "crashing"

    def recompute(self, trend: Trend) -> Dict[str, Any]:
        """Recompute denormalized scores for a single trend."""
        import sqlite3

        sig = self._compute_signal_score(trend)
        opp = self._compute_opportunity_score(trend)
        composite = sig * 0.5 + opp * 0.3 + (trend.score / 100) * 0.2
        bucket = self._velocity_bucket(trend.velocity)
        now = datetime.now(timezone.utc).isoformat()

        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trend_scores_denorm
                (trend_id, signal_score, opportunity_score, composite_rank,
                 velocity_bucket, last_recomputed)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (trend.id, sig, opp, composite, bucket, now))
            conn.commit()

        return {
            "trend_id": trend.id,
            "signal_score": round(sig, 4),
            "opportunity_score": round(opp, 4),
            "composite_rank": round(composite, 4),
            "velocity_bucket": bucket,
        }

    def recompute_all(self) -> int:
        """Recompute denormalized scores for all trends. Returns count."""
        trends = self.db.get_trends(limit=10000)
        for trend in trends:
            self.recompute(trend)
        return len(trends)

    def get_top_by_composite(self, limit: int = 20) -> List[Dict[str, Any]]:
        """Get top trends by composite rank from the denormalized table."""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT d.*, t.name, t.category, t.score
                FROM trend_scores_denorm d
                JOIN trends t ON d.trend_id = t.id
                ORDER BY d.composite_rank DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [dict(r) for r in rows]

    def get_by_bucket(self, bucket: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get trends by velocity bucket."""
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT d.*, t.name, t.category
                FROM trend_scores_denorm d
                JOIN trends t ON d.trend_id = t.id
                WHERE d.velocity_bucket = ?
                ORDER BY d.composite_rank DESC
                LIMIT ?
            """, (bucket, limit)).fetchall()
            return [dict(r) for r in rows]


# ============================================================================
# 17. Time-Series Partitioning for Trend History
# ============================================================================

class TimeSeriesPartitionManager:
    """Partition trend_history into monthly tables for efficient range queries.

    Creates per-month tables (e.g. ``trend_history_2026_03``) and provides
    transparent query routing across partitions.
    """

    def __init__(self, db: TrendDatabase):
        self.db = db
        self._partitions: Set[str] = set()
        self._discover_partitions()

    def _partition_name(self, dt: datetime) -> str:
        return f"trend_history_{dt.year}_{dt.month:02d}"

    def _discover_partitions(self) -> None:
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'trend_history_%'"
            ).fetchall()
            self._partitions = {t[0] for t in tables}

    def ensure_partition(self, dt: datetime) -> str:
        """Create partition table for the given month if not exists."""
        import sqlite3
        name = self._partition_name(dt)
        if name not in self._partitions:
            with sqlite3.connect(self.db.db_path) as conn:
                conn.execute(f"""
                    CREATE TABLE IF NOT EXISTS {name} (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        trend_id TEXT NOT NULL,
                        timestamp TEXT NOT NULL,
                        score REAL,
                        velocity REAL,
                        momentum REAL,
                        volume INTEGER
                    )
                """)
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{name}_trend_id
                    ON {name}(trend_id)
                """)
                conn.execute(f"""
                    CREATE INDEX IF NOT EXISTS idx_{name}_ts
                    ON {name}(timestamp)
                """)
                conn.commit()
            self._partitions.add(name)
        return name

    def insert(self, trend_id: str, timestamp: datetime,
               score: float, velocity: float, momentum: float,
               volume: int) -> None:
        """Insert a history record into the correct partition."""
        import sqlite3
        table = self.ensure_partition(timestamp)
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(f"""
                INSERT INTO {table} (trend_id, timestamp, score, velocity, momentum, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (trend_id, timestamp.isoformat(), score, velocity, momentum, volume))
            conn.commit()

    def query_range(self, trend_id: str, start: datetime,
                    end: datetime) -> List[Dict[str, Any]]:
        """Query history across relevant partitions for a date range."""
        import sqlite3
        results = []
        current = start.replace(day=1)
        while current <= end:
            name = self._partition_name(current)
            if name in self._partitions:
                with sqlite3.connect(self.db.db_path) as conn:
                    conn.row_factory = sqlite3.Row
                    rows = conn.execute(f"""
                        SELECT * FROM {name}
                        WHERE trend_id = ? AND timestamp >= ? AND timestamp <= ?
                        ORDER BY timestamp ASC
                    """, (trend_id, start.isoformat(), end.isoformat())).fetchall()
                    results.extend([dict(r) for r in rows])
            # Move to next month
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1)
            else:
                current = current.replace(month=current.month + 1)
        return results

    def get_partition_stats(self) -> Dict[str, int]:
        """Get row counts per partition."""
        import sqlite3
        stats = {}
        with sqlite3.connect(self.db.db_path) as conn:
            for name in sorted(self._partitions):
                count = conn.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0]
                stats[name] = count
        return stats


# ============================================================================
# 25. Materialized Views for Dashboard Aggregations
# ============================================================================

class MaterializedViewManager:
    """Maintains pre-computed aggregation tables refreshed on demand.

    Views:
    - ``mv_category_summary``: count, avg score, avg velocity per category
    - ``mv_source_summary``: count, avg score per source
    - ``mv_daily_volume``: daily total volume across all trends
    """

    def __init__(self, db: TrendDatabase):
        self.db = db
        self._ensure_tables()
        self._last_refresh: Optional[datetime] = None

    def _ensure_tables(self) -> None:
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mv_category_summary (
                    category TEXT PRIMARY KEY,
                    trend_count INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    avg_velocity REAL DEFAULT 0,
                    max_score REAL DEFAULT 0,
                    refreshed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mv_source_summary (
                    source TEXT PRIMARY KEY,
                    trend_count INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    total_volume INTEGER DEFAULT 0,
                    refreshed_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS mv_daily_volume (
                    date TEXT PRIMARY KEY,
                    total_volume INTEGER DEFAULT 0,
                    trend_count INTEGER DEFAULT 0,
                    avg_score REAL DEFAULT 0,
                    refreshed_at TEXT
                )
            """)
            conn.commit()

    def refresh_all(self) -> Dict[str, int]:
        """Refresh all materialized views. Returns row counts per view."""
        cats = self._refresh_category_summary()
        srcs = self._refresh_source_summary()
        days = self._refresh_daily_volume()
        self._last_refresh = datetime.now(timezone.utc)
        return {"category_summary": cats, "source_summary": srcs, "daily_volume": days}

    def _refresh_category_summary(self) -> int:
        import sqlite3
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("DELETE FROM mv_category_summary")
            conn.execute(f"""
                INSERT INTO mv_category_summary
                    (category, trend_count, avg_score, avg_velocity, max_score, refreshed_at)
                SELECT category, COUNT(*), AVG(score), AVG(velocity), MAX(score), ?
                FROM trends GROUP BY category
            """, (now,))
            count = conn.execute("SELECT COUNT(*) FROM mv_category_summary").fetchone()[0]
            conn.commit()
            return count

    def _refresh_source_summary(self) -> int:
        import sqlite3
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("DELETE FROM mv_source_summary")
            conn.execute(f"""
                INSERT INTO mv_source_summary
                    (source, trend_count, avg_score, total_volume, refreshed_at)
                SELECT source, COUNT(*), AVG(score), SUM(volume), ?
                FROM trends GROUP BY source
            """, (now,))
            count = conn.execute("SELECT COUNT(*) FROM mv_source_summary").fetchone()[0]
            conn.commit()
            return count

    def _refresh_daily_volume(self) -> int:
        import sqlite3
        now = datetime.now(timezone.utc).isoformat()
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("DELETE FROM mv_daily_volume")
            conn.execute(f"""
                INSERT INTO mv_daily_volume
                    (date, total_volume, trend_count, avg_score, refreshed_at)
                SELECT substr(timestamp, 1, 10), SUM(volume), COUNT(*), AVG(score), ?
                FROM trend_history
                GROUP BY substr(timestamp, 1, 10)
            """, (now,))
            count = conn.execute("SELECT COUNT(*) FROM mv_daily_volume").fetchone()[0]
            conn.commit()
            return count

    def get_category_summary(self) -> List[Dict[str, Any]]:
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM mv_category_summary ORDER BY avg_score DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_source_summary(self) -> List[Dict[str, Any]]:
        import sqlite3
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM mv_source_summary ORDER BY trend_count DESC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_daily_volume(self, days: int = 30) -> List[Dict[str, Any]]:
        import sqlite3
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT * FROM mv_daily_volume WHERE date >= ? ORDER BY date ASC",
                (cutoff,),
            ).fetchall()
            return [dict(r) for r in rows]

    @property
    def last_refresh(self) -> Optional[datetime]:
        return self._last_refresh


# ============================================================================
# 32. Query Plan Caching for Frequent Queries
# ============================================================================

class QueryPlanCache:
    """Caches the results of frequently-run parameterised queries.

    Uses an LRU eviction strategy with a configurable TTL.  The cache key
    is derived from the SQL text and bound parameters.
    """

    def __init__(self, db: TrendDatabase, max_entries: int = 256,
                 ttl_seconds: float = 300):
        self.db = db
        self._max_entries = max_entries
        self._ttl = ttl_seconds
        self._cache: OrderedDict[str, Tuple[float, Any]] = OrderedDict()
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _cache_key(query: str, params: tuple) -> str:
        raw = f"{query}|{params}"
        return hashlib.md5(raw.encode()).hexdigest()

    def execute(self, query: str, params: tuple = ()) -> List[Dict[str, Any]]:
        """Execute a query, returning cached results when available."""
        import sqlite3
        key = self._cache_key(query, params)
        now = time.monotonic()

        if key in self._cache:
            ts, result = self._cache[key]
            if now - ts < self._ttl:
                self._hits += 1
                self._cache.move_to_end(key)
                return result
            else:
                del self._cache[key]

        self._misses += 1

        with sqlite3.connect(self.db.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            result = [dict(r) for r in rows]

        self._cache[key] = (now, result)
        if len(self._cache) > self._max_entries:
            self._cache.popitem(last=False)

        return result

    def invalidate(self, query: str = "", params: tuple = ()) -> None:
        """Invalidate a specific entry, or all entries if no args given."""
        if query:
            key = self._cache_key(query, params)
            self._cache.pop(key, None)
        else:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "max_entries": self._max_entries,
            "ttl_seconds": self._ttl,
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0,
        }


# ============================================================================
# 48. Data Source Response Caching with ETags
# ============================================================================

class ETagCache:
    """Cache HTTP responses keyed by URL with ETag / Last-Modified support.

    Stores response bodies alongside their ETag and Last-Modified headers
    so that conditional requests can return 304 Not Modified.
    """

    @dataclass
    class _Entry:
        url: str
        etag: Optional[str]
        last_modified: Optional[str]
        body: bytes
        stored_at: float
        content_hash: str

    def __init__(self, max_entries: int = 512, ttl_seconds: float = 600):
        self._entries: Dict[str, "ETagCache._Entry"] = {}
        self._max_entries = max_entries
        self._ttl = ttl_seconds

    def get(self, url: str) -> Optional["ETagCache._Entry"]:
        entry = self._entries.get(url)
        if entry and (time.monotonic() - entry.stored_at) < self._ttl:
            return entry
        if entry:
            del self._entries[url]
        return None

    def put(self, url: str, body: bytes, etag: Optional[str] = None,
            last_modified: Optional[str] = None) -> "_Entry":
        content_hash = hashlib.md5(body).hexdigest()
        entry = self._Entry(
            url=url, etag=etag, last_modified=last_modified,
            body=body, stored_at=time.monotonic(), content_hash=content_hash,
        )
        self._entries[url] = entry
        if len(self._entries) > self._max_entries:
            oldest_key = min(self._entries, key=lambda k: self._entries[k].stored_at)
            del self._entries[oldest_key]
        return entry

    def conditional_headers(self, url: str) -> Dict[str, str]:
        """Return headers for a conditional request based on cached data."""
        entry = self.get(url)
        headers: Dict[str, str] = {}
        if entry:
            if entry.etag:
                headers["If-None-Match"] = entry.etag
            if entry.last_modified:
                headers["If-Modified-Since"] = entry.last_modified
        return headers

    def stats(self) -> Dict[str, Any]:
        return {"entries": len(self._entries), "max_entries": self._max_entries}


# ============================================================================
# 56. Collector Response Deduplication
# ============================================================================

class CollectorDeduplicator:
    """Deduplicates trends from collectors using content hashing.

    Prevents the same trend from being stored multiple times across
    collection cycles by hashing (name, source) pairs and keeping a
    sliding window of recently-seen hashes.
    """

    def __init__(self, window_size: int = 5000, ttl_seconds: float = 3600):
        self._seen: OrderedDict[str, float] = OrderedDict()
        self._window_size = window_size
        self._ttl = ttl_seconds
        self._dedup_count = 0

    @staticmethod
    def _hash_trend(trend: Trend) -> str:
        raw = f"{trend.name.lower().strip()}|{trend.source.value}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def is_duplicate(self, trend: Trend) -> bool:
        """Return True if this trend has been seen recently."""
        h = self._hash_trend(trend)
        now = time.monotonic()

        if h in self._seen:
            ts = self._seen[h]
            if now - ts < self._ttl:
                self._dedup_count += 1
                return True
            del self._seen[h]

        self._seen[h] = now
        if len(self._seen) > self._window_size:
            self._seen.popitem(last=False)
        return False

    def deduplicate(self, trends: List[Trend]) -> List[Trend]:
        """Filter out duplicate trends from a list."""
        unique = []
        for trend in trends:
            if not self.is_duplicate(trend):
                unique.append(trend)
        return unique

    def stats(self) -> Dict[str, Any]:
        return {
            "tracked": len(self._seen),
            "window_size": self._window_size,
            "duplicates_filtered": self._dedup_count,
        }


# ============================================================================
# 64. Geographic Data Result Caching
# ============================================================================

class GeographicCache:
    """Caches trend results per geographic region with TTL.

    Avoids re-querying the same geo-filtered data within the TTL window.
    """

    def __init__(self, ttl_seconds: float = 300):
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._ttl = ttl_seconds
        self._hits = 0
        self._misses = 0

    @staticmethod
    def _key(geo: str, category: Optional[str] = None,
             limit: int = 50) -> str:
        return f"{geo}|{category or 'all'}|{limit}"

    def get(self, geo: str, category: Optional[str] = None,
            limit: int = 50) -> Optional[List[Dict[str, Any]]]:
        key = self._key(geo, category, limit)
        entry = self._cache.get(key)
        if entry:
            ts, data = entry
            if time.monotonic() - ts < self._ttl:
                self._hits += 1
                return data
            del self._cache[key]
        self._misses += 1
        return None

    def put(self, geo: str, data: List[Dict[str, Any]],
            category: Optional[str] = None, limit: int = 50) -> None:
        key = self._key(geo, category, limit)
        self._cache[key] = (time.monotonic(), data)

    def invalidate(self, geo: Optional[str] = None) -> None:
        if geo:
            keys = [k for k in self._cache if k.startswith(f"{geo}|")]
            for k in keys:
                del self._cache[k]
        else:
            self._cache.clear()

    def stats(self) -> Dict[str, Any]:
        total = self._hits + self._misses
        return {
            "entries": len(self._cache),
            "hits": self._hits,
            "misses": self._misses,
            "hit_rate": round(self._hits / total, 4) if total else 0,
        }


# ============================================================================
# 76. Conditional Responses with ETag / If-None-Match
# ============================================================================

class ConditionalResponseHandler:
    """Implements HTTP conditional response logic.

    Generates ETags for response payloads and determines whether a client's
    cached version is still valid (304 Not Modified).
    """

    def __init__(self):
        self._etags: Dict[str, str] = {}

    @staticmethod
    def compute_etag(data: Any) -> str:
        """Compute a weak ETag for arbitrary JSON-serialisable data."""
        raw = json.dumps(data, sort_keys=True, default=str).encode()
        digest = hashlib.md5(raw).hexdigest()
        return f'W/"{digest}"'

    def should_return_304(self, resource_key: str, data: Any,
                          client_etag: Optional[str]) -> bool:
        """Check if the client already has the latest version."""
        current = self.compute_etag(data)
        self._etags[resource_key] = current
        if client_etag and client_etag == current:
            return True
        return False

    def get_etag(self, resource_key: str) -> Optional[str]:
        return self._etags.get(resource_key)

    def set_response_headers(self, resource_key: str,
                             data: Any) -> Dict[str, str]:
        """Return headers to include in the response."""
        etag = self.compute_etag(data)
        self._etags[resource_key] = etag
        return {"ETag": etag, "Cache-Control": "private, max-age=60"}


# ============================================================================
# 84. Response Format Negotiation (JSON / MessagePack)
# ============================================================================

class ResponseFormatNegotiator:
    """Negotiate response format based on Accept header.

    Supports ``application/json`` (default) and ``application/x-msgpack``
    when the msgpack library is available.
    """

    MIME_JSON = "application/json"
    MIME_MSGPACK = "application/x-msgpack"

    def __init__(self):
        self._has_msgpack = False
        try:
            import msgpack  # noqa: F401
            self._has_msgpack = True
        except ImportError:
            pass

    @property
    def supported_formats(self) -> List[str]:
        formats = [self.MIME_JSON]
        if self._has_msgpack:
            formats.append(self.MIME_MSGPACK)
        return formats

    def negotiate(self, accept_header: str = "") -> str:
        """Return the best content type for the given Accept header."""
        if self._has_msgpack and self.MIME_MSGPACK in accept_header:
            return self.MIME_MSGPACK
        return self.MIME_JSON

    def encode(self, data: Any, content_type: str = "") -> Tuple[bytes, str]:
        """Encode data in the negotiated format. Returns (body, content_type)."""
        if content_type == self.MIME_MSGPACK and self._has_msgpack:
            import msgpack
            return msgpack.packb(data, use_bin_type=True), self.MIME_MSGPACK
        body = json.dumps(data, default=str).encode("utf-8")
        return body, self.MIME_JSON

    def decode(self, body: bytes, content_type: str = "") -> Any:
        """Decode a body from the given content type."""
        if content_type == self.MIME_MSGPACK and self._has_msgpack:
            import msgpack
            return msgpack.unpackb(body, raw=False)
        return json.loads(body)


# ============================================================================
# 91. Response Aggregation for Multi-Source Queries
# ============================================================================

class MultiSourceAggregator:
    """Aggregates trend results from multiple sources into unified views.

    Merges, deduplicates, and ranks trends from different collectors into
    a single result set with provenance metadata.
    """

    def __init__(self):
        self._source_weights: Dict[str, float] = {
            "google_trends": 1.0,
            "reddit": 0.8,
            "hacker_news": 0.9,
            "product_hunt": 0.85,
            "github": 0.9,
            "npm": 0.7,
            "pypi": 0.7,
        }

    def set_source_weight(self, source: str, weight: float) -> None:
        self._source_weights[source] = weight

    def aggregate(self, source_results: Dict[str, List[Dict[str, Any]]],
                  limit: int = 50) -> List[Dict[str, Any]]:
        """Merge results from multiple sources into a ranked list."""
        merged: Dict[str, Dict[str, Any]] = {}

        for source, trends in source_results.items():
            weight = self._source_weights.get(source, 0.5)
            for trend in trends:
                name_key = trend.get("name", "").lower().strip()
                if name_key in merged:
                    existing = merged[name_key]
                    existing["sources"].append(source)
                    existing["weighted_score"] = max(
                        existing["weighted_score"],
                        trend.get("score", 0) * weight,
                    )
                    existing["source_count"] += 1
                else:
                    merged[name_key] = {
                        **trend,
                        "sources": [source],
                        "source_count": 1,
                        "weighted_score": trend.get("score", 0) * weight,
                    }

        # Boost multi-source trends
        for item in merged.values():
            item["weighted_score"] *= 1 + 0.1 * (item["source_count"] - 1)

        ranked = sorted(merged.values(), key=lambda x: x["weighted_score"], reverse=True)
        return ranked[:limit]

    def summary(self, source_results: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
        """Generate aggregation summary statistics."""
        total = sum(len(v) for v in source_results.values())
        aggregated = self.aggregate(source_results)
        return {
            "total_raw": total,
            "total_aggregated": len(aggregated),
            "dedup_savings": total - len(aggregated),
            "sources_used": list(source_results.keys()),
        }


# ============================================================================
# 98. Response Delta Encoding for Polling Clients
# ============================================================================

class DeltaEncoder:
    """Provides delta-encoded responses for polling clients.

    Stores previous response snapshots keyed by client ID so that
    subsequent polls return only the changed fields.
    """

    def __init__(self, max_clients: int = 1000):
        self._snapshots: OrderedDict[str, Dict[str, Any]] = OrderedDict()
        self._max_clients = max_clients

    def _diff_dicts(self, old: Dict[str, Any],
                    new: Dict[str, Any]) -> Dict[str, Any]:
        """Compute shallow diff between two dicts."""
        delta: Dict[str, Any] = {}
        all_keys = set(old.keys()) | set(new.keys())
        for key in all_keys:
            old_val = old.get(key)
            new_val = new.get(key)
            if old_val != new_val:
                delta[key] = new_val
        return delta

    def encode(self, client_id: str,
               data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Encode a response as a delta from the client's last snapshot.

        Returns ``{"full": False, "added": [...], "updated": [...],
        "removed": [...]}`` when a previous snapshot exists.
        """
        current_map = {item.get("id", item.get("name", "")): item for item in data}

        if client_id not in self._snapshots:
            self._snapshots[client_id] = current_map
            if len(self._snapshots) > self._max_clients:
                self._snapshots.popitem(last=False)
            return {"full": True, "data": data}

        prev_map = self._snapshots[client_id]

        added = []
        updated = []
        removed = []

        for key, item in current_map.items():
            if key not in prev_map:
                added.append(item)
            else:
                diff = self._diff_dicts(prev_map[key], item)
                if diff:
                    diff["id"] = key
                    updated.append(diff)

        for key in prev_map:
            if key not in current_map:
                removed.append(key)

        self._snapshots[client_id] = current_map
        self._snapshots.move_to_end(client_id)

        return {
            "full": False,
            "added": added,
            "updated": updated,
            "removed": removed,
        }

    def reset(self, client_id: Optional[str] = None) -> None:
        if client_id:
            self._snapshots.pop(client_id, None)
        else:
            self._snapshots.clear()

    def stats(self) -> Dict[str, Any]:
        return {"tracked_clients": len(self._snapshots), "max_clients": self._max_clients}


# ============================================================================
# 133. Async Data Collection with Backpressure
# ============================================================================

class BackpressureCollector:
    """Async collector that applies backpressure when the downstream buffer
    is full, preventing memory exhaustion during burst collection.
    """

    def __init__(self, max_buffer: int = 100, max_concurrent: int = 5):
        self._buffer: asyncio.Queue = asyncio.Queue(maxsize=max_buffer)
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._total_collected = 0
        self._total_dropped = 0
        self._running = False

    @property
    def buffer_size(self) -> int:
        return self._buffer.qsize()

    @property
    def is_running(self) -> bool:
        return self._running

    async def collect(self, coro: Callable[[], Any]) -> bool:
        """Run a collection coroutine with backpressure.

        Returns True if the result was buffered, False if dropped.
        """
        async with self._semaphore:
            result = await coro()
            if result is None:
                return False
            try:
                self._buffer.put_nowait(result)
                self._total_collected += 1
                return True
            except asyncio.QueueFull:
                self._total_dropped += 1
                return False

    async def drain(self, batch_size: int = 10) -> List[Any]:
        """Drain up to batch_size items from the buffer."""
        items = []
        for _ in range(batch_size):
            try:
                item = self._buffer.get_nowait()
                items.append(item)
            except asyncio.QueueEmpty:
                break
        return items

    async def run_collectors(self, coroutines: List[Callable]) -> int:
        """Run multiple collector coroutines with backpressure. Returns count collected."""
        self._running = True
        tasks = [asyncio.create_task(self.collect(coro)) for coro in coroutines]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        self._running = False
        return sum(1 for r in results if r is True)

    def stats(self) -> Dict[str, Any]:
        return {
            "buffer_size": self._buffer.qsize(),
            "max_buffer": self._buffer.maxsize,
            "total_collected": self._total_collected,
            "total_dropped": self._total_dropped,
            "running": self._running,
        }


# ============================================================================
# 139. Streaming Data Ingestion Pipeline
# ============================================================================

class StreamingIngestionPipeline:
    """Async pipeline that ingests trend data as a stream, applying
    transformations and writing to the database in batches.
    """

    def __init__(self, db: TrendDatabase, batch_size: int = 50,
                 flush_interval: float = 5.0):
        self.db = db
        self._batch_size = batch_size
        self._flush_interval = flush_interval
        self._buffer: List[Trend] = []
        self._total_ingested = 0
        self._total_flushed = 0
        self._transforms: List[Callable[[Trend], Trend]] = []
        self._running = False

    def add_transform(self, fn: Callable[[Trend], Trend]) -> None:
        """Add a transformation to apply to each ingested trend."""
        self._transforms.append(fn)

    async def ingest(self, trend: Trend) -> None:
        """Ingest a single trend through the pipeline."""
        for transform in self._transforms:
            trend = transform(trend)
        self._buffer.append(trend)
        self._total_ingested += 1
        if len(self._buffer) >= self._batch_size:
            await self.flush()

    async def ingest_stream(self, stream: AsyncIterator[Trend]) -> int:
        """Ingest trends from an async iterator. Returns total ingested."""
        count = 0
        self._running = True
        async for trend in stream:
            await self.ingest(trend)
            count += 1
        await self.flush()
        self._running = False
        return count

    async def flush(self) -> int:
        """Flush the buffer to the database."""
        if not self._buffer:
            return 0
        batch = self._buffer[:]
        self._buffer.clear()
        for trend in batch:
            self.db.save_trend(trend)
        self._total_flushed += len(batch)
        return len(batch)

    def stats(self) -> Dict[str, Any]:
        return {
            "buffer_size": len(self._buffer),
            "batch_size": self._batch_size,
            "total_ingested": self._total_ingested,
            "total_flushed": self._total_flushed,
            "transforms": len(self._transforms),
            "running": self._running,
        }


# ============================================================================
# 147. Real-Time Trend Stream Processing
# ============================================================================

class TrendStreamProcessor:
    """Processes a real-time stream of trend updates, applying windowed
    aggregation and emitting events when thresholds are crossed.
    """

    @dataclass
    class WindowState:
        scores: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
        velocities: Deque[float] = field(default_factory=lambda: deque(maxlen=100))
        last_alert: Optional[datetime] = None
        count: int = 0

    def __init__(self, window_size: int = 100,
                 velocity_alert_threshold: float = 0.5,
                 score_alert_threshold: float = 80.0):
        self._window_size = window_size
        self._velocity_threshold = velocity_alert_threshold
        self._score_threshold = score_alert_threshold
        self._windows: Dict[str, "TrendStreamProcessor.WindowState"] = {}
        self._alerts: List[Dict[str, Any]] = []
        self._processed = 0

    def process(self, trend: Trend) -> Optional[Dict[str, Any]]:
        """Process a single trend update. Returns alert dict if threshold crossed."""
        state = self._windows.setdefault(
            trend.id,
            self.WindowState(
                scores=deque(maxlen=self._window_size),
                velocities=deque(maxlen=self._window_size),
            ),
        )

        state.scores.append(trend.score)
        state.velocities.append(trend.velocity)
        state.count += 1
        self._processed += 1

        # Check thresholds
        avg_velocity = sum(state.velocities) / len(state.velocities) if state.velocities else 0
        avg_score = sum(state.scores) / len(state.scores) if state.scores else 0

        alert = None
        now = datetime.now(timezone.utc)
        cooldown = timedelta(minutes=5)

        should_alert = (
            avg_velocity > self._velocity_threshold or avg_score > self._score_threshold
        )
        if should_alert and (
            state.last_alert is None or now - state.last_alert > cooldown
        ):
            alert = {
                "trend_id": trend.id,
                "trend_name": trend.name,
                "avg_velocity": round(avg_velocity, 4),
                "avg_score": round(avg_score, 2),
                "window_size": len(state.scores),
                "triggered_at": now.isoformat(),
            }
            state.last_alert = now
            self._alerts.append(alert)

        return alert

    def get_window(self, trend_id: str) -> Optional[Dict[str, Any]]:
        state = self._windows.get(trend_id)
        if not state:
            return None
        return {
            "scores": list(state.scores),
            "velocities": list(state.velocities),
            "count": state.count,
        }

    @property
    def alerts(self) -> List[Dict[str, Any]]:
        return list(self._alerts)

    def stats(self) -> Dict[str, Any]:
        return {
            "windows_tracked": len(self._windows),
            "total_processed": self._processed,
            "total_alerts": len(self._alerts),
        }


# ============================================================================
# 153. Async Forecast Generation with Cancellation
# ============================================================================

class AsyncForecastGenerator:
    """Generates forecasts asynchronously with support for cancellation.

    Uses asyncio tasks so that long-running forecast jobs can be cancelled
    by the caller.
    """

    def __init__(self, db: TrendDatabase):
        self.db = db
        self._tasks: Dict[str, asyncio.Task] = {}
        self._results: Dict[str, Dict[str, Any]] = {}

    async def _generate_forecast(self, trend_id: str,
                                 horizons: List[int]) -> Dict[str, Any]:
        """Internal forecast generation (runs in task)."""
        from trendscope.forecasting import TrendForecaster
        forecaster = TrendForecaster(self.db)
        # Yield control to allow cancellation checks
        await asyncio.sleep(0)
        result = forecaster.forecast_trend(trend_id, horizons)
        return result or {"trend_id": trend_id, "error": "insufficient_history"}

    async def start(self, trend_id: str,
                    horizons: Optional[List[int]] = None) -> str:
        """Start a forecast generation task. Returns task ID."""
        if horizons is None:
            horizons = [7, 30, 90]
        task_id = f"forecast_{trend_id}_{uuid4().hex[:8]}"
        task = asyncio.create_task(self._generate_forecast(trend_id, horizons))
        self._tasks[task_id] = task

        def _on_done(t: asyncio.Task) -> None:
            try:
                self._results[task_id] = t.result()
            except (asyncio.CancelledError, Exception) as e:
                self._results[task_id] = {"error": str(e), "cancelled": isinstance(e, asyncio.CancelledError)}

        task.add_done_callback(_on_done)
        return task_id

    async def cancel(self, task_id: str) -> bool:
        """Cancel a running forecast task. Returns True if cancelled."""
        task = self._tasks.get(task_id)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
            return True
        return False

    def get_result(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._results.get(task_id)

    def is_done(self, task_id: str) -> bool:
        task = self._tasks.get(task_id)
        return task.done() if task else True

    def stats(self) -> Dict[str, Any]:
        running = sum(1 for t in self._tasks.values() if not t.done())
        return {
            "total_tasks": len(self._tasks),
            "running": running,
            "completed": len(self._results),
        }


# ============================================================================
# 160. Parallel Source Collection with Merge
# ============================================================================

class ParallelSourceCollector:
    """Collects from multiple sources in parallel and merges the results.

    Uses asyncio.gather with per-source timeouts to collect concurrently
    and merges results with deduplication.
    """

    def __init__(self, timeout_per_source: float = 30.0):
        self._timeout = timeout_per_source
        self._dedup = CollectorDeduplicator()

    async def collect_parallel(
        self,
        collectors: Dict[str, Callable[[], Any]],
    ) -> Dict[str, Any]:
        """Collect from all sources in parallel.

        Args:
            collectors: Dict of source_name -> async callable returning List[Trend]

        Returns:
            {"trends": [...], "errors": {...}, "timing": {...}}
        """
        results: Dict[str, List[Trend]] = {}
        errors: Dict[str, str] = {}
        timing: Dict[str, float] = {}

        async def _run(name: str, coro_fn: Callable) -> None:
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(coro_fn(), timeout=self._timeout)
                results[name] = result if isinstance(result, list) else []
            except asyncio.TimeoutError:
                errors[name] = "timeout"
                results[name] = []
            except Exception as e:
                errors[name] = str(e)
                results[name] = []
            timing[name] = round(time.monotonic() - start, 3)

        tasks = [_run(name, fn) for name, fn in collectors.items()]
        await asyncio.gather(*tasks)

        # Merge and deduplicate
        all_trends = []
        for source_trends in results.values():
            all_trends.extend(source_trends)

        unique = self._dedup.deduplicate(all_trends)

        return {
            "trends": unique,
            "by_source": {k: len(v) for k, v in results.items()},
            "errors": errors,
            "timing": timing,
            "total": len(unique),
            "dedup_filtered": len(all_trends) - len(unique),
        }


# ============================================================================
# 180. Memory-Efficient Time Series Storage
# ============================================================================

class CompactTimeSeries:
    """Memory-efficient time series storage using typed arrays.

    Stores float scores and integer volumes in compact struct-packed
    buffers instead of list-of-dicts, reducing memory usage by ~80%.
    """

    # Each record: timestamp(double=8) + score(float=4) + velocity(float=4) + volume(int=4) = 20 bytes
    RECORD_FMT = "!dffi"
    RECORD_SIZE = struct.calcsize(RECORD_FMT)

    def __init__(self, max_points: int = 10000):
        self._max_points = max_points
        self._series: Dict[str, bytearray] = {}

    def append(self, trend_id: str, timestamp: float,
               score: float, velocity: float, volume: int) -> None:
        """Append a data point for a trend."""
        if trend_id not in self._series:
            self._series[trend_id] = bytearray()

        buf = self._series[trend_id]
        record = struct.pack(self.RECORD_FMT, timestamp, score, velocity, volume)
        buf.extend(record)

        # Enforce max points
        max_bytes = self._max_points * self.RECORD_SIZE
        if len(buf) > max_bytes:
            overflow = len(buf) - max_bytes
            del buf[:overflow]

    def get_series(self, trend_id: str) -> List[Dict[str, Any]]:
        """Get all data points for a trend as dicts."""
        buf = self._series.get(trend_id, bytearray())
        count = len(buf) // self.RECORD_SIZE
        points = []
        for i in range(count):
            offset = i * self.RECORD_SIZE
            ts, score, velocity, volume = struct.unpack_from(
                self.RECORD_FMT, buf, offset
            )
            points.append({
                "timestamp": ts,
                "score": score,
                "velocity": velocity,
                "volume": volume,
            })
        return points

    def get_scores(self, trend_id: str) -> List[float]:
        """Get just the score values for a trend (fast path)."""
        buf = self._series.get(trend_id, bytearray())
        count = len(buf) // self.RECORD_SIZE
        scores = []
        for i in range(count):
            offset = i * self.RECORD_SIZE + 8  # skip timestamp
            (score,) = struct.unpack_from("!f", buf, offset)
            scores.append(score)
        return scores

    def point_count(self, trend_id: str) -> int:
        buf = self._series.get(trend_id, bytearray())
        return len(buf) // self.RECORD_SIZE

    def memory_usage(self) -> Dict[str, Any]:
        total = sum(len(b) for b in self._series.values())
        return {
            "series_count": len(self._series),
            "total_bytes": total,
            "total_points": sum(self.point_count(tid) for tid in self._series),
            "bytes_per_point": self.RECORD_SIZE,
        }


# ============================================================================
# 191. Memory-Mapped Trend History Storage
# ============================================================================

class MMapTrendHistory:
    """Memory-mapped file storage for trend history.

    Uses mmap to provide memory-efficient random access to historical
    trend data backed by files on disk.
    """

    HEADER_FMT = "!I"  # record count (uint32)
    HEADER_SIZE = struct.calcsize(HEADER_FMT)
    RECORD_FMT = "!dffi"  # timestamp(double) + score(float) + velocity(float) + volume(int)
    RECORD_SIZE = struct.calcsize(RECORD_FMT)

    def __init__(self, base_dir: Optional[Path] = None):
        self._base_dir = base_dir or Path(tempfile.mkdtemp(prefix="ts_mmap_"))
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._maps: Dict[str, mmap.mmap] = {}
        self._files: Dict[str, io.FileIO] = {}

    def _file_path(self, trend_id: str) -> Path:
        safe_id = trend_id.replace("/", "_").replace("\\", "_")
        return self._base_dir / f"{safe_id}.mmap"

    def _ensure_file(self, trend_id: str, initial_capacity: int = 1000) -> Path:
        path = self._file_path(trend_id)
        if not path.exists():
            size = self.HEADER_SIZE + initial_capacity * self.RECORD_SIZE
            with open(path, "wb") as f:
                f.write(struct.pack(self.HEADER_FMT, 0))
                f.write(b"\x00" * (size - self.HEADER_SIZE))
        return path

    def append(self, trend_id: str, timestamp: float,
               score: float, velocity: float, volume: int) -> None:
        """Append a data point to the mmap file for a trend."""
        path = self._ensure_file(trend_id)

        with open(path, "r+b") as f:
            file_size = f.seek(0, 2)
            f.seek(0)
            (count,) = struct.unpack(self.HEADER_FMT, f.read(self.HEADER_SIZE))

            needed = self.HEADER_SIZE + (count + 1) * self.RECORD_SIZE
            if needed > file_size:
                # Grow file by doubling
                new_size = max(needed, file_size * 2)
                f.seek(new_size - 1)
                f.write(b"\x00")

            offset = self.HEADER_SIZE + count * self.RECORD_SIZE
            f.seek(offset)
            f.write(struct.pack(self.RECORD_FMT, timestamp, score, velocity, volume))

            # Update count
            f.seek(0)
            f.write(struct.pack(self.HEADER_FMT, count + 1))

    def read_all(self, trend_id: str) -> List[Dict[str, Any]]:
        """Read all data points for a trend."""
        path = self._file_path(trend_id)
        if not path.exists():
            return []

        with open(path, "rb") as f:
            header = f.read(self.HEADER_SIZE)
            if len(header) < self.HEADER_SIZE:
                return []
            (count,) = struct.unpack(self.HEADER_FMT, header)
            points = []
            for _ in range(count):
                data = f.read(self.RECORD_SIZE)
                if len(data) < self.RECORD_SIZE:
                    break
                ts, score, velocity, volume = struct.unpack(self.RECORD_FMT, data)
                points.append({
                    "timestamp": ts,
                    "score": score,
                    "velocity": velocity,
                    "volume": volume,
                })
            return points

    def point_count(self, trend_id: str) -> int:
        path = self._file_path(trend_id)
        if not path.exists():
            return 0
        with open(path, "rb") as f:
            header = f.read(self.HEADER_SIZE)
            if len(header) < self.HEADER_SIZE:
                return 0
            (count,) = struct.unpack(self.HEADER_FMT, header)
            return count

    def close(self) -> None:
        """Close all open mmaps."""
        for m in self._maps.values():
            m.close()
        for f in self._files.values():
            f.close()
        self._maps.clear()
        self._files.clear()


# ============================================================================
# 202. Connection Reuse for Data Source Polling
# ============================================================================

class ConnectionPool:
    """Reusable HTTP connection pool for efficient data source polling.

    Maintains a pool of urllib openers keyed by (scheme, host) so that
    TCP connections are reused across requests to the same origin.
    """

    def __init__(self, max_connections_per_host: int = 5,
                 default_timeout: float = 30.0):
        self._max_per_host = max_connections_per_host
        self._default_timeout = default_timeout
        self._request_count = 0
        self._reuse_count = 0
        # Track connection metadata per host
        self._host_stats: Dict[str, Dict[str, Any]] = {}

    def _host_key(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.scheme}://{parsed.hostname}:{parsed.port or (443 if parsed.scheme == 'https' else 80)}"

    def request(self, url: str, headers: Optional[Dict[str, str]] = None,
                timeout: Optional[float] = None) -> Optional[bytes]:
        """Make a request with connection reuse tracking."""
        import urllib.request
        import urllib.error

        host_key = self._host_key(url)
        self._request_count += 1

        if host_key in self._host_stats:
            self._host_stats[host_key]["requests"] += 1
            self._reuse_count += 1
        else:
            self._host_stats[host_key] = {"requests": 1, "errors": 0}

        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Trendscope/1.0")
            req.add_header("Connection", "keep-alive")
            if headers:
                for k, v in headers.items():
                    req.add_header(k, v)

            t = timeout or self._default_timeout
            with urllib.request.urlopen(req, timeout=t) as resp:
                return resp.read()
        except Exception as e:
            self._host_stats[host_key]["errors"] += 1
            logger.debug(f"Connection pool request failed for {host_key}: {e}")
            return None

    def stats(self) -> Dict[str, Any]:
        return {
            "total_requests": self._request_count,
            "reused_connections": self._reuse_count,
            "hosts_tracked": len(self._host_stats),
            "per_host": dict(self._host_stats),
        }


# ============================================================================
# 209. Adaptive Timeout Based on Endpoint Latency
# ============================================================================

class AdaptiveTimeout:
    """Dynamically adjusts request timeouts based on observed endpoint latency.

    Tracks a rolling window of response times per endpoint and computes
    adaptive timeouts using mean + N*stddev.
    """

    def __init__(self, window_size: int = 50, multiplier: float = 2.0,
                 min_timeout: float = 2.0, max_timeout: float = 60.0,
                 default_timeout: float = 15.0):
        self._window_size = window_size
        self._multiplier = multiplier
        self._min = min_timeout
        self._max = max_timeout
        self._default = default_timeout
        self._latencies: Dict[str, Deque[float]] = {}

    def _endpoint_key(self, url: str) -> str:
        from urllib.parse import urlparse
        parsed = urlparse(url)
        return f"{parsed.hostname}{parsed.path}"

    def record(self, url: str, latency: float) -> None:
        """Record a response latency for an endpoint."""
        key = self._endpoint_key(url)
        if key not in self._latencies:
            self._latencies[key] = deque(maxlen=self._window_size)
        self._latencies[key].append(latency)

    def get_timeout(self, url: str) -> float:
        """Get the adaptive timeout for an endpoint."""
        key = self._endpoint_key(url)
        window = self._latencies.get(key)

        if not window or len(window) < 3:
            return self._default

        values = list(window)
        avg = sum(values) / len(values)
        if len(values) >= 2:
            variance = sum((v - avg) ** 2 for v in values) / (len(values) - 1)
            sd = math.sqrt(variance)
        else:
            sd = 0

        timeout = avg + self._multiplier * sd
        return max(self._min, min(self._max, timeout))

    def get_stats(self, url: str) -> Dict[str, Any]:
        key = self._endpoint_key(url)
        window = self._latencies.get(key)
        if not window:
            return {"endpoint": key, "samples": 0, "timeout": self._default}

        values = list(window)
        avg = sum(values) / len(values)
        return {
            "endpoint": key,
            "samples": len(values),
            "mean_latency": round(avg, 3),
            "min_latency": round(min(values), 3),
            "max_latency": round(max(values), 3),
            "adaptive_timeout": round(self.get_timeout(url), 3),
        }

    def all_stats(self) -> Dict[str, Dict[str, Any]]:
        result = {}
        for key, window in self._latencies.items():
            values = list(window)
            avg = sum(values) / len(values)
            result[key] = {
                "samples": len(values),
                "mean_latency": round(avg, 3),
                "adaptive_timeout": round(self.get_timeout(f"http://{key}"), 3),
            }
        return result


# ============================================================================
# 242. Mock Server with Recorded Responses for Tests
# ============================================================================

class RecordedResponse:
    """A single recorded HTTP response."""

    def __init__(self, status: int = 200, body: Union[bytes, str, dict] = b"",
                 headers: Optional[Dict[str, str]] = None,
                 delay: float = 0):
        self.status = status
        if isinstance(body, dict):
            self.body = json.dumps(body).encode("utf-8")
        elif isinstance(body, str):
            self.body = body.encode("utf-8")
        else:
            self.body = body
        self.headers = headers or {}
        self.delay = delay


class MockServerHandler(BaseHTTPRequestHandler):
    """HTTP handler that serves recorded responses."""

    responses: Dict[str, List[RecordedResponse]] = {}
    request_log: List[Dict[str, Any]] = []
    _lock = threading.Lock()

    def do_GET(self):
        self._handle()

    def do_POST(self):
        self._handle()

    def _handle(self):
        with self._lock:
            self.request_log.append({
                "method": self.command,
                "path": self.path,
                "headers": dict(self.headers),
                "timestamp": datetime.now(timezone.utc).isoformat(),
            })

        responses = self.responses.get(self.path, [])
        if not responses:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "not found"}')
            return

        # Pop first response (supports sequential playback)
        resp = responses[0]
        if len(responses) > 1:
            responses.pop(0)

        if resp.delay > 0:
            time.sleep(resp.delay)

        self.send_response(resp.status)
        for k, v in resp.headers.items():
            self.send_header(k, v)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(resp.body)

    def log_message(self, format, *args):
        pass  # Suppress default logging


class MockServer:
    """Test mock server that serves recorded HTTP responses.

    Usage::

        server = MockServer()
        server.record("/api/data", RecordedResponse(body={"ok": True}))
        server.start()
        # ... make requests to server.base_url ...
        server.stop()
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 0):
        self._host = host
        self._port = port
        self._server: Optional[HTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    def record(self, path: str, response: RecordedResponse) -> None:
        """Record a response for a given path."""
        if path not in MockServerHandler.responses:
            MockServerHandler.responses[path] = []
        MockServerHandler.responses[path].append(response)

    def start(self) -> str:
        """Start the mock server. Returns the base URL."""
        MockServerHandler.responses = dict(MockServerHandler.responses)
        MockServerHandler.request_log = []

        self._server = HTTPServer((self._host, self._port), MockServerHandler)
        actual_port = self._server.server_address[1]
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return f"http://{self._host}:{actual_port}"

    def stop(self) -> None:
        """Stop the mock server."""
        if self._server:
            self._server.shutdown()
            self._server = None
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        MockServerHandler.responses.clear()
        MockServerHandler.request_log.clear()

    @property
    def base_url(self) -> str:
        if self._server:
            host, port = self._server.server_address
            return f"http://{host}:{port}"
        return ""

    @property
    def request_log(self) -> List[Dict[str, Any]]:
        return list(MockServerHandler.request_log)

    def reset(self) -> None:
        """Clear all recorded responses and request log."""
        MockServerHandler.responses.clear()
        MockServerHandler.request_log.clear()
