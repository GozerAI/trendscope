"""
Trend Intelligence - Advanced analysis and correlation.

Provides intelligence capabilities including cross-platform correlation,
drift detection, and opportunity scoring for trend analysis.
"""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendSignal,
    TrendDatabase,
    TrendAnalyzer,
    NicheOpportunity,
)
from trendscope.credibility import SourceCredibilityScorer
from trendscope.forecasting import TrendForecaster
from trendscope.anomaly import AnomalyDetector

logger = logging.getLogger(__name__)


@dataclass
class TrendCorrelation:
    """Represents a correlation between trends."""
    id: str = field(default_factory=lambda: str(uuid4()))
    trend_a_id: str = ""
    trend_b_id: str = ""
    correlation_score: float = 0.0  # -1 to 1
    correlation_type: str = "positive"  # positive, negative, neutral
    shared_keywords: List[str] = field(default_factory=list)
    discovered_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    confidence: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trend_a_id": self.trend_a_id,
            "trend_b_id": self.trend_b_id,
            "correlation_score": self.correlation_score,
            "correlation_type": self.correlation_type,
            "shared_keywords": self.shared_keywords,
            "confidence": self.confidence,
        }


@dataclass
class TrendDrift:
    """Represents a significant change in trend behavior."""
    id: str = field(default_factory=lambda: str(uuid4()))
    trend_id: str = ""
    trend_name: str = ""
    drift_type: str = ""  # surge, decline, volatility, reversal
    magnitude: float = 0.0  # How significant the drift
    previous_value: float = 0.0
    current_value: float = 0.0
    detected_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    analysis: str = ""
    recommended_action: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "trend_id": self.trend_id,
            "trend_name": self.trend_name,
            "drift_type": self.drift_type,
            "magnitude": self.magnitude,
            "previous_value": self.previous_value,
            "current_value": self.current_value,
            "detected_at": self.detected_at.isoformat() if self.detected_at else None,
            "analysis": self.analysis,
            "recommended_action": self.recommended_action,
        }


class TrendDriftDetector:
    """Detects significant changes in trend behavior."""

    def __init__(self, db: TrendDatabase):
        self.db = db
        self.thresholds = {
            "surge": 0.3,  # 30% increase
            "decline": -0.3,  # 30% decrease
            "volatility": 0.5,  # Standard deviation threshold
        }

    def detect_drifts(
        self,
        lookback_days: int = 7,
        min_magnitude: float = 0.2,
    ) -> List[TrendDrift]:
        """Detect drifts in all tracked trends."""
        drifts = []
        trends = self.db.get_trends(limit=100)

        for trend in trends:
            history = self.db.get_trend_history(trend.id, days=lookback_days)
            if len(history) < 2:
                continue

            drift = self._analyze_drift(trend, history)
            if drift and abs(drift.magnitude) >= min_magnitude:
                drifts.append(drift)

        return sorted(drifts, key=lambda d: abs(d.magnitude), reverse=True)

    def _analyze_drift(
        self,
        trend: Trend,
        history: List[Dict[str, Any]],
    ) -> Optional[TrendDrift]:
        """Analyze a single trend for drift."""
        if len(history) < 2:
            return None

        # Get first and last values
        first_score = history[0].get("score", 0)
        last_score = history[-1].get("score", 0)

        if first_score == 0:
            return None

        # Calculate change
        change = (last_score - first_score) / first_score

        if abs(change) < 0.1:
            return None

        # Determine drift type
        if change >= self.thresholds["surge"]:
            drift_type = "surge"
            analysis = f"Trend showing strong upward momentum (+{change*100:.1f}%)"
            action = "Consider increasing exposure to this trend"
        elif change <= self.thresholds["decline"]:
            drift_type = "decline"
            analysis = f"Trend showing significant decline ({change*100:.1f}%)"
            action = "Review positioning and consider reducing exposure"
        else:
            # Check for volatility
            scores = [h.get("score", 0) for h in history]
            mean = sum(scores) / len(scores)
            variance = sum((s - mean) ** 2 for s in scores) / len(scores)
            std_dev = variance ** 0.5

            if std_dev / mean > self.thresholds["volatility"] if mean > 0 else False:
                drift_type = "volatility"
                analysis = f"High volatility detected (std dev: {std_dev:.2f})"
                action = "Monitor closely and set alerts"
            else:
                return None

        return TrendDrift(
            trend_id=trend.id,
            trend_name=trend.name,
            drift_type=drift_type,
            magnitude=abs(change),
            previous_value=first_score,
            current_value=last_score,
            analysis=analysis,
            recommended_action=action,
        )


class OpportunityScorer:
    """Scores market opportunities based on trend data."""

    def __init__(self, db: TrendDatabase):
        self.db = db

        # Weights for opportunity calculation
        self.weights = {
            "trend_strength": 0.20,
            "growth_velocity": 0.25,
            "market_gap": 0.20,
            "entry_feasibility": 0.10,
            "timing": 0.15,
            "ecosystem_maturity": 0.10,
        }

    def score_opportunity(self, niche: NicheOpportunity) -> float:
        """Calculate comprehensive opportunity score."""
        scores = {}

        # Trend strength - based on parent trends
        parent_trends = [self.db.get_trend(tid) for tid in niche.parent_trend_ids]
        parent_trends = [t for t in parent_trends if t is not None]

        if parent_trends:
            avg_score = sum(t.score for t in parent_trends) / len(parent_trends)
            scores["trend_strength"] = avg_score / 100
        else:
            scores["trend_strength"] = 0.5

        # Growth velocity
        if parent_trends:
            avg_velocity = sum(t.velocity for t in parent_trends) / len(parent_trends)
            scores["growth_velocity"] = min(1.0, max(0, (avg_velocity + 1) / 2))
        else:
            scores["growth_velocity"] = 0.5

        # Market gap (inverse of competition)
        scores["market_gap"] = 1 - niche.competition_density

        # Entry feasibility (based on storefront fit)
        scores["entry_feasibility"] = min(1.0, len(niche.storefront_fit) / 3)

        # Timing (based on growth rate)
        scores["timing"] = min(1.0, max(0, niche.growth_rate / 50 + 0.5))

        # Ecosystem maturity (artifact evidence from Knowledge Harvester)
        artifact_evidence = niche.metadata.get("artifact_evidence", {})
        if artifact_evidence:
            artifact_count = artifact_evidence.get("artifact_count", 0)
            avg_quality = artifact_evidence.get("avg_quality", 0)
            # More artifacts + higher quality = more mature ecosystem
            count_score = min(1.0, artifact_count / 20)
            quality_score = avg_quality / 100 if avg_quality else 0.5
            scores["ecosystem_maturity"] = count_score * 0.6 + quality_score * 0.4
        else:
            scores["ecosystem_maturity"] = 0.5  # Neutral default when no data available

        # Weighted sum
        total = sum(
            scores[factor] * weight
            for factor, weight in self.weights.items()
        )

        return round(total * 100, 2)

    def rank_opportunities(
        self,
        niches: List[NicheOpportunity],
    ) -> List[Tuple[NicheOpportunity, float, Dict[str, float]]]:
        """Rank opportunities with detailed scoring."""
        ranked = []

        for niche in niches:
            score = self.score_opportunity(niche)
            details = self._get_score_breakdown(niche)
            ranked.append((niche, score, details))

        return sorted(ranked, key=lambda x: x[1], reverse=True)

    def _get_score_breakdown(self, niche: NicheOpportunity) -> Dict[str, float]:
        """Get detailed score breakdown."""
        parent_trends = [self.db.get_trend(tid) for tid in niche.parent_trend_ids]
        parent_trends = [t for t in parent_trends if t is not None]

        return {
            "trend_count": len(parent_trends),
            "avg_trend_score": sum(t.score for t in parent_trends) / len(parent_trends) if parent_trends else 0,
            "competition_level": niche.competition_density,
            "storefront_coverage": len(niche.storefront_fit),
            "growth_rate": niche.growth_rate,
        }


class TrendIntelligenceManager:
    """Manages trend intelligence and analysis."""

    def __init__(self, db: Optional[TrendDatabase] = None):
        self.db = db or TrendDatabase()
        self.analyzer = TrendAnalyzer(self.db)
        self.drift_detector = TrendDriftDetector(self.db)
        self.opportunity_scorer = OpportunityScorer(self.db)
        self.credibility_scorer = SourceCredibilityScorer()
        self.forecaster = TrendForecaster(self.db)
        self.anomaly_detector = AnomalyDetector(self.db)

        # Cache for correlations
        self._correlation_cache: Dict[str, List[TrendCorrelation]] = {}
        self._cache_ttl = 3600  # 1 hour
        self._cache_timestamp: Optional[datetime] = None

    def analyze_all(self) -> Dict[str, Any]:
        """Run comprehensive analysis on all trends."""
        trends = self.db.get_trends(limit=200)

        # Analyze each trend
        analyzed = []
        for trend in trends:
            analyzed_trend = self.analyzer.analyze_trend(trend)
            self.db.save_trend(analyzed_trend)
            analyzed.append(analyzed_trend)

        # Apply credibility weighting
        for trend in analyzed:
            _, count, sources, multiplier = self.credibility_scorer.apply_weighting(trend, analyzed)
            trend.confidence_multiplier = multiplier
            trend.confirmed_by_sources = sources
            self.db.save_trend(trend)

        # Detect correlations
        correlations = self.find_correlations(analyzed)

        # Detect drifts
        drifts = self.drift_detector.detect_drifts()

        # Get niches
        niches = self.db.get_niches(limit=10)

        return {
            "analyzed_trends": len(analyzed),
            "correlations_found": len(correlations),
            "drifts_detected": len(drifts),
            "active_niches": len(niches),
            "top_drifts": [d.to_dict() for d in drifts[:5]],
            "top_correlations": [c.to_dict() for c in correlations[:5]],
            "analysis_time": datetime.now(timezone.utc).isoformat(),
        }

    def find_correlations(
        self,
        trends: Optional[List[Trend]] = None,
        min_correlation: float = 0.3,
    ) -> List[TrendCorrelation]:
        """Find correlations between trends."""
        if trends is None:
            trends = self.db.get_trends(limit=100)

        correlations = []

        for i, trend_a in enumerate(trends):
            for trend_b in trends[i+1:]:
                correlation = self._calculate_correlation(trend_a, trend_b)
                if abs(correlation.correlation_score) >= min_correlation:
                    correlations.append(correlation)

        return sorted(correlations, key=lambda c: abs(c.correlation_score), reverse=True)

    def _calculate_correlation(self, trend_a: Trend, trend_b: Trend) -> TrendCorrelation:
        """Calculate correlation between two trends."""
        # Keyword overlap
        shared = set(trend_a.keywords) & set(trend_b.keywords)
        keyword_score = len(shared) / max(len(trend_a.keywords), len(trend_b.keywords), 1)

        # Category match
        category_score = 1.0 if trend_a.category == trend_b.category else 0.3

        # Source diversity (different sources correlating is interesting)
        source_score = 0.7 if trend_a.source != trend_b.source else 0.3

        # Velocity correlation
        velocity_diff = abs(trend_a.velocity - trend_b.velocity)
        velocity_score = max(0, 1 - velocity_diff)

        # Composite score
        correlation_score = (
            keyword_score * 0.4 +
            category_score * 0.2 +
            source_score * 0.2 +
            velocity_score * 0.2
        )

        return TrendCorrelation(
            trend_a_id=trend_a.id,
            trend_b_id=trend_b.id,
            correlation_score=correlation_score,
            correlation_type="positive" if correlation_score > 0 else "negative",
            shared_keywords=list(shared),
            confidence=min(trend_a.data_quality, trend_b.data_quality),
        )

    def get_trend_signals(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get buy/sell signals for all trends."""
        trends = self.db.get_trends(limit=50)

        signals = {
            "strong_buy": [],
            "buy": [],
            "hold": [],
            "sell": [],
            "strong_sell": [],
        }

        for trend in trends:
            signal = trend.get_signal()
            signal_key = signal.value

            signals[signal_key].append({
                "id": trend.id,
                "name": trend.name,
                "score": trend.score,
                "velocity": trend.velocity,
                "momentum": trend.momentum,
                "category": trend.category.value,
            })

        return signals

    def generate_intelligence_report(self) -> Dict[str, Any]:
        """Generate comprehensive intelligence report."""
        analysis = self.analyze_all()
        signals = self.get_trend_signals()
        niches = self.db.get_niches(limit=10)
        ranked_niches = self.opportunity_scorer.rank_opportunities(niches)

        report = {
            "report_id": str(uuid4()),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "summary": {
                "total_trends_analyzed": analysis["analyzed_trends"],
                "correlations_found": analysis["correlations_found"],
                "drifts_detected": analysis["drifts_detected"],
                "buy_signals": len(signals["strong_buy"]) + len(signals["buy"]),
                "sell_signals": len(signals["strong_sell"]) + len(signals["sell"]),
            },
            "signals": signals,
            "top_opportunities": [
                {
                    "niche": n.to_dict(),
                    "score": score,
                    "breakdown": breakdown,
                }
                for n, score, breakdown in ranked_niches[:5]
            ],
            "alerts": {
                "drifts": analysis["top_drifts"],
                "correlations": analysis["top_correlations"],
            },
            "recommendations": self._generate_recommendations(signals, ranked_niches),
        }

        # Add forecast summary
        trends = self.db.get_top_trends(limit=10)
        forecast_summary = []
        for trend in trends:
            forecast = self.forecaster.forecast_trend(trend.id)
            if forecast:
                forecast_summary.append({
                    "trend_id": trend.id,
                    "trend_name": trend.name,
                    "direction": forecast["direction"],
                    "forecasts": forecast["forecasts"],
                })
        report["forecast_summary"] = forecast_summary

        return report

    def detect_anomalies(self, lookback_days: int = 14):
        """Run anomaly detection on all trends."""
        return self.anomaly_detector.detect_all(lookback_days=lookback_days)

    def _generate_recommendations(
        self,
        signals: Dict[str, List[Dict[str, Any]]],
        ranked_niches: List[Tuple[NicheOpportunity, float, Dict[str, float]]],
    ) -> List[str]:
        """Generate actionable recommendations."""
        recommendations = []

        # Strong buy signals
        if signals["strong_buy"]:
            top = signals["strong_buy"][0]
            recommendations.append(
                f"HIGH PRIORITY: Consider capitalizing on '{top['name']}' trend "
                f"(score: {top['score']:.1f}, velocity: {top['velocity']:.2f})"
            )

        # Top opportunities
        if ranked_niches:
            niche, score, _ = ranked_niches[0]
            recommendations.append(
                f"OPPORTUNITY: '{niche.name}' shows strong potential "
                f"(opportunity score: {score:.1f})"
            )

        # Sell signals
        if signals["strong_sell"]:
            recommendations.append(
                f"WARNING: {len(signals['strong_sell'])} trends showing decline - "
                "review portfolio exposure"
            )

        # Market diversity
        categories = set()
        for signal_list in signals.values():
            for item in signal_list:
                categories.add(item.get("category"))

        if len(categories) < 3:
            recommendations.append(
                "DIVERSIFICATION: Consider expanding trend coverage to more categories"
            )

        return recommendations
