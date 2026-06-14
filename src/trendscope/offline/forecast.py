"""Offline forecast generation from cached trend data.

Item 784: Generates trend forecasts using exponential smoothing on cached
history data when live database/API access is unavailable. Forecasts carry
confidence penalties based on cache staleness.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from trendscope.offline.cache import OfflineTrendCache, CachedTrendData

logger = logging.getLogger(__name__)

DEFAULT_HORIZONS = [7, 30, 90]
MIN_HISTORY_POINTS = 2


@dataclass
class OfflineForecast:
    """A forecast generated from offline/cached data."""

    trend_id: str
    trend_name: str
    data_points: int = 0
    current_level: float = 0.0
    current_trend: float = 0.0
    direction: str = "stable"
    horizons: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    freshness: float = 1.0
    confidence_penalty: float = 0.0
    generated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    warnings: List[str] = field(default_factory=list)

    @property
    def effective_confidence(self) -> float:
        """Confidence after freshness penalty. Range 0.0 to 1.0."""
        return max(0.0, self.freshness - self.confidence_penalty)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend_id": self.trend_id,
            "trend_name": self.trend_name,
            "data_points": self.data_points,
            "current_level": round(self.current_level, 3),
            "current_trend": round(self.current_trend, 4),
            "direction": self.direction,
            "horizons": self.horizons,
            "freshness": round(self.freshness, 3),
            "confidence_penalty": round(self.confidence_penalty, 3),
            "effective_confidence": round(self.effective_confidence, 3),
            "generated_at": self.generated_at.isoformat(),
            "warnings": self.warnings,
        }


class OfflineForecastGenerator:
    """Generate trend forecasts from offline cached data.

    Uses Holt Linear Exponential Smoothing identical to the online TrendForecaster,
    but operates on CachedTrendData and applies freshness-based confidence penalties.
    """

    def __init__(self, cache: OfflineTrendCache, alpha: float = 0.3, beta: float = 0.1):
        self._cache = cache
        self._alpha = alpha
        self._beta = beta

    def forecast(
        self,
        trend_id: str,
        horizons: Optional[List[int]] = None,
    ) -> Optional[OfflineForecast]:
        """Generate a forecast for a single cached trend.

        Returns None if the trend is not cached or has insufficient history.
        """
        entry = self._cache.get(trend_id)
        if entry is None:
            return None
        return self._generate(entry, horizons or DEFAULT_HORIZONS)

    def forecast_all(
        self,
        horizons: Optional[List[int]] = None,
        fresh_only: bool = False,
    ) -> List[OfflineForecast]:
        """Generate forecasts for all cached trends with sufficient history."""
        entries = self._cache.get_all(fresh_only=fresh_only)
        results = []
        for entry in entries:
            fc = self._generate(entry, horizons or DEFAULT_HORIZONS)
            if fc is not None:
                results.append(fc)
        return results

    def forecast_by_source(
        self,
        source: str,
        horizons: Optional[List[int]] = None,
    ) -> List[OfflineForecast]:
        """Generate forecasts for all cached trends from a specific source."""
        entries = self._cache.get_by_source(source)
        results = []
        for entry in entries:
            fc = self._generate(entry, horizons or DEFAULT_HORIZONS)
            if fc is not None:
                results.append(fc)
        return results

    def batch_summary(self, fresh_only: bool = False) -> Dict[str, Any]:
        """Summary statistics across all offline forecasts."""
        forecasts = self.forecast_all(fresh_only=fresh_only)
        if not forecasts:
            return {
                "total_forecasts": 0,
                "avg_confidence": 0.0,
                "direction_distribution": {},
            }
        dir_dist: Dict[str, int] = {}
        for fc in forecasts:
            dir_dist[fc.direction] = dir_dist.get(fc.direction, 0) + 1
        return {
            "total_forecasts": len(forecasts),
            "avg_confidence": round(
                sum(f.effective_confidence for f in forecasts) / len(forecasts), 3
            ),
            "direction_distribution": dir_dist,
            "warnings_count": sum(len(f.warnings) for f in forecasts),
        }

    # -- Private --

    def _generate(self, entry: CachedTrendData, horizons: List[int]) -> Optional[OfflineForecast]:
        """Core forecast generation for a single cache entry."""
        scores = self._extract_scores(entry)
        warnings: List[str] = []

        if len(scores) < MIN_HISTORY_POINTS:
            # Fall back to single-point estimate using current score
            if entry.score <= 0:
                return None
            scores = [entry.score]
            warnings.append("insufficient_history_using_current_score")

        if len(scores) == 1:
            return self._single_point_forecast(entry, scores[0], horizons, warnings)

        # Holt Linear smoothing
        smoothed, level, trend = self._holt_linear(scores)
        errors = [scores[i] - smoothed[i] for i in range(len(scores))]

        horizon_results: Dict[str, Dict[str, Any]] = {}
        for h in horizons:
            predicted = level + trend * h
            ci = self._confidence_interval(errors, h)
            # Apply staleness penalty to CI width (wider when stale)
            staleness_factor = 1.0 + (1.0 - entry.freshness_score) * 2.0
            adjusted_ci = ci * staleness_factor

            horizon_results[f"{h}d"] = {
                "predicted_score": round(max(predicted, 0), 2),
                "confidence_interval": round(adjusted_ci, 2),
                "lower_bound": round(max(predicted - adjusted_ci, 0), 2),
                "upper_bound": round(predicted + adjusted_ci, 2),
                "horizon_days": h,
            }

        direction = "up" if trend > 0.01 else ("down" if trend < -0.01 else "stable")

        # Freshness-based confidence penalty
        penalty = max(0.0, (1.0 - entry.freshness_score) * 0.5)
        if not entry.is_fresh:
            warnings.append("data_past_ttl")
        if entry.is_stale:
            warnings.append("data_severely_stale")

        return OfflineForecast(
            trend_id=entry.trend_id,
            trend_name=entry.trend_name,
            data_points=len(scores),
            current_level=round(level, 3),
            current_trend=round(trend, 4),
            direction=direction,
            horizons=horizon_results,
            freshness=entry.freshness_score,
            confidence_penalty=penalty,
            warnings=warnings,
        )

    def _single_point_forecast(
        self,
        entry: CachedTrendData,
        score: float,
        horizons: List[int],
        warnings: List[str],
    ) -> OfflineForecast:
        """Forecast from a single data point (flat projection with high uncertainty)."""
        warnings.append("single_point_flat_projection")
        # Use velocity hint if available
        velocity_adj = entry.velocity * 0.5 if entry.velocity else 0.0

        horizon_results: Dict[str, Dict[str, Any]] = {}
        for h in horizons:
            predicted = score + velocity_adj * h
            # High uncertainty for single-point forecasts
            ci = score * 0.3 * math.sqrt(h)
            staleness_factor = 1.0 + (1.0 - entry.freshness_score) * 2.0
            adjusted_ci = ci * staleness_factor

            horizon_results[f"{h}d"] = {
                "predicted_score": round(max(predicted, 0), 2),
                "confidence_interval": round(adjusted_ci, 2),
                "lower_bound": round(max(predicted - adjusted_ci, 0), 2),
                "upper_bound": round(predicted + adjusted_ci, 2),
                "horizon_days": h,
            }

        direction = "up" if velocity_adj > 0.01 else ("down" if velocity_adj < -0.01 else "stable")
        penalty = max(0.0, (1.0 - entry.freshness_score) * 0.5) + 0.2  # extra penalty

        return OfflineForecast(
            trend_id=entry.trend_id,
            trend_name=entry.trend_name,
            data_points=1,
            current_level=round(score, 3),
            current_trend=round(velocity_adj, 4),
            direction=direction,
            horizons=horizon_results,
            freshness=entry.freshness_score,
            confidence_penalty=min(penalty, 1.0),
            warnings=warnings,
        )

    def _holt_linear(self, series: List[float]) -> tuple:
        """Holt's Linear Exponential Smoothing."""
        if not series:
            return [], 0.0, 0.0
        if len(series) == 1:
            return [series[0]], series[0], 0.0

        level = series[0]
        trend = series[1] - series[0]
        smoothed = [level]

        for i in range(1, len(series)):
            new_level = self._alpha * series[i] + (1 - self._alpha) * (level + trend)
            new_trend = self._beta * (new_level - level) + (1 - self._beta) * trend
            level = new_level
            trend = new_trend
            smoothed.append(level)

        return smoothed, level, trend

    @staticmethod
    def _confidence_interval(errors: List[float], horizon: int) -> float:
        """95% CI half-width scaled by forecast horizon."""
        if not errors or len(errors) < 2:
            return 0.0
        mean_err = sum(errors) / len(errors)
        variance = sum((e - mean_err) ** 2 for e in errors) / (len(errors) - 1)
        std_dev = math.sqrt(variance)
        return 1.96 * std_dev * math.sqrt(horizon)

    @staticmethod
    def _extract_scores(entry: CachedTrendData) -> List[float]:
        """Extract numeric scores from cached history."""
        scores = []
        for h in entry.history:
            if isinstance(h, dict):
                val = h.get("score", h.get("value"))
                if val is not None:
                    scores.append(float(val))
            elif isinstance(h, (int, float)):
                scores.append(float(h))
        return scores
