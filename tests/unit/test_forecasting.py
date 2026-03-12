"""Unit tests for Trendscope forecasting module."""

import math

import pytest

from trendscope.forecasting import TrendForecaster


# =============================================================================
# Mock database
# =============================================================================


class MockDb:
    def __init__(self, history=None):
        self._history = history or []

    def get_trend_history(self, trend_id):
        return self._history


# =============================================================================
# exponential_smoothing
# =============================================================================


class TestExponentialSmoothing:

    def test_empty_series_returns_empty(self):
        f = TrendForecaster(MockDb())
        assert f.exponential_smoothing([]) == []

    def test_single_value_returns_that_value(self):
        f = TrendForecaster(MockDb())
        assert f.exponential_smoothing([5.0]) == [5.0]

    def test_constant_series_returns_constant(self):
        f = TrendForecaster(MockDb())
        result = f.exponential_smoothing([10.0, 10.0, 10.0, 10.0])
        assert all(v == pytest.approx(10.0) for v in result)

    def test_increasing_series_smooths_toward_values(self):
        f = TrendForecaster(MockDb())
        series = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = f.exponential_smoothing(series, alpha=0.3)
        assert len(result) == 5
        # Smoothed values should lag behind the actual values
        for i in range(1, len(result)):
            assert result[i] < series[i]

    def test_alpha_one_returns_original_series(self):
        f = TrendForecaster(MockDb())
        series = [1.0, 5.0, 3.0, 7.0]
        result = f.exponential_smoothing(series, alpha=1.0)
        assert result == series

    def test_alpha_zero_returns_constant_first_value(self):
        f = TrendForecaster(MockDb())
        series = [10.0, 20.0, 30.0, 40.0]
        result = f.exponential_smoothing(series, alpha=0.0)
        assert all(v == pytest.approx(10.0) for v in result)

    def test_default_alpha_produces_expected_values(self):
        f = TrendForecaster(MockDb())
        series = [10.0, 20.0, 30.0]
        result = f.exponential_smoothing(series)  # alpha=0.3
        assert len(result) == 3
        assert result[0] == pytest.approx(10.0)
        # s1 = 0.3*20 + 0.7*10 = 13.0
        assert result[1] == pytest.approx(13.0)
        # s2 = 0.3*30 + 0.7*13 = 18.1
        assert result[2] == pytest.approx(18.1)


# =============================================================================
# holt_linear
# =============================================================================


class TestHoltLinear:

    def test_empty_series(self):
        f = TrendForecaster(MockDb())
        smoothed, level, trend = f.holt_linear([])
        assert smoothed == []
        assert level == 0.0
        assert trend == 0.0

    def test_single_point(self):
        f = TrendForecaster(MockDb())
        smoothed, level, trend = f.holt_linear([42.0])
        assert smoothed == [42.0]
        assert level == 42.0
        assert trend == 0.0

    def test_linear_increasing_series_positive_trend(self):
        f = TrendForecaster(MockDb())
        series = [10.0, 20.0, 30.0, 40.0, 50.0]
        _, level, trend = f.holt_linear(series)
        assert trend > 0

    def test_linear_decreasing_series_negative_trend(self):
        f = TrendForecaster(MockDb())
        series = [50.0, 40.0, 30.0, 20.0, 10.0]
        _, level, trend = f.holt_linear(series)
        assert trend < 0

    def test_constant_series_trend_near_zero(self):
        f = TrendForecaster(MockDb())
        series = [25.0, 25.0, 25.0, 25.0, 25.0]
        _, level, trend = f.holt_linear(series)
        assert abs(trend) < 0.01
        assert level == pytest.approx(25.0, abs=0.1)

    def test_returns_smoothed_series_of_correct_length(self):
        f = TrendForecaster(MockDb())
        series = [1.0, 2.0, 3.0, 4.0]
        smoothed, _, _ = f.holt_linear(series)
        assert len(smoothed) == len(series)

    def test_level_and_trend_values_are_reasonable(self):
        f = TrendForecaster(MockDb())
        series = [10.0, 12.0, 14.0, 16.0, 18.0]
        _, level, trend = f.holt_linear(series)
        # Level should be near last value
        assert 15.0 < level < 20.0
        # Trend should be near 2.0 (constant increment)
        assert 1.0 < trend < 3.0


# =============================================================================
# calculate_confidence_interval
# =============================================================================


class TestCalculateConfidenceInterval:

    def test_empty_errors_returns_zero(self):
        f = TrendForecaster(MockDb())
        assert f.calculate_confidence_interval([], 7) == 0.0

    def test_single_error_returns_zero(self):
        f = TrendForecaster(MockDb())
        assert f.calculate_confidence_interval([1.5], 7) == 0.0

    def test_larger_errors_wider_interval(self):
        f = TrendForecaster(MockDb())
        small_errors = [0.1, -0.1, 0.05, -0.05]
        large_errors = [5.0, -5.0, 3.0, -3.0]
        ci_small = f.calculate_confidence_interval(small_errors, 7)
        ci_large = f.calculate_confidence_interval(large_errors, 7)
        assert ci_large > ci_small

    def test_longer_horizon_wider_interval(self):
        f = TrendForecaster(MockDb())
        errors = [1.0, -1.0, 0.5, -0.5, 0.3]
        ci_short = f.calculate_confidence_interval(errors, 7)
        ci_long = f.calculate_confidence_interval(errors, 90)
        assert ci_long > ci_short

    def test_zero_errors_zero_interval(self):
        f = TrendForecaster(MockDb())
        errors = [0.0, 0.0, 0.0, 0.0]
        assert f.calculate_confidence_interval(errors, 7) == 0.0


# =============================================================================
# forecast_trend
# =============================================================================


class TestForecastTrend:

    def test_returns_none_with_empty_history(self):
        f = TrendForecaster(MockDb(history=[]))
        assert f.forecast_trend("t1") is None

    def test_returns_none_with_single_data_point(self):
        f = TrendForecaster(MockDb(history=[{"score": 50.0}]))
        assert f.forecast_trend("t1") is None

    def test_returns_forecasts_for_default_horizons(self):
        history = [{"score": float(i * 10)} for i in range(1, 6)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert "7d" in result["forecasts"]
        assert "30d" in result["forecasts"]
        assert "90d" in result["forecasts"]

    def test_custom_horizons_work(self):
        history = [{"score": float(i * 5)} for i in range(1, 8)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1", horizons=[3, 14])
        assert result is not None
        assert "3d" in result["forecasts"]
        assert "14d" in result["forecasts"]
        assert "7d" not in result["forecasts"]

    def test_predicted_scores_are_non_negative(self):
        # Use a declining series that could project below zero
        history = [{"score": float(50 - i * 10)} for i in range(6)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        for key, forecast in result["forecasts"].items():
            assert forecast["predicted_score"] >= 0
            assert forecast["lower_bound"] >= 0

    def test_direction_is_up_for_positive_trend(self):
        history = [{"score": float(i * 10)} for i in range(1, 8)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert result["direction"] == "up"

    def test_direction_is_down_for_negative_trend(self):
        history = [{"score": float(80 - i * 10)} for i in range(8)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert result["direction"] == "down"

    def test_direction_is_stable_for_near_zero_trend(self):
        history = [{"score": 50.0} for _ in range(6)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert result["direction"] == "stable"

    def test_includes_confidence_intervals(self):
        history = [{"score": float(i * 10)} for i in range(1, 8)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        for key, forecast in result["forecasts"].items():
            assert "confidence_interval" in forecast
            assert "lower_bound" in forecast
            assert "upper_bound" in forecast
            assert forecast["upper_bound"] >= forecast["lower_bound"]

    def test_includes_data_points_count(self):
        history = [{"score": float(i)} for i in range(1, 11)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert result["data_points"] == 10

    def test_includes_ses_comparison_value(self):
        history = [{"score": float(i * 5)} for i in range(1, 6)]
        f = TrendForecaster(MockDb(history=history))
        result = f.forecast_trend("t1")
        assert result is not None
        assert result["ses_last_value"] is not None
        assert isinstance(result["ses_last_value"], float)
