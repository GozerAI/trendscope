"""Data source configuration auto-maintenance.

Item 949: Monitors data source health, automatically disables unhealthy sources,
re-enables recovered ones, and maintains source configuration state. This ensures
the collection system gracefully adapts to source availability without manual
intervention.
"""

import json
import logging
import sqlite3
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from uuid import uuid4

logger = logging.getLogger(__name__)

# Default thresholds
DEFAULT_FAILURE_THRESHOLD = 3  # consecutive failures before auto-disable
DEFAULT_RECOVERY_CHECK_MINUTES = 30  # how often to probe disabled sources
DEFAULT_HEALTH_WINDOW_MINUTES = 60  # window for computing failure rate


class SourceStatus(Enum):
    """Health status of a data source."""
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DISABLED = "disabled"
    RECOVERING = "recovering"
    UNKNOWN = "unknown"


@dataclass
class SourceConfig:
    """Configuration and health state for a single data source."""

    source_id: str = ""
    name: str = ""
    source_type: str = ""  # maps to TrendSource values
    enabled: bool = True
    status: SourceStatus = SourceStatus.UNKNOWN
    url: str = ""
    params: Dict[str, Any] = field(default_factory=dict)

    # Health tracking
    consecutive_failures: int = 0
    total_successes: int = 0
    total_failures: int = 0
    last_success_at: Optional[datetime] = None
    last_failure_at: Optional[datetime] = None
    last_error: str = ""
    last_check_at: Optional[datetime] = None

    # Auto-maintenance config
    failure_threshold: int = DEFAULT_FAILURE_THRESHOLD
    recovery_check_minutes: int = DEFAULT_RECOVERY_CHECK_MINUTES
    auto_disable: bool = True
    auto_recover: bool = True

    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @property
    def success_rate(self) -> float:
        """Overall success rate (0.0 to 1.0)."""
        total = self.total_successes + self.total_failures
        if total == 0:
            return 1.0
        return self.total_successes / total

    @property
    def should_auto_disable(self) -> bool:
        return (
            self.auto_disable
            and self.enabled
            and self.consecutive_failures >= self.failure_threshold
        )

    @property
    def should_check_recovery(self) -> bool:
        if not self.auto_recover or self.status != SourceStatus.DISABLED:
            return False
        if self.last_check_at is None:
            return True
        elapsed = (datetime.now(timezone.utc) - self.last_check_at).total_seconds() / 60
        return elapsed >= self.recovery_check_minutes

    def to_dict(self) -> Dict[str, Any]:
        return {
            "source_id": self.source_id,
            "name": self.name,
            "source_type": self.source_type,
            "enabled": self.enabled,
            "status": self.status.value,
            "url": self.url,
            "params": self.params,
            "consecutive_failures": self.consecutive_failures,
            "total_successes": self.total_successes,
            "total_failures": self.total_failures,
            "success_rate": round(self.success_rate, 3),
            "last_success_at": self.last_success_at.isoformat() if self.last_success_at else None,
            "last_failure_at": self.last_failure_at.isoformat() if self.last_failure_at else None,
            "last_error": self.last_error,
            "failure_threshold": self.failure_threshold,
            "auto_disable": self.auto_disable,
            "auto_recover": self.auto_recover,
        }


class SourceMaintenanceManager:
    """Manages data source configuration and automatic health maintenance.

    Tracks source health, auto-disables consistently failing sources,
    and periodically probes disabled sources for recovery.
    """

    def __init__(self, db_path: Optional[Path] = None):
        if db_path is None:
            data_dir = Path(__file__).parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "source_config.db"
        self.db_path = db_path
        self._lock = threading.Lock()
        self._health_probes: Dict[str, Callable[[], bool]] = {}
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS sources (
                        source_id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        source_type TEXT NOT NULL DEFAULT '',
                        enabled INTEGER DEFAULT 1,
                        status TEXT DEFAULT 'unknown',
                        url TEXT DEFAULT '',
                        params TEXT DEFAULT '{}',
                        consecutive_failures INTEGER DEFAULT 0,
                        total_successes INTEGER DEFAULT 0,
                        total_failures INTEGER DEFAULT 0,
                        last_success_at TEXT,
                        last_failure_at TEXT,
                        last_error TEXT DEFAULT '',
                        last_check_at TEXT,
                        failure_threshold INTEGER DEFAULT 3,
                        recovery_check_minutes INTEGER DEFAULT 30,
                        auto_disable INTEGER DEFAULT 1,
                        auto_recover INTEGER DEFAULT 1,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    )
                """)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS source_events (
                        id TEXT PRIMARY KEY,
                        source_id TEXT NOT NULL,
                        event_type TEXT NOT NULL,
                        detail TEXT DEFAULT '',
                        timestamp TEXT NOT NULL,
                        FOREIGN KEY (source_id) REFERENCES sources(source_id)
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_events_source ON source_events(source_id)
                """)

    def register_source(
        self,
        source_id: str,
        name: str,
        source_type: str = "",
        url: str = "",
        params: Optional[Dict[str, Any]] = None,
        failure_threshold: int = DEFAULT_FAILURE_THRESHOLD,
        auto_disable: bool = True,
        auto_recover: bool = True,
    ) -> SourceConfig:
        """Register or update a data source configuration."""
        now = datetime.now(timezone.utc)
        config = SourceConfig(
            source_id=source_id,
            name=name,
            source_type=source_type,
            url=url,
            params=params or {},
            failure_threshold=failure_threshold,
            auto_disable=auto_disable,
            auto_recover=auto_recover,
            created_at=now,
            updated_at=now,
            status=SourceStatus.HEALTHY,
            enabled=True,
        )

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    INSERT OR REPLACE INTO sources
                    (source_id, name, source_type, enabled, status, url, params,
                     consecutive_failures, total_successes, total_failures,
                     last_success_at, last_failure_at, last_error, last_check_at,
                     failure_threshold, recovery_check_minutes, auto_disable, auto_recover,
                     created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    config.source_id, config.name, config.source_type,
                    int(config.enabled), config.status.value, config.url,
                    json.dumps(config.params),
                    config.consecutive_failures, config.total_successes, config.total_failures,
                    None, None, "", None,
                    config.failure_threshold, config.recovery_check_minutes,
                    int(config.auto_disable), int(config.auto_recover),
                    config.created_at.isoformat(), config.updated_at.isoformat(),
                ))
        self._record_event(source_id, "registered", f"Source {name} registered")
        return config

    def register_health_probe(self, source_id: str, probe: Callable[[], bool]) -> None:
        """Register a health probe function for a source.

        The probe should return True if the source is reachable, False otherwise.
        """
        self._health_probes[source_id] = probe

    def record_success(self, source_id: str) -> SourceConfig:
        """Record a successful collection from a source."""
        now = datetime.now(timezone.utc)
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    UPDATE sources SET
                        consecutive_failures = 0,
                        total_successes = total_successes + 1,
                        last_success_at = ?,
                        last_check_at = ?,
                        status = 'healthy',
                        enabled = 1,
                        updated_at = ?
                    WHERE source_id = ?
                """, (now.isoformat(), now.isoformat(), now.isoformat(), source_id))
        config = self.get_source(source_id)
        if config and config.status == SourceStatus.RECOVERING:
            self._record_event(source_id, "recovered", "Source recovered from disabled state")
        return config  # type: ignore[return-value]

    def record_failure(self, source_id: str, error: str = "") -> SourceConfig:
        """Record a failed collection from a source. May auto-disable."""
        now = datetime.now(timezone.utc)
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    UPDATE sources SET
                        consecutive_failures = consecutive_failures + 1,
                        total_failures = total_failures + 1,
                        last_failure_at = ?,
                        last_error = ?,
                        last_check_at = ?,
                        updated_at = ?
                    WHERE source_id = ?
                """, (now.isoformat(), error[:500], now.isoformat(), now.isoformat(), source_id))

        config = self.get_source(source_id)
        if config is None:
            return SourceConfig()  # shouldn't happen

        # Check auto-disable
        if config.consecutive_failures >= config.failure_threshold and config.auto_disable:
            self._disable_source(source_id, reason=f"Auto-disabled after {config.consecutive_failures} consecutive failures")
            config.enabled = False
            config.status = SourceStatus.DISABLED

        elif config.consecutive_failures > 0:
            self._set_status(source_id, SourceStatus.DEGRADED)
            config.status = SourceStatus.DEGRADED

        self._record_event(source_id, "failure", error[:200])
        return config

    def get_source(self, source_id: str) -> Optional[SourceConfig]:
        """Get a source configuration."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM sources WHERE source_id = ?", (source_id,)
                ).fetchone()
        if row is None:
            return None
        return self._row_to_config(row)

    def get_all_sources(self) -> List[SourceConfig]:
        """Get all registered source configurations."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute("SELECT * FROM sources").fetchall()
        return [self._row_to_config(r) for r in rows]

    def get_enabled_sources(self) -> List[SourceConfig]:
        """Get only enabled sources."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM sources WHERE enabled = 1"
                ).fetchall()
        return [self._row_to_config(r) for r in rows]

    def get_disabled_sources(self) -> List[SourceConfig]:
        """Get only disabled sources."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM sources WHERE enabled = 0"
                ).fetchall()
        return [self._row_to_config(r) for r in rows]

    def disable_source(self, source_id: str, reason: str = "manual") -> bool:
        """Manually disable a source."""
        return self._disable_source(source_id, reason=reason)

    def enable_source(self, source_id: str) -> bool:
        """Manually re-enable a source."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "UPDATE sources SET enabled = 1, status = 'healthy', consecutive_failures = 0, updated_at = ? WHERE source_id = ?",
                    (now, source_id),
                )
                ok = cursor.rowcount > 0
        if ok:
            self._record_event(source_id, "enabled", "Manually re-enabled")
        return ok

    def run_maintenance(self) -> Dict[str, Any]:
        """Run a full maintenance cycle: check disabled sources for recovery.

        Returns summary of actions taken.
        """
        actions: List[Dict[str, str]] = []
        disabled = self.get_disabled_sources()

        for src in disabled:
            if not src.should_check_recovery:
                continue

            # Update last_check_at
            self._touch_check(src.source_id)

            probe = self._health_probes.get(src.source_id)
            if probe is None:
                continue

            self._set_status(src.source_id, SourceStatus.RECOVERING)
            self._record_event(src.source_id, "recovery_probe", "Probing source health")

            try:
                healthy = probe()
            except Exception as exc:
                logger.warning("Health probe failed for %s: %s", src.source_id, exc)
                healthy = False

            if healthy:
                self.enable_source(src.source_id)
                actions.append({"source_id": src.source_id, "action": "recovered"})
                self._record_event(src.source_id, "recovered", "Auto-recovered after successful probe")
            else:
                self._set_status(src.source_id, SourceStatus.DISABLED)
                actions.append({"source_id": src.source_id, "action": "still_disabled"})

        return {
            "checked": len([s for s in disabled if s.should_check_recovery]),
            "actions": actions,
        }

    def get_events(self, source_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get recent events for a source."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM source_events WHERE source_id = ? ORDER BY timestamp DESC LIMIT ?",
                    (source_id, limit),
                ).fetchall()
        return [
            {"id": r["id"], "source_id": r["source_id"], "event_type": r["event_type"],
             "detail": r["detail"], "timestamp": r["timestamp"]}
            for r in rows
        ]

    def health_summary(self) -> Dict[str, Any]:
        """Overall health summary of all sources."""
        sources = self.get_all_sources()
        status_counts: Dict[str, int] = {}
        for s in sources:
            key = s.status.value
            status_counts[key] = status_counts.get(key, 0) + 1

        return {
            "total_sources": len(sources),
            "enabled": sum(1 for s in sources if s.enabled),
            "disabled": sum(1 for s in sources if not s.enabled),
            "status_distribution": status_counts,
            "avg_success_rate": (
                round(sum(s.success_rate for s in sources) / len(sources), 3)
                if sources else 0.0
            ),
        }

    def remove_source(self, source_id: str) -> bool:
        """Remove a source configuration entirely."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("DELETE FROM source_events WHERE source_id = ?", (source_id,))
                cursor = conn.execute("DELETE FROM sources WHERE source_id = ?", (source_id,))
                ok = cursor.rowcount > 0
        self._health_probes.pop(source_id, None)
        return ok

    # -- Private --

    def _disable_source(self, source_id: str, reason: str = "") -> bool:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "UPDATE sources SET enabled = 0, status = 'disabled', updated_at = ? WHERE source_id = ?",
                    (now, source_id),
                )
                ok = cursor.rowcount > 0
        if ok:
            self._record_event(source_id, "disabled", reason)
            logger.warning("Source %s disabled: %s", source_id, reason)
        return ok

    def _set_status(self, source_id: str, status: SourceStatus) -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE sources SET status = ?, updated_at = ? WHERE source_id = ?",
                    (status.value, now, source_id),
                )

    def _touch_check(self, source_id: str) -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE sources SET last_check_at = ?, updated_at = ? WHERE source_id = ?",
                    (now, now, source_id),
                )

    def _record_event(self, source_id: str, event_type: str, detail: str = "") -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute(
                    "INSERT INTO source_events (id, source_id, event_type, detail, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (str(uuid4()), source_id, event_type, detail, datetime.now(timezone.utc).isoformat()),
                )

    def _row_to_config(self, row: sqlite3.Row) -> SourceConfig:
        def _parse_dt(val: Optional[str]) -> Optional[datetime]:
            if not val:
                return None
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        return SourceConfig(
            source_id=row["source_id"],
            name=row["name"],
            source_type=row["source_type"] or "",
            enabled=bool(row["enabled"]),
            status=SourceStatus(row["status"]) if row["status"] else SourceStatus.UNKNOWN,
            url=row["url"] or "",
            params=json.loads(row["params"] or "{}"),
            consecutive_failures=row["consecutive_failures"] or 0,
            total_successes=row["total_successes"] or 0,
            total_failures=row["total_failures"] or 0,
            last_success_at=_parse_dt(row["last_success_at"]),
            last_failure_at=_parse_dt(row["last_failure_at"]),
            last_error=row["last_error"] or "",
            last_check_at=_parse_dt(row["last_check_at"]),
            failure_threshold=row["failure_threshold"] or DEFAULT_FAILURE_THRESHOLD,
            recovery_check_minutes=row["recovery_check_minutes"] or DEFAULT_RECOVERY_CHECK_MINUTES,
            auto_disable=bool(row["auto_disable"]),
            auto_recover=bool(row["auto_recover"]),
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
        )
