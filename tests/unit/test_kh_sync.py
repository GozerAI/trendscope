"""Tests for cross-system sync with Knowledge Harvester."""

import pytest
from unittest.mock import patch, MagicMock
from trendscope.core import TrendDatabase
from trendscope.integrations.kh_sync import KHSync, _fetch_kh

try:
    from gozerai_telemetry.resilience import reset_all_breakers
    _HAS_RESILIENCE = True
except ImportError:
    _HAS_RESILIENCE = False


class TestFetchKH:
    def setup_method(self):
        if _HAS_RESILIENCE:
            reset_all_breakers()

    def test_fetch_kh_graceful_failure(self):
        result = _fetch_kh("http://localhost:99999", "/api/nope")
        assert result is None

    @patch("gozerai_telemetry.resilience.urlopen")
    def test_fetch_kh_success(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"data": "test"}'
        mock_resp.status = 200
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _fetch_kh("http://localhost:8011", "/api/test")
        assert result == {"data": "test"}


class TestKHSync:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def sync(self, db):
        return KHSync(db, kh_base_url="http://localhost:8011")

    def test_initial_status(self, sync):
        status = sync.get_sync_status()
        assert status["status"] == "never"
        assert status["last_sync"] is None

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_from_kh_success(self, mock_fetch, sync):
        mock_fetch.return_value = [
            {"category": "technology", "deficit": 5},
            {"category": "business", "deficit": 3},
        ]
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 2
        assert len(result["targets"]) == 2

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_from_kh_unreachable(self, mock_fetch, sync):
        mock_fetch.return_value = None
        result = sync.sync_from_kh()
        assert result["status"] == "failed"
        assert sync.get_sync_status()["status"] == "failed"

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_updates_status(self, mock_fetch, sync):
        mock_fetch.return_value = []
        sync.sync_from_kh()
        status = sync.get_sync_status()
        assert status["status"] == "success"
        assert status["last_sync"] is not None

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_empty_gaps(self, mock_fetch, sync):
        mock_fetch.return_value = []
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 0

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_non_list_response(self, mock_fetch, sync):
        mock_fetch.return_value = {"gaps": []}
        result = sync.sync_from_kh()
        assert result["status"] == "success"
        assert result["new_targets"] == 0

    def test_receive_intelligence_update(self, sync):
        result = sync.receive_intelligence({"event": "intelligence.update", "data": {}})
        assert result["status"] == "accepted"

    def test_receive_intelligence_unknown_event(self, sync):
        result = sync.receive_intelligence({"event": "unknown", "data": {}})
        assert result["status"] == "ignored"

    def test_get_sync_status_includes_url(self, sync):
        status = sync.get_sync_status()
        assert status["kh_base_url"] == "http://localhost:8011"

    @patch("trendscope.integrations.kh_sync._fetch_kh")
    def test_sync_skips_empty_categories(self, mock_fetch, sync):
        mock_fetch.return_value = [
            {"category": "", "deficit": 5},
            {"category": "tech", "deficit": 3},
        ]
        result = sync.sync_from_kh()
        assert result["new_targets"] == 1

    # ── Phase 1: expanded receive_intelligence event types ──

    def test_receive_artifact_stale(self, sync):
        result = sync.receive_intelligence({"event": "artifact.stale", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "stale_alert"

    def test_receive_harvest_complete(self, sync):
        result = sync.receive_intelligence({"event": "harvest.complete", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "sync_refresh"

    def test_receive_graph_materialized(self, sync):
        result = sync.receive_intelligence({"event": "graph.materialized", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "graph_update"

    def test_receive_pipeline_complete(self, sync):
        result = sync.receive_intelligence({"event": "pipeline.run.complete", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "pipeline_complete"

    def test_receive_refresh_complete(self, sync):
        result = sync.receive_intelligence({"event": "refresh.complete", "data": {}})
        assert result["status"] == "accepted"
        assert result["action"] == "refresh_logged"

    def test_receive_snapshot_diff(self, sync):
        result = sync.receive_intelligence({"event": "snapshot.diff", "data": {"added_count": 5}})
        assert result["status"] == "accepted"
        assert result["action"] == "diff_received"

    def test_receive_updates_last_sync(self, sync):
        assert sync._last_sync is None
        sync.receive_intelligence({"event": "artifact.stale", "data": {}})
        assert sync._last_sync is not None

    def test_receive_all_accepted_types_set_success_status(self, sync):
        accepted_events = [
            "intelligence.update", "artifact.stale", "harvest.complete",
            "graph.materialized", "pipeline.run.complete", "refresh.complete",
            "snapshot.diff",
        ]
        for event in accepted_events:
            sync._sync_status = "never"
            result = sync.receive_intelligence({"event": event, "data": {}})
            assert result["status"] == "accepted", f"Expected accepted for {event}"
            assert sync._sync_status == "success", f"Expected success status for {event}"
