"""Tests for autonomy dashboard."""

import pytest
from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase
from trendscope.autonomy import AutonomyDashboard
from trendscope.scheduler import TrendScheduler
from trendscope.coverage import CoverageAnalyzer
from trendscope.feed import IntelligenceFeed


class FakeService:
    """Minimal service mock for autonomy dashboard tests."""

    def __init__(self, db):
        self.db = db
        self._scheduler = TrendScheduler()
        self._coverage_analyzer = CoverageAnalyzer(db)
        self._feed = IntelligenceFeed()
        self._scheduler.register("test_job", 60.0, lambda: None)

    def detect_anomalies(self, lookback_days=1):
        return []


class TestAutonomyDashboard:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def service(self, db):
        return FakeService(db)

    @pytest.fixture
    def dashboard(self, service):
        return AutonomyDashboard(service)

    def test_get_system_pulse_structure(self, dashboard):
        pulse = dashboard.get_system_pulse()
        assert "timestamp" in pulse
        assert "scheduler" in pulse
        assert "anomalies" in pulse
        assert "coverage" in pulse
        assert "feed" in pulse
        assert "health_score" in pulse

    def test_scheduler_status(self, dashboard):
        pulse = dashboard.get_system_pulse()
        sched = pulse["scheduler"]
        assert sched["status"] == "ok"
        assert sched["total"] == 1

    def test_anomaly_status(self, dashboard):
        pulse = dashboard.get_system_pulse()
        assert pulse["anomalies"]["status"] == "ok"
        assert pulse["anomalies"]["recent_count"] == 0

    def test_coverage_status(self, dashboard):
        pulse = dashboard.get_system_pulse()
        cov = pulse["coverage"]
        assert cov["status"] == "ok"

    def test_feed_status(self, dashboard):
        pulse = dashboard.get_system_pulse()
        assert pulse["feed"]["status"] == "ok"
        assert pulse["feed"]["events_last_hour"] == 0

    def test_get_timeline_empty(self, dashboard):
        timeline = dashboard.get_timeline(hours=24)
        assert timeline == []

    def test_get_timeline_with_events(self, dashboard):
        dashboard.service._feed.push_event("test", {"x": 1})
        timeline = dashboard.get_timeline(hours=24)
        assert len(timeline) == 1

    def test_health_score_perfect(self, dashboard):
        score = dashboard.get_health_score()
        assert 0 <= score <= 100

    def test_health_score_with_errors(self, dashboard):
        # Simulate a scheduler error
        dashboard.service._scheduler.register("failing", 60.0, lambda: (_ for _ in ()).throw(RuntimeError("fail")))
        dashboard.service._scheduler.run_now("failing")
        score = dashboard.get_health_score()
        assert score < 100

    def test_health_score_clamped(self, dashboard):
        score = dashboard.get_health_score()
        assert 0 <= score <= 100

    def test_pulse_with_feed_events(self, dashboard):
        dashboard.service._feed.push_event("anomaly", {"level": "high"})
        dashboard.service._feed.push_event("refresh", {"count": 5})
        pulse = dashboard.get_system_pulse()
        assert pulse["feed"]["events_last_hour"] == 2

    def test_dashboard_handles_missing_subsystems(self):
        class BrokenService:
            pass
        dashboard = AutonomyDashboard(BrokenService())
        pulse = dashboard.get_system_pulse()
        assert pulse["scheduler"]["status"] == "unavailable"
        assert pulse["anomalies"]["status"] == "unavailable"
        assert pulse["coverage"]["status"] == "unavailable"
        assert pulse["feed"]["status"] == "unavailable"
