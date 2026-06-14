"""Offline trend analysis using cached data when live sources are unavailable.

Item 756: Performs trend scoring, ranking, correlation, and status classification
entirely from cached data, with freshness-weighted confidence adjustments.
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from trendscope.offline.cache import OfflineTrendCache, CachedTrendData

logger = logging.getLogger(__name__)

# Weights for offline composite score (freshness-adjusted)
_W_SCORE = 0.30
_W_VELOCITY = 0.25
_W_MOMENTUM = 0.25
_W_VOLUME_NORM = 0.20

# Volume normalization cap (anything above this gets score 1.0)
_VOLUME_CAP = 10_000


@dataclass
class OfflineAnalysisResult:
    """Result of an offline trend analysis pass."""

    trend_id: str
    trend_name: str
    composite_score: float = 0.0
    rank: int = 0
    status: str = "unknown"
    freshness: float = 1.0
    confidence: float = 1.0
    velocity: float = 0.0
    momentum: float = 0.0
    direction: str = "stable"
    details: Dict[str, Any] = field(default_factory=dict)
    analyzed_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend_id": self.trend_id,
            "trend_name": self.trend_name,
            "composite_score": round(self.composite_score, 3),
            "rank": self.rank,
            "status": self.status,
            "freshness": round(self.freshness, 3),
            "confidence": round(self.confidence, 3),
            "velocity": round(self.velocity, 4),
            "momentum": round(self.momentum, 4),
            "direction": self.direction,
            "analyzed_at": self.analyzed_at.isoformat(),
        }


@dataclass
class OfflineCorrelation:
    """Correlation between two offline-analyzed trends."""

    trend_a_id: str
    trend_b_id: str
    correlation: float = 0.0
    basis: str = "score"  # what metric correlation is based on

    def to_dict(self) -> Dict[str, Any]:
        return {
            "trend_a_id": self.trend_a_id,
            "trend_b_id": self.trend_b_id,
            "correlation": round(self.correlation, 4),
            "basis": self.basis,
        }


class OfflineTrendAnalyzer:
    """Performs trend analysis entirely from offline cached data.

    All outputs are weighted by data freshness so consumers know
    how much to trust stale results.
    """

    def __init__(self, cache: OfflineTrendCache):
        self._cache = cache

    def analyze_all(self, fresh_only: bool = False) -> List[OfflineAnalysisResult]:
        """Analyze all cached trends and return ranked results.

        Args:
            fresh_only: If True, skip entries past their TTL.

        Returns:
            List of analysis results sorted by composite score descending.
        """
        entries = self._cache.get_all(fresh_only=fresh_only)
        if not entries:
            return []

        max_volume = max((e.volume for e in entries), default=1) or 1

        results: List[OfflineAnalysisResult] = []
        for entry in entries:
            result = self._analyze_entry(entry, max_volume)
            results.append(result)

        # Sort descending by composite_score
        results.sort(key=lambda r: r.composite_score, reverse=True)

        # Assign ranks
        for i, r in enumerate(results, 1):
            r.rank = i

        return results

    def analyze_one(self, trend_id: str) -> Optional[OfflineAnalysisResult]:
        """Analyze a single cached trend."""
        entry = self._cache.get(trend_id)
        if entry is None:
            return None
        # Need max volume from all entries for normalization
        all_entries = self._cache.get_all()
        max_volume = max((e.volume for e in all_entries), default=1) or 1
        return self._analyze_entry(entry, max_volume)

    def analyze_by_source(self, source: str) -> List[OfflineAnalysisResult]:
        """Analyze all cached trends from a specific source."""
        entries = self._cache.get_by_source(source)
        if not entries:
            return []
        max_volume = max((e.volume for e in entries), default=1) or 1
        results = [self._analyze_entry(e, max_volume) for e in entries]
        results.sort(key=lambda r: r.composite_score, reverse=True)
        for i, r in enumerate(results, 1):
            r.rank = i
        return results

    def analyze_by_category(self, category: str) -> List[OfflineAnalysisResult]:
        """Analyze all cached trends in a specific category."""
        entries = self._cache.get_by_category(category)
        if not entries:
            return []
        max_volume = max((e.volume for e in entries), default=1) or 1
        results = [self._analyze_entry(e, max_volume) for e in entries]
        results.sort(key=lambda r: r.composite_score, reverse=True)
        for i, r in enumerate(results, 1):
            r.rank = i
        return results

    def top_trends(self, n: int = 10, fresh_only: bool = False) -> List[OfflineAnalysisResult]:
        """Return the top N trends by composite score."""
        results = self.analyze_all(fresh_only=fresh_only)
        return results[:n]

    def correlate(self, trend_a_id: str, trend_b_id: str) -> Optional[OfflineCorrelation]:
        """Compute score-history correlation between two cached trends.

        Uses Pearson correlation on the cached history score series.
        Returns None if either trend lacks history data.
        """
        entry_a = self._cache.get(trend_a_id)
        entry_b = self._cache.get(trend_b_id)
        if entry_a is None or entry_b is None:
            return None

        scores_a = self._extract_history_scores(entry_a)
        scores_b = self._extract_history_scores(entry_b)

        if not scores_a or not scores_b:
            return None

        # Truncate to equal length
        min_len = min(len(scores_a), len(scores_b))
        scores_a = scores_a[:min_len]
        scores_b = scores_b[:min_len]

        corr = self._pearson(scores_a, scores_b)
        return OfflineCorrelation(
            trend_a_id=trend_a_id,
            trend_b_id=trend_b_id,
            correlation=corr,
            basis="score_history",
        )

    def find_emerging(self, velocity_threshold: float = 0.2) -> List[OfflineAnalysisResult]:
        """Find trends with velocity above threshold (emerging/growing)."""
        results = self.analyze_all()
        return [r for r in results if r.velocity >= velocity_threshold]

    def find_declining(self, velocity_threshold: float = -0.2) -> List[OfflineAnalysisResult]:
        """Find trends with velocity below threshold (declining)."""
        results = self.analyze_all()
        return [r for r in results if r.velocity <= velocity_threshold]

    def summary(self) -> Dict[str, Any]:
        """Return a summary of the offline analysis state."""
        results = self.analyze_all()
        cache_stats = self._cache.stats()
        status_counts: Dict[str, int] = {}
        for r in results:
            status_counts[r.status] = status_counts.get(r.status, 0) + 1

        return {
            "total_analyzed": len(results),
            "avg_composite_score": (
                round(sum(r.composite_score for r in results) / len(results), 3)
                if results else 0.0
            ),
            "avg_confidence": (
                round(sum(r.confidence for r in results) / len(results), 3)
                if results else 0.0
            ),
            "status_distribution": status_counts,
            "cache": cache_stats,
        }

    # -- Private helpers --

    def _analyze_entry(self, entry: CachedTrendData, max_volume: int) -> OfflineAnalysisResult:
        """Compute composite score and classify a single entry."""
        freshness = entry.freshness_score
        norm_score = min(entry.score / 100.0, 1.0) if entry.score else 0.0
        norm_velocity = min(max(entry.velocity, -1.0), 1.0)
        norm_momentum = min(max(entry.momentum, -1.0), 1.0)
        norm_volume = min(entry.volume / min(max_volume, _VOLUME_CAP), 1.0)

        composite = (
            _W_SCORE * norm_score
            + _W_VELOCITY * ((norm_velocity + 1) / 2)  # shift to 0-1
            + _W_MOMENTUM * ((norm_momentum + 1) / 2)
            + _W_VOLUME_NORM * norm_volume
        )

        # Weight by freshness: stale data yields lower confidence
        confidence = freshness
        composite *= freshness

        # Classify status
        status = self._classify_status(entry.velocity)
        direction = self._classify_direction(entry.velocity)

        return OfflineAnalysisResult(
            trend_id=entry.trend_id,
            trend_name=entry.trend_name,
            composite_score=composite,
            status=status,
            freshness=freshness,
            confidence=confidence,
            velocity=entry.velocity,
            momentum=entry.momentum,
            direction=direction,
        )

    @staticmethod
    def _classify_status(velocity: float) -> str:
        if velocity >= 0.5:
            return "emerging"
        elif velocity >= 0.2:
            return "growing"
        elif velocity >= -0.2:
            return "stable"
        elif velocity >= -0.5:
            return "declining"
        else:
            return "fading"

    @staticmethod
    def _classify_direction(velocity: float) -> str:
        if velocity > 0.01:
            return "up"
        elif velocity < -0.01:
            return "down"
        return "stable"

    @staticmethod
    def _extract_history_scores(entry: CachedTrendData) -> List[float]:
        """Pull numeric scores from history list."""
        scores = []
        for h in entry.history:
            if isinstance(h, dict):
                val = h.get("score", h.get("value"))
                if val is not None:
                    scores.append(float(val))
            elif isinstance(h, (int, float)):
                scores.append(float(h))
        return scores

    @staticmethod
    def _pearson(xs: List[float], ys: List[float]) -> float:
        """Compute Pearson correlation coefficient."""
        n = len(xs)
        if n < 2:
            return 0.0
        mx = sum(xs) / n
        my = sum(ys) / n
        cov = sum((xs[i] - mx) * (ys[i] - my) for i in range(n))
        var_x = sum((x - mx) ** 2 for x in xs)
        var_y = sum((y - my) ** 2 for y in ys)
        denom = math.sqrt(var_x * var_y)
        if denom == 0:
            return 0.0
        return cov / denom
