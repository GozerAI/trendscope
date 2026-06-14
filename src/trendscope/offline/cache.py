"""Offline trend data cache with TTL-based expiration and staleness tracking."""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional
from uuid import uuid4

from trendscope.core import Trend, TrendSource

logger = logging.getLogger(__name__)

DEFAULT_CACHE_TTL_HOURS = 24
MAX_STALE_HOURS = 72

_EMPTY_JSON = "{}"


@dataclass
class CachedTrendData:
    """A cached snapshot of trend data with freshness metadata."""

    trend_id: str
    trend_name: str
    category: str = ""
    source: str = ""
    score: float = 0.0
    velocity: float = 0.0
    momentum: float = 0.0
    volume: int = 0
    history: List[Dict[str, Any]] = field(default_factory=list)
    raw_data: Dict[str, Any] = field(default_factory=dict)
    cached_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_hours: float = DEFAULT_CACHE_TTL_HOURS
    access_count: int = 0

    @property
    def age_hours(self) -> float:
        """Hours since this entry was cached."""
        delta = datetime.now(timezone.utc) - self.cached_at
        return delta.total_seconds() / 3600

    @property
    def is_fresh(self) -> bool:
        """Whether this cache entry is within its TTL."""
        return self.age_hours < self.ttl_hours

    @property
    def is_stale(self) -> bool:
        """Whether this cache entry has exceeded the maximum staleness window."""
        return self.age_hours >= MAX_STALE_HOURS

    @property
    def freshness_score(self) -> float:
        """0.0 (completely stale) to 1.0 (just cached). Linearly decays."""
        if self.age_hours <= 0:
            return 1.0
        if self.age_hours >= MAX_STALE_HOURS:
            return 0.0
        return max(0.0, 1.0 - (self.age_hours / MAX_STALE_HOURS))

    def to_trend(self) -> Trend:
        """Convert cached data back to a Trend object."""
        return Trend(
            id=self.trend_id,
            name=self.trend_name,
            category=_safe_enum(self.category, "emerging"),
            source=_safe_source(self.source, "custom"),
            score=self.score,
            velocity=self.velocity,
            momentum=self.momentum,
            volume=self.volume,
            history=self.history,
            raw_data=self.raw_data,
            data_quality=self.freshness_score,
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend_id": self.trend_id,
            "trend_name": self.trend_name,
            "category": self.category,
            "source": self.source,
            "score": self.score,
            "velocity": self.velocity,
            "momentum": self.momentum,
            "volume": self.volume,
            "history": self.history,
            "raw_data": self.raw_data,
            "cached_at": self.cached_at.isoformat(),
            "ttl_hours": self.ttl_hours,
            "access_count": self.access_count,
            "is_fresh": self.is_fresh,
            "freshness_score": round(self.freshness_score, 3),
        }


def _safe_enum(value: str, default: str) -> Any:
    """Safely convert string to TrendCategory."""
    from trendscope.core import TrendCategory
    try:
        return TrendCategory(value)
    except (ValueError, KeyError):
        return TrendCategory(default)


def _safe_source(value: str, default: str) -> Any:
    """Safely convert string to TrendSource."""
    try:
        return TrendSource(value)
    except (ValueError, KeyError):
        return TrendSource(default)


class OfflineTrendCache:
    """SQLite-backed offline cache for trend data.

    Stores trend snapshots with TTL-based expiration so analysis can continue
    when external data sources are unreachable.
    """

    def __init__(self, db_path: Optional[Path] = None, default_ttl_hours: float = DEFAULT_CACHE_TTL_HOURS):
        if db_path is None:
            data_dir = Path(__file__).parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "offline_cache.db"
        self.db_path = db_path
        self.default_ttl_hours = default_ttl_hours
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS trend_cache (
                        trend_id TEXT PRIMARY KEY,
                        trend_name TEXT NOT NULL,
                        category TEXT DEFAULT '',
                        source TEXT DEFAULT '',
                        score REAL DEFAULT 0,
                        velocity REAL DEFAULT 0,
                        momentum REAL DEFAULT 0,
                        volume INTEGER DEFAULT 0,
                        history TEXT DEFAULT '[]',
                        raw_data TEXT DEFAULT '{}',
                        cached_at TEXT NOT NULL,
                        ttl_hours REAL DEFAULT 24,
                        access_count INTEGER DEFAULT 0
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_source ON trend_cache(source)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_cache_category ON trend_cache(category)
                """)

    def store(self, trend: Trend, ttl_hours: Optional[float] = None) -> CachedTrendData:
        """Cache a trend snapshot."""
        ttl = ttl_hours if ttl_hours is not None else self.default_ttl_hours
        now = datetime.now(timezone.utc)
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO trend_cache
                    (trend_id, trend_name, category, source, score, velocity, momentum,
                     volume, history, raw_data, cached_at, ttl_hours, access_count)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
                """, (
                    trend.id, trend.name,
                    trend.category.value if hasattr(trend.category, "value") else str(trend.category),
                    trend.source.value if hasattr(trend.source, "value") else str(trend.source),
                    trend.score, trend.velocity, trend.momentum, trend.volume,
                    json.dumps(trend.history), json.dumps(trend.raw_data),
                    now.isoformat(), ttl,
                ))
        return CachedTrendData(
            trend_id=trend.id,
            trend_name=trend.name,
            category=trend.category.value if hasattr(trend.category, "value") else str(trend.category),
            source=trend.source.value if hasattr(trend.source, "value") else str(trend.source),
            score=trend.score,
            velocity=trend.velocity,
            momentum=trend.momentum,
            volume=trend.volume,
            history=trend.history,
            raw_data=trend.raw_data,
            cached_at=now,
            ttl_hours=ttl,
        )

    def store_many(self, trends: List[Trend], ttl_hours: Optional[float] = None) -> int:
        """Cache multiple trends. Returns count stored."""
        count = 0
        for trend in trends:
            self.store(trend, ttl_hours=ttl_hours)
            count += 1
        return count

    def get(self, trend_id: str) -> Optional[CachedTrendData]:
        """Retrieve a cached trend (even if stale). Returns None if not found."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM trend_cache WHERE trend_id = ?", (trend_id,)
                ).fetchone()
                if row is None:
                    return None
                conn.execute(
                    "UPDATE trend_cache SET access_count = access_count + 1 WHERE trend_id = ?",
                    (trend_id,),
                )
        return self._row_to_cached(row)

    def get_fresh(self, trend_id: str) -> Optional[CachedTrendData]:
        """Get a cached trend only if it is still within TTL."""
        entry = self.get(trend_id)
        if entry and entry.is_fresh:
            return entry
        return None

    def get_by_source(self, source: str) -> List[CachedTrendData]:
        """Get all cached trends for a given source."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM trend_cache WHERE source = ?", (source,)
                ).fetchall()
        return [self._row_to_cached(r) for r in rows]

    def get_by_category(self, category: str) -> List[CachedTrendData]:
        """Get all cached trends for a given category."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM trend_cache WHERE category = ?", (category,)
                ).fetchall()
        return [self._row_to_cached(r) for r in rows]

    def get_all(self, fresh_only: bool = False) -> List[CachedTrendData]:
        """Get all cached trends."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM trend_cache").fetchall()
        entries = [self._row_to_cached(r) for r in rows]
        if fresh_only:
            entries = [e for e in entries if e.is_fresh]
        return entries

    def evict_stale(self) -> int:
        """Remove all entries past MAX_STALE_HOURS. Returns count removed."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=MAX_STALE_HOURS)).isoformat()
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "DELETE FROM trend_cache WHERE cached_at < ?", (cutoff,)
                )
                return cursor.rowcount

    def clear(self) -> int:
        """Remove all cached entries. Returns count removed."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute("DELETE FROM trend_cache")
                return cursor.rowcount

    def stats(self) -> Dict[str, Any]:
        """Return cache statistics."""
        entries = self.get_all()
        fresh = [e for e in entries if e.is_fresh]
        stale = [e for e in entries if e.is_stale]
        return {
            "total_entries": len(entries),
            "fresh_entries": len(fresh),
            "stale_entries": len(stale),
            "degraded_entries": len(entries) - len(fresh) - len(stale),
            "sources": list(set(e.source for e in entries)),
            "avg_freshness": (
                round(sum(e.freshness_score for e in entries) / len(entries), 3)
                if entries else 0.0
            ),
        }

    def _row_to_cached(self, row: sqlite3.Row) -> CachedTrendData:
        cached_at_str = row["cached_at"]
        if isinstance(cached_at_str, str):
            cached_at = datetime.fromisoformat(cached_at_str.replace("Z", "+00:00"))
            if cached_at.tzinfo is None:
                cached_at = cached_at.replace(tzinfo=timezone.utc)
        else:
            cached_at = datetime.now(timezone.utc)

        return CachedTrendData(
            trend_id=row["trend_id"],
            trend_name=row["trend_name"],
            category=row["category"] or "",
            source=row["source"] or "",
            score=row["score"] or 0.0,
            velocity=row["velocity"] or 0.0,
            momentum=row["momentum"] or 0.0,
            volume=row["volume"] or 0,
            history=json.loads(row["history"] or "[]"),
            raw_data=json.loads(row["raw_data"] or "{}"),
            cached_at=cached_at,
            ttl_hours=row["ttl_hours"] or DEFAULT_CACHE_TTL_HOURS,
            access_count=row["access_count"] or 0,
        )
