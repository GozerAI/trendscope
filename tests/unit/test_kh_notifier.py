"""Tests for KH anomaly notifier."""

import pytest
from unittest.mock import patch, MagicMock
from trendscope.integrations.kh_notifier import (
    KHAnomalyNotifier,
    _post_to_kh,
    TS_TO_KH_CATEGORY,
)

try:
    from gozerai_telemetry.resilience import reset_all_breakers
    _HAS_RESILIENCE = True
except ImportError:
    _HAS_RESILIENCE = False


class FakeAnomaly:
    """Minimal anomaly result for testing."""

    def __init__(self, category=None):
        self.trend_id = "t1"
        self.trend_name = "test"
        self.anomaly_type = "composite"
        self.severity = "high"
        self.value = 90.0
        self.expected_range = (40.0, 60.0)
        self.deviation = 0.8
        self.category = category


class TestPostToKH:
    def setup_method(self):
        if _HAS_RESILIENCE:
            reset_all_breakers()

    def test_graceful_failure(self):
        result = _post_to_kh("http://localhost:99999", "/api/nope", {"a": 1})
        assert result is None

    @patch("urllib.request.urlopen")
    def test_success(self, mock_urlopen):
        if _HAS_RESILIENCE:
            reset_all_breakers()
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'{"ok": true}'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp
        result = _post_to_kh("http://localhost:8011", "/api/research/gaps", {"category": "ai-agent"})
        assert result == {"ok": True}


class TestKHAnomalyNotifier:
    @pytest.fixture
    def notifier(self):
        return KHAnomalyNotifier(kh_base_url="http://localhost:8011")

    def test_notify_empty_anomalies(self, notifier):
        result = notifier.notify_anomalies([])
        assert result["sent"] == 0
        assert result["errors"] == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_single_anomaly(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        result = notifier.notify_anomalies([FakeAnomaly(category="technology")])
        assert result["sent"] == 1
        assert result["errors"] == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_multiple_anomalies_deduplicates_categories(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        anomalies = [
            FakeAnomaly(category="technology"),
            FakeAnomaly(category="technology"),
            FakeAnomaly(category="ecommerce"),
        ]
        result = notifier.notify_anomalies(anomalies)
        # Two unique categories: ai-agent (from technology) and ecommerce
        assert result["sent"] == 2
        assert len(result["categories"]) == 2

    def test_category_mapping(self, notifier):
        assert TS_TO_KH_CATEGORY["technology"] == "ai-agent"
        assert TS_TO_KH_CATEGORY["ecommerce"] == "ecommerce"
        assert TS_TO_KH_CATEGORY["business"] == "lead-gen-crm"
        assert TS_TO_KH_CATEGORY["consumer"] == "customer-support"
        assert TS_TO_KH_CATEGORY["finance"] == "finance-accounting"

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_graceful_degradation_kh_down(self, mock_post, notifier):
        mock_post.return_value = None
        result = notifier.notify_anomalies([FakeAnomaly()])
        assert result["errors"] == 1
        assert result["sent"] == 0

    def test_get_stats_initial(self, notifier):
        stats = notifier.get_stats()
        assert stats["notifications_sent"] == 0
        assert stats["errors"] == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_get_stats_after_notifications(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        notifier.notify_anomalies([FakeAnomaly(category="technology")])
        stats = notifier.get_stats()
        assert stats["notifications_sent"] == 1
        assert stats["errors"] == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_returns_categories_list(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        result = notifier.notify_anomalies([FakeAnomaly(category="ecommerce")])
        assert "categories" in result
        assert "ecommerce" in result["categories"]

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_unknown_category_passes_through(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        result = notifier.notify_anomalies([FakeAnomaly(category="custom_cat")])
        assert "custom_cat" in result["categories"]

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_notify_increments_counters(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        notifier.notify_anomalies([FakeAnomaly(category="technology")])
        assert notifier._notifications_sent == 1
        assert notifier._errors == 0

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_multiple_calls_accumulate_stats(self, mock_post, notifier):
        mock_post.return_value = {"ok": True}
        notifier.notify_anomalies([FakeAnomaly(category="technology")])
        notifier.notify_anomalies([FakeAnomaly(category="ecommerce")])
        stats = notifier.get_stats()
        assert stats["notifications_sent"] == 2

    @patch("trendscope.integrations.kh_notifier._post_to_kh")
    def test_default_category_when_none(self, mock_post, notifier):
        """Anomaly with no category defaults to 'technology' -> 'ai-agent'."""
        mock_post.return_value = {"ok": True}
        result = notifier.notify_anomalies([FakeAnomaly(category=None)])
        assert "ai-agent" in result["categories"]
