"""Tests for data source configuration auto-maintenance (item 949)."""

from datetime import datetime, timezone, timedelta

import pytest

from trendscope.offline.source_maintenance import (
    SourceMaintenanceManager,
    SourceConfig,
    SourceStatus,
)


@pytest.fixture
def manager(tmp_path):
    return SourceMaintenanceManager(db_path=tmp_path / "sources.db")


class TestSourceConfig:
    def test_success_rate_no_data(self):
        cfg = SourceConfig()
        assert cfg.success_rate == 1.0

    def test_success_rate_mixed(self):
        cfg = SourceConfig(total_successes=7, total_failures=3)
        assert cfg.success_rate == pytest.approx(0.7)

    def test_should_auto_disable(self):
        cfg = SourceConfig(auto_disable=True, enabled=True, consecutive_failures=3, failure_threshold=3)
        assert cfg.should_auto_disable

    def test_should_not_auto_disable_below_threshold(self):
        cfg = SourceConfig(auto_disable=True, enabled=True, consecutive_failures=2, failure_threshold=3)
        assert not cfg.should_auto_disable

    def test_should_check_recovery(self):
        cfg = SourceConfig(
            auto_recover=True,
            status=SourceStatus.DISABLED,
            last_check_at=datetime.now(timezone.utc) - timedelta(minutes=60),
            recovery_check_minutes=30,
        )
        assert cfg.should_check_recovery

    def test_should_not_check_recovery_too_soon(self):
        cfg = SourceConfig(
            auto_recover=True,
            status=SourceStatus.DISABLED,
            last_check_at=datetime.now(timezone.utc) - timedelta(minutes=5),
            recovery_check_minutes=30,
        )
        assert not cfg.should_check_recovery

    def test_to_dict(self):
        cfg = SourceConfig(source_id="s1", name="Reddit")
        d = cfg.to_dict()
        assert d["source_id"] == "s1"
        assert "success_rate" in d


class TestSourceMaintenanceManager:
    def test_register_source(self, manager):
        cfg = manager.register_source("reddit", "Reddit", source_type="reddit")
        assert cfg.source_id == "reddit"
        assert cfg.enabled
        assert cfg.status == SourceStatus.HEALTHY

    def test_get_source(self, manager):
        manager.register_source("s1", "Source One")
        cfg = manager.get_source("s1")
        assert cfg is not None
        assert cfg.name == "Source One"

    def test_get_source_missing(self, manager):
        assert manager.get_source("nope") is None

    def test_get_all_sources(self, manager):
        manager.register_source("a", "A")
        manager.register_source("b", "B")
        all_srcs = manager.get_all_sources()
        assert len(all_srcs) == 2

    def test_record_success(self, manager):
        manager.register_source("s1", "S1")
        cfg = manager.record_success("s1")
        assert cfg.total_successes == 1
        assert cfg.consecutive_failures == 0
        assert cfg.status == SourceStatus.HEALTHY

    def test_record_failure(self, manager):
        manager.register_source("s1", "S1")
        cfg = manager.record_failure("s1", error="timeout")
        assert cfg.total_failures == 1
        assert cfg.consecutive_failures == 1

    def test_auto_disable_after_threshold(self, manager):
        manager.register_source("s1", "S1", failure_threshold=2)
        manager.record_failure("s1", "err1")
        cfg = manager.record_failure("s1", "err2")
        assert not cfg.enabled
        assert cfg.status == SourceStatus.DISABLED

    def test_success_resets_failures(self, manager):
        manager.register_source("s1", "S1", failure_threshold=5)
        manager.record_failure("s1")
        manager.record_failure("s1")
        manager.record_success("s1")
        cfg = manager.get_source("s1")
        assert cfg.consecutive_failures == 0
        assert cfg.enabled

    def test_degraded_status_on_failure(self, manager):
        manager.register_source("s1", "S1", failure_threshold=5)
        manager.record_failure("s1")
        cfg = manager.get_source("s1")
        assert cfg.status == SourceStatus.DEGRADED

    def test_get_enabled_sources(self, manager):
        manager.register_source("a", "A")
        manager.register_source("b", "B", failure_threshold=1)
        manager.record_failure("b")
        enabled = manager.get_enabled_sources()
        assert len(enabled) == 1
        assert enabled[0].source_id == "a"

    def test_get_disabled_sources(self, manager):
        manager.register_source("a", "A", failure_threshold=1)
        manager.record_failure("a")
        disabled = manager.get_disabled_sources()
        assert len(disabled) == 1

    def test_manual_disable(self, manager):
        manager.register_source("s1", "S1")
        assert manager.disable_source("s1", reason="maintenance")
        cfg = manager.get_source("s1")
        assert not cfg.enabled

    def test_manual_enable(self, manager):
        manager.register_source("s1", "S1", failure_threshold=1)
        manager.record_failure("s1")
        assert manager.enable_source("s1")
        cfg = manager.get_source("s1")
        assert cfg.enabled
        assert cfg.consecutive_failures == 0

    def test_run_maintenance_recovery(self, manager):
        manager.register_source("s1", "S1", failure_threshold=1)
        manager.record_failure("s1")
        # Register probe that returns healthy
        manager.register_health_probe("s1", lambda: True)
        # Force last_check_at to be old enough
        import sqlite3
        old = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        with sqlite3.connect(str(manager.db_path)) as conn:
            conn.execute("UPDATE sources SET last_check_at = ? WHERE source_id = 's1'", (old,))
        result = manager.run_maintenance()
        assert len(result["actions"]) == 1
        assert result["actions"][0]["action"] == "recovered"
        cfg = manager.get_source("s1")
        assert cfg.enabled

    def test_run_maintenance_still_down(self, manager):
        manager.register_source("s1", "S1", failure_threshold=1)
        manager.record_failure("s1")
        manager.register_health_probe("s1", lambda: False)
        import sqlite3
        old = (datetime.now(timezone.utc) - timedelta(minutes=60)).isoformat()
        with sqlite3.connect(str(manager.db_path)) as conn:
            conn.execute("UPDATE sources SET last_check_at = ? WHERE source_id = 's1'", (old,))
        result = manager.run_maintenance()
        assert result["actions"][0]["action"] == "still_disabled"

    def test_get_events(self, manager):
        manager.register_source("s1", "S1")
        manager.record_failure("s1", "error1")
        events = manager.get_events("s1")
        assert len(events) >= 2  # registered + failure

    def test_health_summary(self, manager):
        manager.register_source("a", "A")
        manager.register_source("b", "B")
        summary = manager.health_summary()
        assert summary["total_sources"] == 2
        assert summary["enabled"] == 2

    def test_remove_source(self, manager):
        manager.register_source("s1", "S1")
        assert manager.remove_source("s1")
        assert manager.get_source("s1") is None

    def test_remove_nonexistent(self, manager):
        assert not manager.remove_source("nope")

    def test_register_with_params(self, manager):
        cfg = manager.register_source("s1", "S1", params={"geo": "US"}, url="https://example.com")
        assert cfg.params == {"geo": "US"}
        assert cfg.url == "https://example.com"
