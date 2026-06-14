"""Edge-case tests for KH sync, KH client, and KH notifier integration."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from trendscope.core import TrendDatabase
from trendscope.integrations.kh_sync import KHSync, _fetch_kh
from trendscope.integrations.kh_notifier import KHAnomalyNotifier, _post_to_kh, TS_TO_KH_CATEGORY
from trendscope.integrations.kh_client import (
    get_artifacts,
    get_popular,
    get_analytics_trends,
    get_trending_artifacts,
    map_ts_category_to_kh,
    map_kh_category_to_ts,
)
from trendscope.anomaly import AnomalyResult

try:
    from gozerai_telemetry.resilience import reset_all_breakers
    _HAS_RESILIENCE = True
except ImportError:
    _HAS_RESILIENCE = False


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(db_path=tmp_path / "kh_edge.db")


@pytest.fixture
def sync(db):
    return KHSync(db, kh_base_url="http://localhost:8011")


@pytest.fixture(autouse=True)
def reset_breakers():
    """Reset circuit breakers before each test if resilience is available."""
    if _HAS_RESILIENCE:
        reset_all_breakers()


# =============================================================================
# Sync with KH Available
# =============================================================================


class TestSyncKHAvailable:

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_success_with_gaps(self, mock_fetch, sync):
        mock_fetch.return_value = [
            {"category": "technology", "deficit": 10},
            {"category": "business", "deficit": 5},
        ]
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 2
        assert len(result["targets"]) == 2
        assert result["targets"][0]["category"] == "technology"

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_success_empty_gaps(self, mock_fetch, sync):
        mock_fetch.return_value = []
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 0

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_updates_timestamp(self, mock_fetch, sync):
        mock_fetch.return_value = []
        sync.sync_from_kh()
        status = sync.get_sync_status()
        assert status["last_sync"] is not None
        assert status["status"] == "success"


# =============================================================================
# Sync with KH Unavailable (Graceful Degradation)
# =============================================================================


class TestSyncKHUnavailable:

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_failed_when_unreachable(self, mock_fetch, sync):
        mock_fetch.return_value = None
        result = sync.sync_from_kh()
        assert result["status"] == "failed"
        assert "unreachable" in result["reason"].lower() or "KH" in result["reason"]

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_status_set_to_failed(self, mock_fetch, sync):
        mock_fetch.return_value = None
        sync.sync_from_kh()
        assert sync.get_sync_status()["status"] == "failed"

    def test_fetch_kh_unreachable_returns_none(self):
        """Direct call to _fetch_kh with bad URL returns None."""
        result = _fetch_kh("http://localhost:99999", "/api/nope")
        assert result is None

    def test_kh_client_graceful_degradation(self):
        """get_artifacts returns empty list when KH is unreachable."""
        with patch("trendscope.integrations.kh_client._request", return_value=None):
            assert get_artifacts() == []
            assert get_popular() == []
            assert get_analytics_trends() == []
            assert get_trending_artifacts() == []


# =============================================================================
# Sync Conflict Resolution
# =============================================================================


class TestSyncConflictResolution:

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_skips_empty_category(self, mock_fetch, sync):
        """Gaps with empty category are skipped."""
        mock_fetch.return_value = [
            {"category": "", "deficit": 5},
            {"category": "tech", "deficit": 3},
        ]
        result = sync.sync_from_kh()
        assert result["new_targets"] == 1
        assert result["targets"][0]["category"] == "tech"

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_handles_non_list_response(self, mock_fetch, sync):
        """Non-list KH response treated as 0 targets."""
        mock_fetch.return_value = {"gaps": []}
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 0

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_duplicate_categories(self, mock_fetch, sync):
        """Duplicate categories in gaps are all included as targets."""
        mock_fetch.return_value = [
            {"category": "tech", "deficit": 3},
            {"category": "tech", "deficit": 7},
        ]
        result = sync.sync_from_kh()
        assert result["new_targets"] == 2


# =============================================================================
# Sync with Stale Data
# =============================================================================


class TestSyncStaleData:

    def test_receive_artifact_stale_event(self, sync):
        result = sync.receive_intelligence({"event": "artifact.stale", "data": {"trend_id": "t1"}})
        assert result["status"] == "accepted"
        assert result["action"] == "stale_alert"

    def test_receive_harvest_complete_triggers_sync_refresh(self, sync):
        result = sync.receive_intelligence({"event": "harvest.complete", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "sync_refresh"

    def test_receive_snapshot_diff_event(self, sync):
        result = sync.receive_intelligence({"event": "snapshot.diff", "data": {"added": 5}})
        assert result["status"] == "accepted"
        assert result["action"] == "diff_received"

    def test_receive_refresh_complete(self, sync):
        result = sync.receive_intelligence({"event": "refresh.complete", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "refresh_logged"

    def test_stale_event_updates_last_sync(self, sync):
        assert sync._last_sync is None
        sync.receive_intelligence({"event": "artifact.stale", "data": {}})
        assert sync._last_sync is not None


# =============================================================================
# Sync Batch Size Handling
# =============================================================================


class TestSyncBatchSize:

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_large_batch(self, mock_fetch, sync):
        """Large gap list is handled correctly."""
        gaps = [{"category": f"cat_{i}", "deficit": i} for i in range(50)]
        mock_fetch.return_value = gaps
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 50

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_single_gap(self, mock_fetch, sync):
        mock_fetch.return_value = [{"category": "tech", "deficit": 1}]
        result = sync.sync_from_kh()
        assert result["new_targets"] == 1

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_gap_priority_preserved(self, mock_fetch, sync):
        """The deficit value is preserved as priority in targets."""
        mock_fetch.return_value = [{"category": "tech", "deficit": 42}]
        result = sync.sync_from_kh()
        assert result["targets"][0]["priority"] == 42


# =============================================================================
# Sync Retry on Transient Error
# =============================================================================


class TestSyncRetryTransientError:

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_first_fail_then_succeed(self, mock_fetch, sync):
        """Simulates retry by calling sync twice — first fails, second succeeds."""
        mock_fetch.side_effect = [None, [{"category": "ai", "deficit": 3}]]
        r1 = sync.sync_from_kh()
        assert r1["status"] == "failed"
        r2 = sync.sync_from_kh()
        assert r2["status"] == "success"
        assert r2["new_targets"] == 1

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_status_recovers_after_failure(self, mock_fetch, sync):
        """Status transitions from failed to success on recovery."""
        mock_fetch.return_value = None
        sync.sync_from_kh()
        assert sync.get_sync_status()["status"] == "failed"

        mock_fetch.return_value = []
        sync.sync_from_kh()
        assert sync.get_sync_status()["status"] == "success"


# =============================================================================
# KH Notifier Edge Cases
# =============================================================================


class TestKHNotifier:

    def test_notify_empty_anomalies(self):
        notifier = KHAnomalyNotifier()
        result = notifier.notify_anomalies([])
        assert result["sent"] == 0
        assert result["errors"] == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_sends_to_kh(self, mock_post):
        mock_post.return_value = {"status": "ok"}
        notifier = KHAnomalyNotifier()
        anomaly = AnomalyResult(
            trend_id="t1", trend_name="Test",
            anomaly_type="composite", severity="high",
            value=100, expected_range=(40, 60), deviation=2.5,
        )
        result = notifier.notify_anomalies([anomaly])
        assert result["sent"] >= 1
        assert notifier._notifications_sent >= 1

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_handles_kh_failure(self, mock_post):
        mock_post.return_value = None
        notifier = KHAnomalyNotifier()
        anomaly = AnomalyResult(
            trend_id="t1", trend_name="Test",
            anomaly_type="composite", severity="critical",
            value=200, expected_range=(40, 60), deviation=5.0,
        )
        result = notifier.notify_anomalies([anomaly])
        assert result["errors"] >= 1
        assert notifier._errors >= 1

    def test_notifier_stats(self):
        notifier = KHAnomalyNotifier()
        stats = notifier.get_stats()
        assert stats["notifications_sent"] == 0
        assert stats["errors"] == 0


# =============================================================================
# KH Client Category Mapping
# =============================================================================


class TestKHClientMapping:

    def test_map_ts_to_kh_technology(self):
        result = map_ts_category_to_kh("technology")
        assert isinstance(result, list)
        assert "ai-agent" in result

    def test_map_ts_to_kh_ecommerce(self):
        result = map_ts_category_to_kh("ecommerce")
        assert "ecommerce" in result

    def test_map_ts_to_kh_unknown(self):
        result = map_ts_category_to_kh("nonexistent_category")
        assert result == []

    def test_map_kh_to_ts_known(self):
        assert map_kh_category_to_ts("ai-agent") == "technology"
        assert map_kh_category_to_ts("ecommerce") == "ecommerce"

    def test_map_kh_to_ts_unknown_defaults_technology(self):
        assert map_kh_category_to_ts("totally-unknown") == "technology"

    def test_ts_to_kh_category_map_completeness(self):
        """All entries in the notifier's TS_TO_KH_CATEGORY dict are strings."""
        for ts_cat, kh_cat in TS_TO_KH_CATEGORY.items():
            assert isinstance(ts_cat, str)
            assert isinstance(kh_cat, str)


# =============================================================================
# Receive Intelligence Events — All Types
# =============================================================================


class TestReceiveIntelligenceAllEvents:

    ACCEPTED_EVENTS = [
        ("intelligence.update", "accepted"),
        ("artifact.stale", "accepted"),
        ("harvest.complete", "accepted"),
        ("graph.materialized", "accepted"),
        ("pipeline.run.complete", "accepted"),
        ("refresh.complete", "accepted"),
        ("snapshot.diff", "accepted"),
    ]

    @pytest.mark.parametrize("event_type,expected_status", ACCEPTED_EVENTS)
    def test_accepted_events(self, sync, event_type, expected_status):
        result = sync.receive_intelligence({"event": event_type, "data": {}})
        assert result["status"] == expected_status

    def test_unknown_event_ignored(self, sync):
        result = sync.receive_intelligence({"event": "totally.unknown", "data": {}})
        assert result["status"] == "ignored"

    def test_empty_event_ignored(self, sync):
        result = sync.receive_intelligence({"event": "", "data": {}})
        assert result["status"] == "ignored"

    def test_missing_event_key_ignored(self, sync):
        result = sync.receive_intelligence({"data": {}})
        assert result["status"] == "ignored"
