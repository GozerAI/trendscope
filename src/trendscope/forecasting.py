"""Trend forecasting using exponential smoothing methods."""

import math
from typing import List, Dict, Optional, Tuple


class TrendForecaster:
    """Forecasts trend scores using Simple and Holt Linear Exponential Smoothing."""

    def __init__(self, db):
        self.db = db

    def exponential_smoothing(self, series: List[float], alpha: float = 0.3) -> List[float]:
        """Simple Exponential Smoothing (SES).

        Returns smoothed series of same length as input.
        """
        if not series:
            return []

        smoothed = [series[0]]
        for i in range(1, len(series)):
            s = alpha * series[i] + (1 - alpha) * smoothed[i - 1]
            smoothed.append(s)
        return smoothed

    def holt_linear(self, series: List[float], alpha: float = 0.3, beta: float = 0.1) -> Tuple[List[float], float, float]:
        """Holt's Linear Exponential Smoothing (double exponential).

        Returns (smoothed_series, final_level, final_trend).
        """
        if not series:
            return [], 0.0, 0.0
        if len(series) == 1:
            return [series[0]], series[0], 0.0

        # Initialize
        level = series[0]
        trend = series[1] - series[0]
        smoothed = [level]

        for i in range(1, len(series)):
            new_level = alpha * series[i] + (1 - alpha) * (level + trend)
            new_trend = beta * (new_level - level) + (1 - beta) * trend
            level = new_level
            trend = new_trend
            smoothed.append(level)

        return smoothed, level, trend

    def calculate_confidence_interval(self, errors: List[float], horizon: int) -> float:
        """Calculate confidence interval width based on forecast errors.

        Returns the 95% CI half-width, scaled by horizon.
        """
        if not errors or len(errors) < 2:
            return 0.0

        mean_error = sum(errors) / len(errors)
        variance = sum((e - mean_error) ** 2 for e in errors) / (len(errors) - 1)
        std_dev = math.sqrt(variance)

        # 95% CI: ~1.96 * std_dev, scaled by sqrt of horizon
        return 1.96 * std_dev * math.sqrt(horizon)

    def forecast_trend(self, trend_id: str, horizons: List[int] = None) -> Optional[Dict]:
        """Generate forecasts for a trend at multiple horizons.

        Args:
            trend_id: The trend to forecast
            horizons: List of days to forecast ahead (default: [7, 30, 90])

        Returns:
            Dict with forecast data, or None if insufficient history.
        """
        if horizons is None:
            horizons = [7, 30, 90]

        # Get trend history
        history = self.db.get_trend_history(trend_id)
        if not history or len(history) < 2:
            return None

        # Extract score series
        scores = [h.get("score", h.get("value", 0)) for h in history]

        # Run Holt Linear smoothing
        smoothed, level, trend = self.holt_linear(scores)

        # Calculate errors for confidence intervals
        errors = [scores[i] - smoothed[i] for i in range(len(scores))]

        # Generate forecasts for each horizon
        forecasts = {}
        for horizon in horizons:
            predicted_value = level + trend * horizon
            ci_width = self.calculate_confidence_interval(errors, horizon)

            forecasts[f"{horizon}d"] = {
                "predicted_score": round(max(predicted_value, 0), 2),
                "confidence_interval": round(ci_width, 2),
                "lower_bound": round(max(predicted_value - ci_width, 0), 2),
                "upper_bound": round(predicted_value + ci_width, 2),
                "horizon_days": horizon,
            }

        # SES forecast for comparison
        ses_smoothed = self.exponential_smoothing(scores)

        return {
            "trend_id": trend_id,
            "data_points": len(scores),
            "current_level": round(level, 2),
            "current_trend": round(trend, 4),
            "direction": "up" if trend > 0.01 else ("down" if trend < -0.01 else "stable"),
            "forecasts": forecasts,
            "ses_last_value": round(ses_smoothed[-1], 2) if ses_smoothed else None,
        }
