"""Offline data collection queue for deferred execution.

Item 768: When network/sources are unavailable, collection requests are queued
in a persistent SQLite store and drained when connectivity returns.
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

DEFAULT_MAX_RETRIES = 3
DEFAULT_PRIORITY = 5  # 1=highest, 10=lowest


class QueueStatus(Enum):
    """Status of a queued collection request."""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class QueuedRequest:
    """A single queued data-collection request."""

    id: str = field(default_factory=lambda: str(uuid4()))
    source: str = ""
    query: str = ""
    params: Dict[str, Any] = field(default_factory=dict)
    status: QueueStatus = QueueStatus.PENDING
    priority: int = DEFAULT_PRIORITY
    retries: int = 0
    max_retries: int = DEFAULT_MAX_RETRIES
    error: str = ""
    result_summary: str = ""
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None

    @property
    def is_retriable(self) -> bool:
        return self.status == QueueStatus.FAILED and self.retries < self.max_retries

    @property
    def is_expired(self) -> bool:
        if self.expires_at is None:
            return False
        return datetime.now(timezone.utc) >= self.expires_at

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "source": self.source,
            "query": self.query,
            "params": self.params,
            "status": self.status.value,
            "priority": self.priority,
            "retries": self.retries,
            "max_retries": self.max_retries,
            "error": self.error,
            "result_summary": self.result_summary,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }


class OfflineCollectionQueue:
    """Persistent queue for deferred data-collection requests.

    Requests are stored in SQLite so they survive process restarts.
    When connectivity returns, a drain pass processes them in priority order.
    """

    def __init__(
        self,
        db_path: Optional[Path] = None,
        default_ttl_hours: float = 48.0,
    ):
        if db_path is None:
            data_dir = Path(__file__).parent / "data"
            data_dir.mkdir(parents=True, exist_ok=True)
            db_path = data_dir / "collection_queue.db"
        self.db_path = db_path
        self.default_ttl_hours = default_ttl_hours
        self._lock = threading.Lock()
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS queue (
                        id TEXT PRIMARY KEY,
                        source TEXT NOT NULL,
                        query TEXT NOT NULL DEFAULT '',
                        params TEXT DEFAULT '{}',
                        status TEXT DEFAULT 'pending',
                        priority INTEGER DEFAULT 5,
                        retries INTEGER DEFAULT 0,
                        max_retries INTEGER DEFAULT 3,
                        error TEXT DEFAULT '',
                        result_summary TEXT DEFAULT '',
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        expires_at TEXT
                    )
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queue_status ON queue(status)
                """)
                conn.execute("""
                    CREATE INDEX IF NOT EXISTS idx_queue_priority ON queue(priority ASC)
                """)

    def enqueue(
        self,
        source: str,
        query: str = "",
        params: Optional[Dict[str, Any]] = None,
        priority: int = DEFAULT_PRIORITY,
        max_retries: int = DEFAULT_MAX_RETRIES,
        ttl_hours: Optional[float] = None,
    ) -> QueuedRequest:
        """Add a collection request to the queue."""
        now = datetime.now(timezone.utc)
        ttl = ttl_hours if ttl_hours is not None else self.default_ttl_hours
        expires_at = now + timedelta(hours=ttl) if ttl > 0 else None

        req = QueuedRequest(
            source=source,
            query=query,
            params=params or {},
            priority=priority,
            max_retries=max_retries,
            created_at=now,
            updated_at=now,
            expires_at=expires_at,
        )

        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.execute("""
                    INSERT INTO queue (id, source, query, params, status, priority,
                        retries, max_retries, error, result_summary,
                        created_at, updated_at, expires_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    req.id, req.source, req.query, json.dumps(req.params),
                    req.status.value, req.priority, req.retries, req.max_retries,
                    req.error, req.result_summary,
                    req.created_at.isoformat(), req.updated_at.isoformat(),
                    req.expires_at.isoformat() if req.expires_at else None,
                ))
        logger.info("Queued collection request %s for source=%s query=%s", req.id, source, query)
        return req

    def peek(self, limit: int = 10) -> List[QueuedRequest]:
        """Peek at the top pending requests by priority without changing status."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT * FROM queue WHERE status = 'pending' ORDER BY priority ASC, created_at ASC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._row_to_request(r) for r in rows]

    def dequeue(self) -> Optional[QueuedRequest]:
        """Pop the highest-priority pending request and mark it as processing."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    "SELECT * FROM queue WHERE status = 'pending' ORDER BY priority ASC, created_at ASC LIMIT 1"
                ).fetchone()
                if row is None:
                    return None
                now = datetime.now(timezone.utc).isoformat()
                conn.execute(
                    "UPDATE queue SET status = 'processing', updated_at = ? WHERE id = ?",
                    (now, row["id"]),
                )
        req = self._row_to_request(row)
        req.status = QueueStatus.PROCESSING
        return req

    def complete(self, request_id: str, result_summary: str = "") -> bool:
        """Mark a queued request as completed."""
        return self._update_status(request_id, QueueStatus.COMPLETED, result_summary=result_summary)

    def fail(self, request_id: str, error: str = "") -> bool:
        """Mark a queued request as failed, incrementing retry count."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "UPDATE queue SET status = 'failed', error = ?, retries = retries + 1, updated_at = ? WHERE id = ?",
                    (error, now, request_id),
                )
                return cursor.rowcount > 0

    def retry_failed(self) -> int:
        """Re-queue all failed requests that haven't exceeded max_retries. Returns count."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "UPDATE queue SET status = 'pending', updated_at = ? WHERE status = 'failed' AND retries < max_retries",
                    (now,),
                )
                return cursor.rowcount

    def expire_old(self) -> int:
        """Mark expired requests. Returns count expired."""
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                cursor = conn.execute(
                    "UPDATE queue SET status = 'expired', updated_at = ? WHERE status IN ('pending', 'failed') AND expires_at IS NOT NULL AND expires_at < ?",
                    (now, now),
                )
                return cursor.rowcount

    def drain(
        self,
        handler: Callable[[QueuedRequest], bool],
        limit: int = 50,
    ) -> Dict[str, int]:
        """Process pending requests through a handler function.

        The handler receives a QueuedRequest and returns True on success.
        Returns counts of {completed, failed, expired}.
        """
        self.expire_old()

        completed = 0
        failed = 0

        for _ in range(limit):
            req = self.dequeue()
            if req is None:
                break

            if req.is_expired:
                self._update_status(req.id, QueueStatus.EXPIRED)
                continue

            try:
                success = handler(req)
                if success:
                    self.complete(req.id, result_summary="drained")
                    completed += 1
                else:
                    self.fail(req.id, error="handler returned False")
                    failed += 1
            except Exception as exc:
                self.fail(req.id, error=str(exc)[:500])
                failed += 1
                logger.warning("Queue drain handler failed for %s: %s", req.id, exc)

        return {"completed": completed, "failed": failed}

    def get(self, request_id: str) -> Optional[QueuedRequest]:
        """Get a specific queued request."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute("SELECT * FROM queue WHERE id = ?", (request_id,)).fetchone()
        if row is None:
            return None
        return self._row_to_request(row)

    def count(self, status: Optional[QueueStatus] = None) -> int:
        """Count requests, optionally filtered by status."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                if status:
                    row = conn.execute(
                        "SELECT COUNT(*) FROM queue WHERE status = ?", (status.value,)
                    ).fetchone()
                else:
                    row = conn.execute("SELECT COUNT(*) FROM queue").fetchone()
        return row[0] if row else 0

    def clear(self, status: Optional[QueueStatus] = None) -> int:
        """Clear queue entries. If status given, only clear that status."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                if status:
                    cursor = conn.execute("DELETE FROM queue WHERE status = ?", (status.value,))
                else:
                    cursor = conn.execute("DELETE FROM queue")
                return cursor.rowcount

    def stats(self) -> Dict[str, Any]:
        """Return queue statistics."""
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    "SELECT status, COUNT(*) as cnt FROM queue GROUP BY status"
                ).fetchall()
        status_counts = {row["status"]: row["cnt"] for row in rows}
        return {
            "total": sum(status_counts.values()),
            "by_status": status_counts,
        }

    def _update_status(self, request_id: str, status: QueueStatus, result_summary: str = "") -> bool:
        with self._lock:
            with sqlite3.connect(str(self.db_path)) as conn:
                now = datetime.now(timezone.utc).isoformat()
                cursor = conn.execute(
                    "UPDATE queue SET status = ?, result_summary = ?, updated_at = ? WHERE id = ?",
                    (status.value, result_summary, now, request_id),
                )
                return cursor.rowcount > 0

    def _row_to_request(self, row: sqlite3.Row) -> QueuedRequest:
        def _parse_dt(val: Optional[str]) -> Optional[datetime]:
            if not val:
                return None
            dt = datetime.fromisoformat(val.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt

        return QueuedRequest(
            id=row["id"],
            source=row["source"],
            query=row["query"] or "",
            params=json.loads(row["params"] or "{}"),
            status=QueueStatus(row["status"]),
            priority=row["priority"],
            retries=row["retries"],
            max_retries=row["max_retries"],
            error=row["error"] or "",
            result_summary=row["result_summary"] or "",
            created_at=_parse_dt(row["created_at"]) or datetime.now(timezone.utc),
            updated_at=_parse_dt(row["updated_at"]) or datetime.now(timezone.utc),
            expires_at=_parse_dt(row["expires_at"]),
        )
