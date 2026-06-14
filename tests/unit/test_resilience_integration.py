"""Integration tests for resilience patterns in Trendscope KH integration.

Verifies that KH sync and anomaly notifier clients degrade gracefully
when circuit breakers trip, and that breakers are independent.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from gozerai_telemetry.resilience import (
    CircuitState,
    get_circuit_breaker,
    reset_all_breakers,
)
from trendscope.integrations.kh_sync import KHSync, _fetch_kh
from trendscope.integrations.kh_notifier import KHAnomalyNotifier, _post_to_kh


def _trip_breaker(name: str, failure_threshold: int = 3) -> None:
    """Pre-trip a named circuit breaker by recording enough failures."""
    cb = get_circuit_breaker(name, failure_threshold=failure_threshold, recovery_timeout=120)
    for _ in range(failure_threshold):
        cb.record_failure()
    assert cb.state == CircuitState.OPEN


def _mock_urlopen_ok(data):
    """Return a context-manager mock that yields valid JSON."""
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(data).encode()
    mock_resp.status = 200
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    return mock_resp


class TestKHSyncResilience:
    """Tests for _fetch_kh and KHSync graceful degradation."""

    def setup_method(self):
        reset_all_breakers()

    def test_fetch_kh_returns_none_when_cb_open(self):
        """_fetch_kh returns None immediately when the 'kh' circuit breaker
        is already OPEN (no network call made)."""
        _trip_breaker("kh", failure_threshold=3)

        result = _fetch_kh("http://localhost:59999", "/api/coverage/gaps")
        assert result is None

    def test_fetch_kh_succeeds_when_cb_closed(self):
        """_fetch_kh returns data normally when the breaker is CLOSED."""
        expected = [{"category": "ai-agent", "deficit": 5}]
        with patch("gozerai_telemetry.resilience.urlopen",
                    return_value=_mock_urlopen_ok(expected)):
            result = _fetch_kh("http://localhost:8011", "/api/coverage/gaps")
        assert result == expected

    def test_sync_from_kh_returns_failed_when_retries_exhausted(self):
        """KHSync.sync_from_kh() returns failed status when KH is unreachable
        and all retries are exhausted (CB trips)."""
        _trip_breaker("kh", failure_threshold=3)

        sync = KHSync(db=MagicMock(), kh_base_url="http://localhost:59999")
        result = sync.sync_from_kh()

        assert result["status"] == "failed"
        assert "unreachable" in result["reason"].lower() or "KH" in result["reason"]

    def test_after_reset_all_breakers_fetch_kh_tries_again(self):
        """After reset_all_breakers(), a previously tripped breaker allows
        requests again."""
        _trip_breaker("kh", failure_threshold=3)
        assert _fetch_kh("http://localhost:59999", "/api/test") is None

        reset_all_breakers()

        # Now the breaker is gone; a new one will be created in CLOSED state.
        # The call will attempt a real connection (and fail), but it will
        # actually try rather than being short-circuited.
        expected = {"ok": True}
        with patch("gozerai_telemetry.resilience.urlopen",
                    return_value=_mock_urlopen_ok(expected)):
            result = _fetch_kh("http://localhost:8011", "/api/test")
        assert result == expected


class TestKHNotifierResilience:
    """Tests for _post_to_kh and KHAnomalyNotifier graceful degradation."""

    def setup_method(self):
        reset_all_breakers()

    def test_post_to_kh_returns_none_when_cb_open(self):
        """_post_to_kh returns None when the 'kh_notifier' breaker is OPEN."""
        _trip_breaker("kh_notifier", failure_threshold=3)

        result = _post_to_kh(
            "http://localhost:59999", "/api/research/gaps",
            {"source": "test"},
        )
        assert result is None

    def test_notify_anomalies_counts_errors_when_cb_open(self):
        """KHAnomalyNotifier.notify_anomalies() increments error count when
        the circuit breaker is open."""
        _trip_breaker("kh_notifier", failure_threshold=3)

        notifier = KHAnomalyNotifier(kh_base_url="http://localhost:59999")

        # Create mock anomalies with a category attribute
        anomaly = MagicMock()
        anomaly.category = "technology"
        result = notifier.notify_anomalies([anomaly])

        assert result["errors"] >= 1
        assert result["sent"] == 0
        assert notifier._errors >= 1

    def test_breakers_independent_between_sync_and_notifier(self):
        """Tripping kh_notifier does not affect the 'kh' breaker used by sync."""
        _trip_breaker("kh_notifier", failure_threshold=3)

        kh_cb = get_circuit_breaker("kh", failure_threshold=3, recovery_timeout=120)
        assert kh_cb.state == CircuitState.CLOSED
        assert kh_cb.allow_request()

    def test_reset_all_breakers_restores_notifier(self):
        """After reset_all_breakers(), the kh_notifier breaker is fresh."""
        _trip_breaker("kh_notifier", failure_threshold=3)
        assert _post_to_kh("http://localhost:59999", "/test", {}) is None

        reset_all_breakers()

        cb = get_circuit_breaker("kh_notifier", failure_threshold=3, recovery_timeout=120)
        assert cb.state == CircuitState.CLOSED
        assert cb.allow_request()
