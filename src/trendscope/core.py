"""
Trend Intelligence Core - Data models and base analyzer.

Provides the foundational data structures and analysis capabilities
for trend tracking and market intelligence.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

logger = logging.getLogger(__name__)


# ============================================================
# Signal Scoring Constants
# ============================================================
# These weights are used to calculate composite signal scores
# They should sum to 1.0 for proper normalization

SIGNAL_WEIGHT_VELOCITY = 0.3  # How fast the trend is growing
SIGNAL_WEIGHT_MOMENTUM = 0.3  # Sustained growth over time
SIGNAL_WEIGHT_MARKET_OPPORTUNITY = 0.2  # Market size and potential
SIGNAL_WEIGHT_COMPETITION = 0.1  # Lower competition = higher score
SIGNAL_WEIGHT_ENTRY_BARRIER = 0.1  # Lower barrier = higher score

# Signal threshold boundaries (must be in descending order)
SIGNAL_THRESHOLD_STRONG_BUY = 0.8
SIGNAL_THRESHOLD_BUY = 0.6
SIGNAL_THRESHOLD_HOLD = 0.4
SIGNAL_THRESHOLD_SELL = 0.2

# Velocity thresholds for trend status classification
VELOCITY_THRESHOLD_EMERGING = 0.5  # Rapid growth
VELOCITY_THRESHOLD_GROWING = 0.2  # Moderate growth
VELOCITY_THRESHOLD_STABLE_LOW = -0.2  # Minor decline still considered stable
VELOCITY_THRESHOLD_DECLINING = -0.5  # Significant decline

# Default query limits
DEFAULT_TREND_LIMIT = 10
DEFAULT_HISTORY_DAYS = 7
MAX_CORRELATION_TRENDS = 100


class TrendCategory(Enum):
    """Categories for classifying trends."""
    TECHNOLOGY = "technology"
    ECOMMERCE = "ecommerce"
    SOCIAL = "social"
    CULTURAL = "cultural"
    BUSINESS = "business"
    CONSUMER = "consumer"
    LIFESTYLE = "lifestyle"
    HEALTH = "health"
    FINANCE = "finance"
    ENTERTAINMENT = "entertainment"
    NICHE_MARKET = "niche_market"
    EMERGING = "emerging"


class TrendSource(Enum):
    """Sources for trend data collection."""
    GOOGLE_TRENDS = "google_trends"
    REDDIT = "reddit"
    HACKER_NEWS = "hacker_news"
    PRODUCT_HUNT = "product_hunt"
    TWITTER = "twitter"
    YOUTUBE = "youtube"
    TIKTOK = "tiktok"
    NEWS = "news"
    GITHUB = "github"
    NPM = "npm"
    PYPI = "pypi"
    STACK_OVERFLOW = "stack_overflow"
    WIKIPEDIA = "wikipedia"
    INTERNAL = "internal"
    CUSTOM = "custom"


class TrendStatus(Enum):
    """Status of a trend in its lifecycle."""
    EMERGING = "emerging"
    GROWING = "growing"
    PEAK = "peak"
    DECLINING = "declining"
    STABLE = "stable"
    VOLATILE = "volatile"
    UNKNOWN = "unknown"


class TrendSignal(Enum):
    """Trading-style signals for trend action."""
    STRONG_BUY = "strong_buy"
    BUY = "buy"
    HOLD = "hold"
    SELL = "sell"
    STRONG_SELL = "strong_sell"


@dataclass
class Trend:
    """Represents a market or cultural trend."""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    category: TrendCategory = TrendCategory.EMERGING
    source: TrendSource = TrendSource.CUSTOM
    status: TrendStatus = TrendStatus.UNKNOWN

    # Scoring metrics
    score: float = 0.0  # 0-100 composite score
    velocity: float = 0.0  # Rate of change
    momentum: float = 0.0  # Momentum indicator
    volume: int = 0  # Volume of mentions/interest

    # Time series data
    history: List[Dict[str, Any]] = field(default_factory=list)

    # Classification
    keywords: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    related_trends: List[str] = field(default_factory=list)

    # Business relevance
    market_opportunity: float = 0.0  # 0-1 opportunity score
    competition_level: float = 0.0  # 0-1 competition intensity
    entry_barrier: float = 0.0  # 0-1 barrier to entry

    # Metadata
    first_seen: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_updated: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    data_quality: float = 1.0  # 0-1 confidence in data
    raw_data: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    # Credibility weighting
    confidence_multiplier: float = 1.0
    confirmed_by_sources: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "source": self.source.value,
            "status": self.status.value,
            "score": self.score,
            "velocity": self.velocity,
            "momentum": self.momentum,
            "volume": self.volume,
            "keywords": self.keywords,
            "tags": self.tags,
            "related_trends": self.related_trends,
            "market_opportunity": self.market_opportunity,
            "competition_level": self.competition_level,
            "entry_barrier": self.entry_barrier,
            "first_seen": self.first_seen.isoformat() if self.first_seen else None,
            "last_updated": self.last_updated.isoformat() if self.last_updated else None,
            "data_quality": self.data_quality,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trend":
        """Create from dictionary."""
        trend = cls(
            id=data.get("id", str(uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            score=data.get("score", 0.0),
            velocity=data.get("velocity", 0.0),
            momentum=data.get("momentum", 0.0),
            volume=data.get("volume", 0),
            keywords=data.get("keywords", []),
            tags=data.get("tags", []),
            related_trends=data.get("related_trends", []),
            market_opportunity=data.get("market_opportunity", 0.0),
            competition_level=data.get("competition_level", 0.0),
            entry_barrier=data.get("entry_barrier", 0.0),
            data_quality=data.get("data_quality", 1.0),
            raw_data=data.get("raw_data", {}),
            metadata=data.get("metadata", {}),
        )

        # Parse enums
        if "category" in data:
            trend.category = TrendCategory(data["category"]) if isinstance(data["category"], str) else data["category"]
        if "source" in data:
            trend.source = TrendSource(data["source"]) if isinstance(data["source"], str) else data["source"]
        if "status" in data:
            trend.status = TrendStatus(data["status"]) if isinstance(data["status"], str) else data["status"]

        # Parse dates
        if "first_seen" in data and data["first_seen"]:
            if isinstance(data["first_seen"], str):
                trend.first_seen = datetime.fromisoformat(data["first_seen"].replace("Z", "+00:00"))
            else:
                trend.first_seen = data["first_seen"]
        if "last_updated" in data and data["last_updated"]:
            if isinstance(data["last_updated"], str):
                trend.last_updated = datetime.fromisoformat(data["last_updated"].replace("Z", "+00:00"))
            else:
                trend.last_updated = data["last_updated"]

        return trend

    def get_signal(self) -> TrendSignal:
        """Get trading-style signal based on metrics."""
        # Composite signal based on velocity, momentum, and opportunity
        signal_score = (
            self.velocity * SIGNAL_WEIGHT_VELOCITY +
            self.momentum * SIGNAL_WEIGHT_MOMENTUM +
            self.market_opportunity * SIGNAL_WEIGHT_MARKET_OPPORTUNITY +
            (1 - self.competition_level) * SIGNAL_WEIGHT_COMPETITION +
            (1 - self.entry_barrier) * SIGNAL_WEIGHT_ENTRY_BARRIER
        )

        if signal_score >= SIGNAL_THRESHOLD_STRONG_BUY:
            return TrendSignal.STRONG_BUY
        elif signal_score >= SIGNAL_THRESHOLD_BUY:
            return TrendSignal.BUY
        elif signal_score >= SIGNAL_THRESHOLD_HOLD:
            return TrendSignal.HOLD
        elif signal_score >= SIGNAL_THRESHOLD_SELL:
            return TrendSignal.SELL
        else:
            return TrendSignal.STRONG_SELL


@dataclass
class NicheOpportunity:
    """Represents an identified niche market opportunity."""
    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    description: str = ""
    parent_trend_ids: List[str] = field(default_factory=list)

    # Scoring
    opportunity_score: float = 0.0  # 0-100
    confidence: float = 0.0  # 0-1

    # Market characteristics
    estimated_market_size: str = ""  # e.g., "$10M-50M"
    growth_rate: float = 0.0  # Percentage
    competition_density: float = 0.0  # 0-1

    # Product/service fit
    product_ideas: List[str] = field(default_factory=list)
    target_audience: str = ""
    pain_points: List[str] = field(default_factory=list)

    # E-commerce relevance
    storefront_fit: List[str] = field(default_factory=list)  # Which storefronts this fits
    product_categories: List[str] = field(default_factory=list)

    # Timing
    recommended_action: str = ""
    urgency: str = "medium"  # low, medium, high, critical

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "parent_trend_ids": self.parent_trend_ids,
            "opportunity_score": self.opportunity_score,
            "confidence": self.confidence,
            "estimated_market_size": self.estimated_market_size,
            "growth_rate": self.growth_rate,
            "competition_density": self.competition_density,
            "product_ideas": self.product_ideas,
            "target_audience": self.target_audience,
            "pain_points": self.pain_points,
            "storefront_fit": self.storefront_fit,
            "product_categories": self.product_categories,
            "recommended_action": self.recommended_action,
            "urgency": self.urgency,
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class TrendDatabase:
    """SQLite-based trend storage and retrieval."""

    def __init__(self, db_path: Optional[Path] = None):
        """Initialize database."""
        if db_path is None:
            # Default to module data directory
            data_dir = Path(__file__).parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "trends.db"

        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS trends (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    category TEXT,
                    source TEXT,
                    status TEXT,
                    score REAL DEFAULT 0,
                    velocity REAL DEFAULT 0,
                    momentum REAL DEFAULT 0,
                    volume INTEGER DEFAULT 0,
                    keywords TEXT,
                    tags TEXT,
                    market_opportunity REAL DEFAULT 0,
                    competition_level REAL DEFAULT 0,
                    entry_barrier REAL DEFAULT 0,
                    first_seen TEXT,
                    last_updated TEXT,
                    data_quality REAL DEFAULT 1,
                    raw_data TEXT,
                    metadata TEXT
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS trend_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trend_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    score REAL,
                    velocity REAL,
                    momentum REAL,
                    volume INTEGER,
                    FOREIGN KEY (trend_id) REFERENCES trends(id)
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS niches (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    parent_trend_ids TEXT,
                    opportunity_score REAL DEFAULT 0,
                    confidence REAL DEFAULT 0,
                    data TEXT,
                    created_at TEXT
                )
            """)

            # Add credibility columns (safe migration for existing DBs)
            try:
                conn.execute("ALTER TABLE trends ADD COLUMN confidence_multiplier REAL DEFAULT 1.0")
            except Exception:
                pass  # Column already exists
            try:
                conn.execute("ALTER TABLE trends ADD COLUMN confirmed_by_sources TEXT DEFAULT '[]'")
            except Exception:
                pass  # Column already exists

            conn.execute("""
                CREATE TABLE IF NOT EXISTS schedules (
                    id TEXT PRIMARY KEY,
                    name TEXT UNIQUE NOT NULL,
                    interval_minutes REAL NOT NULL,
                    enabled INTEGER DEFAULT 1,
                    last_run TEXT,
                    run_count INTEGER DEFAULT 0,
                    last_status TEXT DEFAULT 'pending',
                    last_error TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    snapshot_data TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)

            conn.execute("""
                CREATE TABLE IF NOT EXISTS lifecycle_transitions (
                    id TEXT PRIMARY KEY,
                    trend_id TEXT NOT NULL,
                    from_stage TEXT,
                    to_stage TEXT NOT NULL,
                    timestamp TEXT DEFAULT (datetime('now')),
                    reason TEXT
                )
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_lifecycle_trend_id
                ON lifecycle_transitions(trend_id)
            """)

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trends_category ON trends(category)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trends_source ON trends(source)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trends_score ON trends(score DESC)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trends_status ON trends(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trend_history_trend_id
                ON trend_history(trend_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_trend_history_timestamp
                ON trend_history(timestamp)
            """)

            conn.commit()

    def save_trend(self, trend: Trend) -> None:
        """Save or update a trend."""
        trend.last_updated = datetime.now(timezone.utc)

        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO trends
                (id, name, description, category, source, status, score, velocity,
                 momentum, volume, keywords, tags, market_opportunity, competition_level,
                 entry_barrier, first_seen, last_updated, data_quality, raw_data, metadata,
                 confidence_multiplier, confirmed_by_sources)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                trend.id,
                trend.name,
                trend.description,
                trend.category.value,
                trend.source.value,
                trend.status.value,
                trend.score,
                trend.velocity,
                trend.momentum,
                trend.volume,
                json.dumps(trend.keywords),
                json.dumps(trend.tags),
                trend.market_opportunity,
                trend.competition_level,
                trend.entry_barrier,
                trend.first_seen.isoformat() if trend.first_seen else None,
                trend.last_updated.isoformat() if trend.last_updated else None,
                trend.data_quality,
                json.dumps(trend.raw_data),
                json.dumps(trend.metadata),
                trend.confidence_multiplier,
                json.dumps(trend.confirmed_by_sources),
            ))

            # Record history point
            conn.execute("""
                INSERT INTO trend_history (trend_id, timestamp, score, velocity, momentum, volume)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                trend.id,
                datetime.now(timezone.utc).isoformat(),
                trend.score,
                trend.velocity,
                trend.momentum,
                trend.volume,
            ))

            conn.commit()

    def get_trend(self, trend_id: str) -> Optional[Trend]:
        """Get a trend by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM trends WHERE id = ?", (trend_id,)
            ).fetchone()

            if row:
                return self._row_to_trend(row)
        return None

    def get_trends(
        self,
        category: Optional[TrendCategory] = None,
        source: Optional[TrendSource] = None,
        min_score: float = 0,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Trend]:
        """Get trends with optional filters."""
        query = "SELECT * FROM trends WHERE score >= ?"
        params: List[Any] = [min_score]

        if category:
            query += " AND category = ?"
            params.append(category.value)
        if source:
            query += " AND source = ?"
            params.append(source.value)

        query += " ORDER BY score DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_trend(row) for row in rows]

    def get_top_trends(self, limit: int = 10) -> List[Trend]:
        """Get top-scoring trends."""
        return self.get_trends(min_score=0, limit=limit)

    def get_emerging_trends(self, limit: int = 10) -> List[Trend]:
        """Get emerging trends with high velocity."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM trends
                WHERE status = 'emerging' OR velocity > 0.5
                ORDER BY velocity DESC, score DESC
                LIMIT ?
            """, (limit,)).fetchall()
            return [self._row_to_trend(row) for row in rows]

    def search_trends(self, query: str, limit: int = 20) -> List[Trend]:
        """Search trends by name or keywords."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM trends
                WHERE name LIKE ? OR description LIKE ? OR keywords LIKE ?
                ORDER BY score DESC
                LIMIT ?
            """, (f"%{query}%", f"%{query}%", f"%{query}%", limit)).fetchall()
            return [self._row_to_trend(row) for row in rows]

    def get_trend_history(
        self,
        trend_id: str,
        days: int = 30,
    ) -> List[Dict[str, Any]]:
        """Get historical data for a trend."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM trend_history
                WHERE trend_id = ? AND timestamp >= ?
                ORDER BY timestamp ASC
            """, (trend_id, cutoff)).fetchall()

            return [dict(row) for row in rows]

    def save_niche(self, niche: NicheOpportunity) -> None:
        """Save a niche opportunity."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO niches
                (id, name, description, parent_trend_ids, opportunity_score, confidence, data, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                niche.id,
                niche.name,
                niche.description,
                json.dumps(niche.parent_trend_ids),
                niche.opportunity_score,
                niche.confidence,
                json.dumps(niche.to_dict()),
                niche.created_at.isoformat() if niche.created_at else None,
            ))
            conn.commit()

    def get_niches(self, min_score: float = 0, limit: int = 20) -> List[NicheOpportunity]:
        """Get niche opportunities."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM niches
                WHERE opportunity_score >= ?
                ORDER BY opportunity_score DESC
                LIMIT ?
            """, (min_score, limit)).fetchall()

            niches = []
            for row in rows:
                data = json.loads(row["data"])
                niche = NicheOpportunity(
                    id=data.get("id", row["id"]),
                    name=data.get("name", row["name"]),
                    description=data.get("description", ""),
                    parent_trend_ids=data.get("parent_trend_ids", []),
                    opportunity_score=data.get("opportunity_score", 0),
                    confidence=data.get("confidence", 0),
                    estimated_market_size=data.get("estimated_market_size", ""),
                    growth_rate=data.get("growth_rate", 0),
                    competition_density=data.get("competition_density", 0),
                    product_ideas=data.get("product_ideas", []),
                    target_audience=data.get("target_audience", ""),
                    pain_points=data.get("pain_points", []),
                    storefront_fit=data.get("storefront_fit", []),
                    product_categories=data.get("product_categories", []),
                    recommended_action=data.get("recommended_action", ""),
                    urgency=data.get("urgency", "medium"),
                )
                niches.append(niche)

            return niches

    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        with sqlite3.connect(self.db_path) as conn:
            total = conn.execute("SELECT COUNT(*) FROM trends").fetchone()[0]
            by_category = dict(conn.execute("""
                SELECT category, COUNT(*) FROM trends GROUP BY category
            """).fetchall())
            by_source = dict(conn.execute("""
                SELECT source, COUNT(*) FROM trends GROUP BY source
            """).fetchall())
            avg_score = conn.execute("SELECT AVG(score) FROM trends").fetchone()[0] or 0
            niches_count = conn.execute("SELECT COUNT(*) FROM niches").fetchone()[0]

            return {
                "total_trends": total,
                "by_category": by_category,
                "by_source": by_source,
                "average_score": round(avg_score, 2),
                "total_niches": niches_count,
            }

    def _row_to_trend(self, row: sqlite3.Row) -> Trend:
        """Convert database row to Trend object."""
        return Trend(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            category=TrendCategory(row["category"]) if row["category"] else TrendCategory.EMERGING,
            source=TrendSource(row["source"]) if row["source"] else TrendSource.CUSTOM,
            status=TrendStatus(row["status"]) if row["status"] else TrendStatus.UNKNOWN,
            score=row["score"] or 0,
            velocity=row["velocity"] or 0,
            momentum=row["momentum"] or 0,
            volume=row["volume"] or 0,
            keywords=json.loads(row["keywords"]) if row["keywords"] else [],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            market_opportunity=row["market_opportunity"] or 0,
            competition_level=row["competition_level"] or 0,
            entry_barrier=row["entry_barrier"] or 0,
            first_seen=datetime.fromisoformat(row["first_seen"]) if row["first_seen"] else None,
            last_updated=datetime.fromisoformat(row["last_updated"]) if row["last_updated"] else None,
            data_quality=row["data_quality"] or 1,
            raw_data=json.loads(row["raw_data"]) if row["raw_data"] else {},
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            confidence_multiplier=row["confidence_multiplier"] if row["confidence_multiplier"] is not None else 1.0,
            confirmed_by_sources=json.loads(row["confirmed_by_sources"]) if row["confirmed_by_sources"] else [],
        )


class TrendAnalyzer:
    """Core trend analysis engine."""

    def __init__(self, db: Optional[TrendDatabase] = None):
        """Initialize analyzer."""
        self.db = db or TrendDatabase()

    def analyze_trend(self, trend: Trend) -> Trend:
        """Analyze and score a trend."""
        # Calculate velocity from history if available
        history = self.db.get_trend_history(trend.id, days=DEFAULT_HISTORY_DAYS)
        if len(history) >= 2:
            recent_score = history[-1].get("score", 0)
            older_score = history[0].get("score", 0)
            trend.velocity = (recent_score - older_score) / max(len(history), 1)

        # Determine status based on metrics
        if trend.velocity > VELOCITY_THRESHOLD_EMERGING:
            trend.status = TrendStatus.EMERGING
        elif trend.velocity > VELOCITY_THRESHOLD_GROWING:
            trend.status = TrendStatus.GROWING
        elif trend.velocity > VELOCITY_THRESHOLD_STABLE_LOW:
            trend.status = TrendStatus.STABLE
        elif trend.velocity > VELOCITY_THRESHOLD_DECLINING:
            trend.status = TrendStatus.DECLINING
        else:
            trend.status = TrendStatus.DECLINING

        # Calculate momentum (smoothed velocity)
        if len(history) >= 3:
            velocities = []
            for i in range(1, len(history)):
                v = history[i].get("score", 0) - history[i-1].get("score", 0)
                velocities.append(v)
            trend.momentum = sum(velocities) / len(velocities) if velocities else 0

        return trend

    def calculate_opportunity_score(self, trend: Trend) -> float:
        """Calculate market opportunity score for a trend."""
        # Factors: growth potential, competition, entry barrier
        growth_factor = (trend.velocity + 1) / 2  # Normalize to 0-1
        competition_factor = 1 - trend.competition_level
        barrier_factor = 1 - trend.entry_barrier
        quality_factor = trend.data_quality

        opportunity = (
            growth_factor * 0.4 +
            competition_factor * 0.25 +
            barrier_factor * 0.2 +
            quality_factor * 0.15
        )

        return min(max(opportunity, 0), 1)

    def identify_correlations(
        self,
        trend: Trend,
        all_trends: Optional[List[Trend]] = None,
    ) -> List[Tuple[str, float]]:
        """Find correlated trends."""
        if all_trends is None:
            all_trends = self.db.get_trends(limit=100)

        correlations = []
        for other in all_trends:
            if other.id == trend.id:
                continue

            # Simple keyword overlap correlation
            overlap = len(set(trend.keywords) & set(other.keywords))
            if overlap > 0:
                correlation = overlap / max(len(trend.keywords), len(other.keywords), 1)
                if correlation > 0.2:
                    correlations.append((other.id, correlation))

        return sorted(correlations, key=lambda x: x[1], reverse=True)[:10]

    def get_trend_report(self) -> Dict[str, Any]:
        """Generate a comprehensive trend report."""
        top_trends = self.db.get_top_trends(limit=10)
        emerging = self.db.get_emerging_trends(limit=10)
        niches = self.db.get_niches(limit=5)
        stats = self.db.get_stats()

        return {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_trends": stats["total_trends"],
                "average_score": stats["average_score"],
                "top_categories": list(stats["by_category"].items())[:5],
            },
            "top_trends": [t.to_dict() for t in top_trends],
            "emerging_trends": [t.to_dict() for t in emerging],
            "top_niches": [n.to_dict() for n in niches],
            "signals": {
                "buy_signals": len([t for t in top_trends if t.get_signal() in [TrendSignal.BUY, TrendSignal.STRONG_BUY]]),
                "hold_signals": len([t for t in top_trends if t.get_signal() == TrendSignal.HOLD]),
                "sell_signals": len([t for t in top_trends if t.get_signal() in [TrendSignal.SELL, TrendSignal.STRONG_SELL]]),
            },
        }
