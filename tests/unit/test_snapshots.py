"""Tests for snapshot management."""

import pytest

from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase
from trendscope.snapshots import SnapshotManager, Snapshot


class TestSnapshot:
    def test_creation(self):
        s = Snapshot(id="s1", label="test", data={"total_trends": 5}, created_at="2026-01-01T00:00:00")
        assert s.id == "s1"
        assert s.label == "test"
        assert s.data["total_trends"] == 5


class TestSnapshotManager:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def manager(self, db):
        return SnapshotManager(db)

    def test_create_snapshot_empty_db(self, manager):
        snap = manager.create_snapshot("empty")
        assert snap.label == "empty"
        assert snap.data["total_trends"] == 0
        assert isinstance(snap.id, str)
        assert snap.created_at is not None

    def test_create_snapshot_with_data(self, db, manager):
        db.save_trend(Trend(name="AI", score=90, category=TrendCategory.TECHNOLOGY, source=TrendSource.REDDIT))
        db.save_trend(Trend(name="Crypto", score=70, category=TrendCategory.FINANCE, source=TrendSource.TWITTER))
        snap = manager.create_snapshot("with_data")
        assert snap.data["total_trends"] == 2
        assert "by_category" in snap.data
        assert "by_status" in snap.data

    def test_list_snapshots_empty(self, manager):
        assert manager.list_snapshots() == []

    def test_list_snapshots(self, manager):
        manager.create_snapshot("first")
        manager.create_snapshot("second")
        snaps = manager.list_snapshots()
        assert len(snaps) == 2

    def test_get_snapshot(self, manager):
        snap = manager.create_snapshot("find_me")
        found = manager.get_snapshot(snap.id)
        assert found is not None
        assert found.label == "find_me"
        assert found.data == snap.data

    def test_get_snapshot_not_found(self, manager):
        assert manager.get_snapshot("nonexistent") is None

    def test_compare_snapshots_identical(self, manager):
        s1 = manager.create_snapshot("a")
        s2 = manager.create_snapshot("b")
        result = manager.compare_snapshots(s1.id, s2.id)
        assert "snapshot_a" in result
        assert "snapshot_b" in result
        assert "diff" in result

    def test_compare_snapshots_with_changes(self, db, manager):
        s1 = manager.create_snapshot("before")
        db.save_trend(Trend(name="New", score=80, category=TrendCategory.TECHNOLOGY))
        s2 = manager.create_snapshot("after")
        result = manager.compare_snapshots(s1.id, s2.id)
        # total_trends changed
        assert result["diff"]["changes"].get("total_trends") is not None

    def test_compare_snapshots_not_found(self, manager):
        s1 = manager.create_snapshot("exists")
        result = manager.compare_snapshots(s1.id, "nonexistent")
        assert "error" in result

    def test_compare_both_not_found(self, manager):
        result = manager.compare_snapshots("a", "b")
        assert "error" in result

    def test_snapshot_data_has_categories(self, db, manager):
        db.save_trend(Trend(name="T1", score=50, category=TrendCategory.TECHNOLOGY))
        db.save_trend(Trend(name="T2", score=60, category=TrendCategory.BUSINESS))
        snap = manager.create_snapshot("cats")
        assert "technology" in snap.data["by_category"]
        assert "business" in snap.data["by_category"]

    def test_snapshot_preserves_avg_score(self, db, manager):
        db.save_trend(Trend(name="T1", score=40, category=TrendCategory.TECHNOLOGY))
        db.save_trend(Trend(name="T2", score=60, category=TrendCategory.TECHNOLOGY))
        snap = manager.create_snapshot("avg")
        cat_data = snap.data["by_category"]["technology"]
        assert cat_data["count"] == 2
        assert cat_data["avg_score"] == 50.0

    def test_list_snapshots_ordered_desc(self, manager):
        manager.create_snapshot("first")
        manager.create_snapshot("second")
        manager.create_snapshot("third")
        snaps = manager.list_snapshots()
        assert snaps[0].label == "third"
        assert snaps[-1].label == "first"

    def test_compare_diff_structure(self, db, manager):
        s1 = manager.create_snapshot("v1")
        db.save_trend(Trend(name="X", score=100, category=TrendCategory.HEALTH))
        s2 = manager.create_snapshot("v2")
        result = manager.compare_snapshots(s1.id, s2.id)
        diff = result["diff"]
        assert "additions" in diff
        assert "removals" in diff
        assert "changes" in diff
