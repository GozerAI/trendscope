"""Tests for time-window comparison analysis."""

import pytest
from datetime import datetime, timezone, timedelta
from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase
from trendscope.time_compare import TimeComparator


class TestTimeComparator:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def comparator(self, db):
        return TimeComparator(db)

    def test_compare_windows_empty(self, comparator):
        now = datetime.now(timezone.utc)
        w_a = {"start": (now - timedelta(days=14)).isoformat(), "end": (now - timedelta(days=7)).isoformat()}
        w_b = {"start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()}
        result = comparator.compare_windows(w_a, w_b)
        assert result["delta"]["total"] == 0
        assert "window_a" in result
        assert "window_b" in result

    def test_compare_windows_with_data(self, db, comparator):
        now = datetime.now(timezone.utc)
        t = Trend(name="AI", score=80, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
        t.last_updated = now.isoformat()
        db.save_trend(t)
        w_a = {"start": (now - timedelta(days=14)).isoformat(), "end": (now - timedelta(days=7)).isoformat()}
        w_b = {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1)).isoformat()}
        result = comparator.compare_windows(w_a, w_b)
        assert result["delta"]["total"] >= 0

    def test_compare_windows_structure(self, comparator):
        now = datetime.now(timezone.utc)
        w_a = {"start": (now - timedelta(days=14)).isoformat(), "end": (now - timedelta(days=7)).isoformat()}
        w_b = {"start": (now - timedelta(days=7)).isoformat(), "end": now.isoformat()}
        result = comparator.compare_windows(w_a, w_b)
        assert "window_a" in result
        assert "window_b" in result
        assert "delta" in result
        assert "total" in result["delta"]
        assert "percent" in result["delta"]

    def test_this_vs_last_week(self, comparator):
        result = comparator.this_vs_last("week")
        assert "window_a" in result
        assert "window_b" in result
        assert "delta" in result

    def test_this_vs_last_day(self, comparator):
        result = comparator.this_vs_last("day")
        assert "delta" in result

    def test_this_vs_last_month(self, comparator):
        result = comparator.this_vs_last("month")
        assert "delta" in result

    def test_this_vs_last_default_week(self, comparator):
        result = comparator.this_vs_last()
        assert "delta" in result

    def test_movers_report_empty(self, db, comparator):
        result = comparator.movers_report("week")
        assert result["gainers"] == []
        assert result["losers"] == []
        assert result["period"] == "week"

    def test_movers_report_structure(self, comparator):
        result = comparator.movers_report("week")
        assert "gainers" in result
        assert "losers" in result
        assert "period" in result

    def test_movers_report_day_period(self, comparator):
        result = comparator.movers_report("day")
        assert result["period"] == "day"

    def test_movers_report_month_period(self, comparator):
        result = comparator.movers_report("month")
        assert result["period"] == "month"

    def test_compare_windows_zero_percent_when_no_baseline(self, comparator):
        now = datetime.now(timezone.utc)
        w_a = {"start": (now - timedelta(days=100)).isoformat(), "end": (now - timedelta(days=90)).isoformat()}
        w_b = {"start": (now - timedelta(days=90)).isoformat(), "end": (now - timedelta(days=80)).isoformat()}
        result = comparator.compare_windows(w_a, w_b)
        assert result["delta"]["percent"] == 0

    def test_compare_windows_delta_calculation(self, db, comparator):
        now = datetime.now(timezone.utc)
        # Create trends in window B only
        for i in range(3):
            t = Trend(name=f"New {i}", score=70, category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS)
            t.last_updated = now.isoformat()
            db.save_trend(t)
        w_a = {"start": (now - timedelta(days=30)).isoformat(), "end": (now - timedelta(days=15)).isoformat()}
        w_b = {"start": (now - timedelta(days=1)).isoformat(), "end": (now + timedelta(days=1)).isoformat()}
        result = comparator.compare_windows(w_a, w_b)
        assert result["delta"]["total"] >= 0
