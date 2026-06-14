"""Tests for offline data collection queue (item 768)."""

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest

from trendscope.offline.queue import (
    OfflineCollectionQueue,
    QueuedRequest,
    QueueStatus,
)


@pytest.fixture
def queue(tmp_path):
    return OfflineCollectionQueue(db_path=tmp_path / "queue.db")


class TestQueuedRequest:
    def test_is_retriable_after_failure(self):
        req = QueuedRequest(status=QueueStatus.FAILED, retries=1, max_retries=3)
        assert req.is_retriable

    def test_not_retriable_when_exhausted(self):
        req = QueuedRequest(status=QueueStatus.FAILED, retries=3, max_retries=3)
        assert not req.is_retriable

    def test_is_expired(self):
        req = QueuedRequest(expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        assert req.is_expired

    def test_not_expired(self):
        req = QueuedRequest(expires_at=datetime.now(timezone.utc) + timedelta(hours=1))
        assert not req.is_expired

    def test_no_expiry(self):
        req = QueuedRequest(expires_at=None)
        assert not req.is_expired

    def test_to_dict(self):
        req = QueuedRequest(source="reddit", query="AI")
        d = req.to_dict()
        assert d["source"] == "reddit"
        assert d["status"] == "pending"


class TestOfflineCollectionQueue:
    def test_enqueue(self, queue):
        req = queue.enqueue("reddit", query="machine learning")
        assert req.source == "reddit"
        assert req.query == "machine learning"
        assert req.status == QueueStatus.PENDING

    def test_enqueue_with_params(self, queue):
        req = queue.enqueue("google_trends", params={"geo": "US"})
        assert req.params == {"geo": "US"}

    def test_peek(self, queue):
        queue.enqueue("reddit", priority=3)
        queue.enqueue("twitter", priority=1)
        peeked = queue.peek(limit=5)
        assert len(peeked) == 2
        assert peeked[0].source == "twitter"  # higher priority first

    def test_dequeue(self, queue):
        queue.enqueue("reddit")
        req = queue.dequeue()
        assert req is not None
        assert req.status == QueueStatus.PROCESSING

    def test_dequeue_empty(self, queue):
        assert queue.dequeue() is None

    def test_dequeue_priority_order(self, queue):
        queue.enqueue("low", priority=10)
        queue.enqueue("high", priority=1)
        req = queue.dequeue()
        assert req.source == "high"

    def test_complete(self, queue):
        req = queue.enqueue("test")
        dequeued = queue.dequeue()
        assert queue.complete(dequeued.id, result_summary="done")
        updated = queue.get(dequeued.id)
        assert updated.status == QueueStatus.COMPLETED

    def test_fail(self, queue):
        req = queue.enqueue("test")
        queue.dequeue()
        assert queue.fail(req.id, error="timeout")
        updated = queue.get(req.id)
        assert updated.status == QueueStatus.FAILED
        assert updated.retries == 1

    def test_retry_failed(self, queue):
        req = queue.enqueue("test", max_retries=3)
        queue.dequeue()
        queue.fail(req.id)
        count = queue.retry_failed()
        assert count == 1
        assert queue.count(QueueStatus.PENDING) == 1

    def test_retry_exhausted_not_retried(self, queue):
        req = queue.enqueue("test", max_retries=1)
        queue.dequeue()
        queue.fail(req.id)
        # retries=1, max_retries=1 -> not retriable
        count = queue.retry_failed()
        assert count == 0

    def test_expire_old(self, queue):
        # Insert with already-expired timestamp
        now = datetime.now(timezone.utc)
        past = now - timedelta(hours=100)
        with sqlite3.connect(str(queue.db_path)) as conn:
            conn.execute(
                "INSERT INTO queue (id, source, query, status, priority, retries, max_retries, error, result_summary, created_at, updated_at, expires_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("exp-1", "test", "", "pending", 5, 0, 3, "", "", past.isoformat(), past.isoformat(), past.isoformat()),
            )
        expired = queue.expire_old()
        assert expired == 1

    def test_drain_success(self, queue):
        queue.enqueue("a")
        queue.enqueue("b")

        def handler(req):
            return True

        result = queue.drain(handler)
        assert result["completed"] == 2
        assert result["failed"] == 0

    def test_drain_failure(self, queue):
        queue.enqueue("a")

        def handler(req):
            raise RuntimeError("boom")

        result = queue.drain(handler)
        assert result["failed"] == 1

    def test_drain_limit(self, queue):
        for i in range(10):
            queue.enqueue(f"s{i}")
        result = queue.drain(lambda r: True, limit=3)
        assert result["completed"] == 3

    def test_count(self, queue):
        queue.enqueue("a")
        queue.enqueue("b")
        assert queue.count() == 2
        assert queue.count(QueueStatus.PENDING) == 2
        assert queue.count(QueueStatus.COMPLETED) == 0

    def test_clear(self, queue):
        queue.enqueue("a")
        queue.enqueue("b")
        removed = queue.clear()
        assert removed == 2
        assert queue.count() == 0

    def test_clear_by_status(self, queue):
        queue.enqueue("a")
        req = queue.enqueue("b")
        queue.dequeue()
        queue.complete(req.id)
        removed = queue.clear(status=QueueStatus.COMPLETED)
        assert removed == 1
        assert queue.count() >= 1

    def test_stats(self, queue):
        queue.enqueue("a")
        queue.enqueue("b")
        s = queue.stats()
        assert s["total"] == 2
        assert s["by_status"]["pending"] == 2

    def test_get(self, queue):
        req = queue.enqueue("test")
        fetched = queue.get(req.id)
        assert fetched is not None
        assert fetched.source == "test"

    def test_get_missing(self, queue):
        assert queue.get("nope") is None
