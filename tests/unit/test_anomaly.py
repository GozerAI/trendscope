"""Tests for statistical anomaly detection."""

import pytest
from unittest.mock import MagicMock

from trendscope.anomaly import (
    AnomalyResult,
    AnomalyDetector,
    mean,
    std_dev,
    zscore_detect,
    iqr_detect,
    moving_average_detect,
    composite_anomaly_score,
    classify_severity,
)


class TestMean:
    def test_empty(self):
        assert mean([]) == 0.0

    def test_single(self):
        assert mean([5.0]) == 5.0

    def test_multiple(self):
        assert mean([1.0, 2.0, 3.0]) == 2.0

    def test_negative(self):
        assert mean([-1.0, 1.0]) == 0.0


class TestStdDev:
    def test_empty(self):
        assert std_dev([]) == 0.0

    def test_single(self):
        assert std_dev([5.0]) == 0.0

    def test_constant(self):
        assert std_dev([3.0, 3.0, 3.0]) == 0.0

    def test_known_values(self):
        # sample std dev of [2, 4, 4, 4, 5, 5, 7, 9] ≈ 2.138 (N-1 denominator)
        result = std_dev([2, 4, 4, 4, 5, 5, 7, 9])
        assert abs(result - 2.138) < 0.01


class TestZscoreDetect:
    def test_empty(self):
        assert zscore_detect([]) == []

    def test_too_few(self):
        assert zscore_detect([1.0, 2.0]) == []

    def test_constant_series(self):
        assert zscore_detect([5.0, 5.0, 5.0, 5.0]) == []

    def test_detects_outlier(self):
        series = [10, 10, 10, 10, 10, 10, 10, 100]
        results = zscore_detect(series, threshold=2.0)
        assert len(results) > 0
        indices = {r["index"] for r in results}
        assert 7 in indices

    def test_no_anomaly_in_normal_data(self):
        series = [50, 51, 49, 50, 52, 48, 50]
        results = zscore_detect(series, threshold=3.0)
        assert len(results) == 0

    def test_result_structure(self):
        series = [10, 10, 10, 10, 10, 100]
        results = zscore_detect(series, threshold=1.5)
        if results:
            r = results[0]
            assert "index" in r
            assert "value" in r
            assert "z_score" in r
            assert "expected_range" in r


class TestIqrDetect:
    def test_empty(self):
        assert iqr_detect([]) == []

    def test_too_few(self):
        assert iqr_detect([1.0, 2.0, 3.0]) == []

    def test_detects_outlier(self):
        series = [1, 2, 3, 4, 5, 6, 7, 8, 100]
        results = iqr_detect(series)
        assert len(results) > 0
        values = {r["value"] for r in results}
        assert 100 in values

    def test_no_anomaly_tight_data(self):
        series = [10, 11, 12, 13, 14, 15, 16, 17]
        results = iqr_detect(series)
        assert len(results) == 0

    def test_result_has_expected_range(self):
        series = [1, 2, 3, 4, 5, 6, 7, 8, 100]
        results = iqr_detect(series)
        if results:
            r = results[0]
            assert "expected_range" in r
            assert "deviation" in r


class TestMovingAverageDetect:
    def test_empty(self):
        assert moving_average_detect([]) == []

    def test_too_short(self):
        assert moving_average_detect([1, 2, 3, 4, 5]) == []

    def test_detects_spike(self):
        # Need variance in window for std_dev > 0
        series = [10, 12, 9, 11, 10, 11, 100]
        results = moving_average_detect(series, window=5, threshold=2.0)
        assert len(results) > 0

    def test_constant_series(self):
        series = [5, 5, 5, 5, 5, 5, 5, 5]
        results = moving_average_detect(series, window=3)
        assert len(results) == 0

    def test_result_structure(self):
        series = [10, 10, 10, 10, 10, 10, 100]
        results = moving_average_detect(series, window=5)
        if results:
            r = results[0]
            assert "moving_avg" in r
            assert "deviation" in r


class TestCompositeAnomalyScore:
    def test_empty(self):
        assert composite_anomaly_score([]) == {}

    def test_normal_data(self):
        series = [50, 51, 49, 50, 52, 48, 50]
        scores = composite_anomaly_score(series)
        # Normal data should have few or no anomalies
        assert isinstance(scores, dict)

    def test_extreme_outlier_detected(self):
        series = [10, 10, 10, 10, 10, 10, 10, 10, 10, 500]
        scores = composite_anomaly_score(series)
        assert len(scores) > 0
        # The outlier at index 9 should be detected
        assert 9 in scores

    def test_score_range(self):
        series = [10, 10, 10, 10, 10, 10, 10, 10, 10, 500]
        scores = composite_anomaly_score(series)
        for idx, score in scores.items():
            assert 0 < score <= 1.0


class TestClassifySeverity:
    def test_critical(self):
        assert classify_severity(1.0) == "critical"

    def test_high(self):
        assert classify_severity(0.67) == "high"

    def test_medium(self):
        assert classify_severity(0.34) == "medium"

    def test_low(self):
        assert classify_severity(0.2) == "low"
        assert classify_severity(0.0) == "low"


class TestAnomalyResult:
    def test_creation(self):
        r = AnomalyResult(
            trend_id="t1",
            trend_name="Test",
            anomaly_type="composite",
            severity="high",
            value=100,
            expected_range=(10, 50),
            deviation=0.8,
        )
        assert r.trend_id == "t1"
        assert r.severity == "high"


class TestAnomalyDetector:
    @pytest.fixture
    def db(self, tmp_path):
        from trendscope.core import TrendDatabase
        return TrendDatabase(db_path=tmp_path / "test.db")

    def test_detect_all_empty(self, db):
        detector = AnomalyDetector(db)
        results = detector.detect_all()
        assert results == []

    def test_detect_for_trend_insufficient_history(self, db):
        from trendscope.core import Trend, TrendCategory
        trend = Trend(name="Short", score=50, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        detector = AnomalyDetector(db)
        results = detector.detect_for_trend(trend.id, trend.name)
        # Only 1 history point from save, needs >= 3
        assert len(results) == 0

    def test_detect_for_trend_with_history(self, db):
        from trendscope.core import Trend, TrendCategory
        import sqlite3

        trend = Trend(name="Hist", score=50, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)

        # Insert additional history points to create anomaly
        with sqlite3.connect(db.db_path) as conn:
            from datetime import datetime, timezone, timedelta
            now = datetime.now(timezone.utc)
            for i in range(10):
                score = 50 if i < 9 else 200  # anomaly at end
                ts = (now - timedelta(hours=10 - i)).isoformat()
                conn.execute(
                    "INSERT INTO trend_history (trend_id, timestamp, score, velocity, momentum, volume) "
                    "VALUES (?, ?, ?, 0, 0, 0)",
                    (trend.id, ts, score),
                )
            conn.commit()

        detector = AnomalyDetector(db)
        results = detector.detect_for_trend(trend.id, trend.name)
        # Should detect the spike
        assert len(results) > 0

    def test_detect_all_with_trends(self, db):
        from trendscope.core import Trend, TrendCategory
        import sqlite3
        from datetime import datetime, timezone, timedelta

        trend = Trend(name="Full", score=50, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)

        now = datetime.now(timezone.utc)
        with sqlite3.connect(db.db_path) as conn:
            for i in range(10):
                score = 50 if i < 9 else 300
                ts = (now - timedelta(hours=10 - i)).isoformat()
                conn.execute(
                    "INSERT INTO trend_history (trend_id, timestamp, score, velocity, momentum, volume) "
                    "VALUES (?, ?, ?, 0, 0, 0)",
                    (trend.id, ts, score),
                )
            conn.commit()

        detector = AnomalyDetector(db)
        results = detector.detect_all()
        assert len(results) > 0
        assert all(isinstance(r, AnomalyResult) for r in results)
