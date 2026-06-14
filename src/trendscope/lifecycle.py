"""Full lifecycle tracking for trends."""

import sqlite3
import uuid
from enum import Enum
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


class LifecycleStage(str, Enum):
    NASCENT = "nascent"
    EMERGING = "emerging"
    GROWING = "growing"
    PEAK = "peak"
    DECLINING = "declining"
    DORMANT = "dormant"
    DEAD = "dead"


@dataclass
class LifecycleTransition:
    id: str
    trend_id: str
    from_stage: Optional[str]
    to_stage: str
    timestamp: str
    reason: str


class LifecycleTracker:
    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db.db_path) as conn:
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
            conn.commit()

    def classify_stage(self, trend) -> LifecycleStage:
        """Classify a trend's current lifecycle stage based on metrics."""
        score = getattr(trend, "score", 0) or 0
        velocity = getattr(trend, "velocity", 0) or 0

        # Dead: very low score and negative velocity
        if score < 10 and velocity <= -0.3:
            return LifecycleStage.DEAD
        # Dormant: low score, near-zero velocity
        if score < 20 and abs(velocity) < 0.1:
            return LifecycleStage.DORMANT
        # Declining: negative velocity
        if velocity < -0.2:
            return LifecycleStage.DECLINING
        # Peak: high score, low velocity (plateauing)
        if score >= 80 and abs(velocity) < 0.15:
            return LifecycleStage.PEAK
        # Growing: positive velocity, moderate score
        if velocity > 0.1 and score >= 40:
            return LifecycleStage.GROWING
        # Emerging: positive velocity, low score
        if velocity > 0.05 and score >= 20:
            return LifecycleStage.EMERGING
        # Nascent: very early, low everything
        if score < 30:
            return LifecycleStage.NASCENT
        # Default based on score
        if score >= 70:
            return LifecycleStage.PEAK
        if score >= 40:
            return LifecycleStage.GROWING
        return LifecycleStage.EMERGING

    def update_lifecycle(
        self, trend_id: str, trend=None
    ) -> Optional[LifecycleTransition]:
        """Update lifecycle for a trend, recording transition if stage changed."""
        if trend is None:
            trend = self.db.get_trend(trend_id)
        if trend is None:
            return None

        new_stage = self.classify_stage(trend)

        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()

            # Get current stage
            cursor.execute(
                "SELECT to_stage FROM lifecycle_transitions "
                "WHERE trend_id = ? ORDER BY timestamp DESC LIMIT 1",
                (trend_id,),
            )
            row = cursor.fetchone()
            current_stage = row[0] if row else None

            if current_stage == new_stage.value:
                return None

            transition = LifecycleTransition(
                id=str(uuid.uuid4()),
                trend_id=trend_id,
                from_stage=current_stage,
                to_stage=new_stage.value,
                timestamp=datetime.now(timezone.utc).isoformat(),
                reason=f"Score={getattr(trend, 'score', 0)}, Velocity={getattr(trend, 'velocity', 0)}",
            )
            cursor.execute(
                "INSERT INTO lifecycle_transitions "
                "(id, trend_id, from_stage, to_stage, timestamp, reason) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    transition.id,
                    transition.trend_id,
                    transition.from_stage,
                    transition.to_stage,
                    transition.timestamp,
                    transition.reason,
                ),
            )
            conn.commit()
            return transition

    def get_lifecycle(self, trend_id: str) -> list[dict]:
        """Get full lifecycle history for a trend."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, trend_id, from_stage, to_stage, timestamp, reason "
                "FROM lifecycle_transitions WHERE trend_id = ? ORDER BY timestamp",
                (trend_id,),
            )
            return [
                {
                    "id": r[0],
                    "trend_id": r[1],
                    "from_stage": r[2],
                    "to_stage": r[3],
                    "timestamp": r[4],
                    "reason": r[5],
                }
                for r in cursor.fetchall()
            ]

    def get_stage_distribution(self) -> dict:
        """Get count of trends per lifecycle stage."""
        trends = self.db.get_trends(limit=10000)
        dist: dict[str, int] = {}
        for trend in trends:
            stage = self.classify_stage(trend).value
            dist[stage] = dist.get(stage, 0) + 1
        return dist

    def predict_time_to_peak(self, trend_id: str) -> Optional[dict]:
        """Estimate time to peak based on velocity and current score."""
        trend = self.db.get_trend(trend_id)
        if not trend:
            return None
        score = getattr(trend, "score", 0) or 0
        velocity = getattr(trend, "velocity", 0) or 0
        if velocity <= 0 or score >= 80:
            return {
                "trend_id": trend_id,
                "prediction": "not_applicable",
                "reason": "Not growing or already at peak",
            }
        gap = 80 - score
        days = gap / (velocity * 100) if velocity > 0 else float("inf")
        return {
            "trend_id": trend_id,
            "estimated_days": round(days, 1),
            "current_score": score,
            "velocity": velocity,
        }

    def get_aging_trends(self, min_days: int = 7) -> list[dict]:
        """Get trends in declining/dormant/dead stage for more than min_days."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT trend_id, to_stage, timestamp FROM lifecycle_transitions "
                "WHERE to_stage IN ('declining', 'dormant', 'dead') "
                "ORDER BY timestamp"
            )
            aging = []
            for r in cursor.fetchall():
                try:
                    ts = datetime.fromisoformat(r[2])
                    if ts.tzinfo is None:
                        ts = ts.replace(tzinfo=timezone.utc)
                    days = (datetime.now(timezone.utc) - ts).days
                    if days >= min_days:
                        aging.append(
                            {
                                "trend_id": r[0],
                                "stage": r[1],
                                "days_in_stage": days,
                                "entered_at": r[2],
                            }
                        )
                except (ValueError, TypeError):
                    continue
            return aging
