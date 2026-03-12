"""
Trend Service - High-level service interface for executives.

Provides a clean API for interacting with the
trend intelligence system.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendDatabase,
    TrendAnalyzer,
    NicheOpportunity,
)
from trendscope.collectors import (
    TrendCollectorManager,
    NicheIdentifier,
)
try:
    from trendscope.intelligence import (
        TrendIntelligenceManager,
        TrendCorrelation,
        TrendDrift,
    )
    _HAS_INTELLIGENCE = True
except ImportError:
    _HAS_INTELLIGENCE = False
from trendscope.alerts import AlertManager
try:
    from trendscope.narratives import NarrativeGenerator
    _HAS_NARRATIVES = True
except ImportError:
    _HAS_NARRATIVES = False
from trendscope.licensing import license_gate
try:
    from trendscope.scheduler import TrendScheduler
    _HAS_SCHEDULER = True
except ImportError:
    _HAS_SCHEDULER = False
try:
    from trendscope.anomaly import AnomalyDetector
    _HAS_ANOMALY = True
except ImportError:
    _HAS_ANOMALY = False
try:
    from trendscope.snapshots import SnapshotManager
    _HAS_SNAPSHOTS = True
except ImportError:
    _HAS_SNAPSHOTS = False
try:
    from trendscope.lifecycle import LifecycleTracker
    _HAS_LIFECYCLE = True
except ImportError:
    _HAS_LIFECYCLE = False
try:
    from trendscope.coverage import CoverageAnalyzer
    _HAS_COVERAGE = True
except ImportError:
    _HAS_COVERAGE = False
try:
    from trendscope.time_compare import TimeComparator
    _HAS_TIME_COMPARE = True
except ImportError:
    _HAS_TIME_COMPARE = False
try:
    from trendscope.feed import IntelligenceFeed
    _HAS_FEED = True
except ImportError:
    _HAS_FEED = False
try:
    from trendscope.integrations.kh_sync import KHSync
    _HAS_KH_SYNC = True
except ImportError:
    _HAS_KH_SYNC = False
try:
    from trendscope.integrations.kh_notifier import KHAnomalyNotifier
    _HAS_KH_NOTIFIER = True
except ImportError:
    _HAS_KH_NOTIFIER = False
try:
    from trendscope.autonomy import AutonomyDashboard
    _HAS_AUTONOMY = True
except ImportError:
    _HAS_AUTONOMY = False

try:
    from trendscope.integrations.kh_client import get_artifacts, get_trending_artifacts, map_ts_category_to_kh
    _HAS_KH = True
except ImportError:
    _HAS_KH = False

try:
    from trendscope.integrations.graph_sync import sync_trends_to_graph
    _HAS_GRAPH_SYNC = True
except ImportError:
    _HAS_GRAPH_SYNC = False

logger = logging.getLogger(__name__)

# Optional telemetry
try:
    from gozerai_telemetry import get_collector, Tracer

    _collector = get_collector("trendscope")
    _tracer = Tracer("trendscope")
    _refresh_counter = _collector.counter("refreshes_total", "Total trend refreshes")
    _trends_gauge = _collector.gauge("trends_collected", "Trends collected last refresh")
    _refresh_duration = _collector.histogram(
        "refresh_duration_seconds", "Refresh duration"
    )
    _analysis_counter = _collector.counter("analyses_total", "Total analysis cycles")
    _HAS_TELEMETRY = True
except ImportError:
    _HAS_TELEMETRY = False


class TrendService:
    """
    High-level trend intelligence service for users.

    This service provides a unified interface for:
    - CMO (Echo): Market trends for campaign planning
    - CPO (Visionary): Product opportunity identification
    - CRO (Axiom): Revenue trend analysis
    - CEO (Apex): Strategic trend overview

    Example:
        ```python
        service = TrendService()
        await service.initialize()

        # Get trend report for CMO
        report = await service.get_executive_report("CMO")

        # Find niche opportunities for CPO
        opportunities = await service.find_opportunities(min_score=60)

        # Collect fresh data
        await service.refresh_trends()
        ```
    """

    def __init__(self, db_path: Optional[str] = None):
        """Initialize the trend service."""
        import os
        from pathlib import Path

        if db_path:
            self.db = TrendDatabase(Path(db_path))
        else:
            self.db = TrendDatabase()

        self.collector_manager = TrendCollectorManager(self.db)
        self.intelligence = TrendIntelligenceManager(self.db) if _HAS_INTELLIGENCE else None
        self.analyzer = TrendAnalyzer(self.db)
        self.alert_manager = AlertManager(self.db)
        self._narrative_generator = NarrativeGenerator() if _HAS_NARRATIVES else None

        # Autonomy subsystems
        self._scheduler = TrendScheduler() if _HAS_SCHEDULER else None
        self._anomaly_detector = AnomalyDetector(self.db) if _HAS_ANOMALY else None
        self._snapshot_manager = SnapshotManager(self.db) if _HAS_SNAPSHOTS else None
        self._lifecycle_tracker = LifecycleTracker(self.db) if _HAS_LIFECYCLE else None
        self._coverage_analyzer = CoverageAnalyzer(self.db) if _HAS_COVERAGE else None
        self._time_comparator = TimeComparator(self.db) if _HAS_TIME_COMPARE else None
        self._feed = IntelligenceFeed() if _HAS_FEED else None
        self._kh_sync = KHSync(self.db) if _HAS_KH_SYNC else None
        self._kh_notifier = None  # KHAnomalyNotifier requires enterprise license
        # self._kh_notifier = KHAnomalyNotifier(
            kh_base_url=os.environ.get("KH_BASE_URL", "http://localhost:8011")
        )
        self._autonomy_dashboard = AutonomyDashboard(self) if _HAS_AUTONOMY else None

        # Register default schedules (callbacks are no-ops initially)
        self._scheduler.register("refresh_trends", 60.0, lambda: None)
        self._scheduler.register("detect_anomalies", 120.0, lambda: None)
        self._scheduler.register("anomaly_scan_and_notify", 360.0, lambda: self.detect_anomalies(lookback_days=1))

        self._initialized = False
        self._last_refresh: Optional[datetime] = None

    async def initialize(self) -> None:
        """Initialize the service with default collectors."""
        if self._initialized:
            return

        self.collector_manager.add_default_collectors()
        self._initialized = True
        logger.info("TrendService initialized")

    async def refresh_trends(self, sources: Optional[List[str]] = None) -> Dict[str, Any]:
        """
        Refresh trend data from sources.

        Args:
            sources: Optional list of source names to refresh. If None, refreshes all.

        Returns:
            Summary of collection results
        """
        if not self._initialized:
            await self.initialize()

        if _HAS_TELEMETRY:
            _refresh_counter.inc()

        if sources:
            trends = []
            for source in sources:
                try:
                    source_trends = await self.collector_manager.collect_from(source)
                    trends.extend(source_trends)
                except ValueError as e:
                    logger.warning(f"Unknown source: {source}")
        else:
            trends = await self.collector_manager.collect_all()

        self._last_refresh = datetime.now(timezone.utc)

        if _HAS_TELEMETRY:
            _trends_gauge.set(len(trends))

        return {
            "trends_collected": len(trends),
            "sources_used": sources or list(self.collector_manager.collectors.keys()),
            "refreshed_at": self._last_refresh.isoformat(),
        }

    async def get_trends(
        self,
        category: Optional[str] = None,
        min_score: float = 0,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Get trends with optional filters.

        Args:
            category: Optional category filter
            min_score: Minimum score threshold
            limit: Maximum number of trends to return

        Returns:
            List of trend dictionaries
        """
        cat = TrendCategory(category) if category else None
        trends = self.db.get_trends(category=cat, min_score=min_score, limit=limit)
        return [t.to_dict() for t in trends]

    async def get_trend(self, trend_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific trend by ID."""
        trend = self.db.get_trend(trend_id)
        return trend.to_dict() if trend else None

    async def search_trends(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search trends by name or keywords."""
        trends = self.db.search_trends(query, limit=limit)
        return [t.to_dict() for t in trends]

    async def get_top_trends(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get top-scoring trends."""
        trends = self.db.get_top_trends(limit=limit)
        return [t.to_dict() for t in trends]

    async def get_emerging_trends(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get emerging trends with high velocity."""
        trends = self.db.get_emerging_trends(limit=limit)
        return [t.to_dict() for t in trends]

    async def find_opportunities(
        self,
        min_score: float = 50,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Find niche market opportunities.

        Args:
            min_score: Minimum opportunity score
            limit: Maximum number of opportunities

        Returns:
            List of niche opportunity dictionaries
        """
        license_gate.gate("std.trendscope.advanced")
        # First, identify new niches from current trends
        niches = self.collector_manager.identify_niches(min_confidence=0.4)

        # Get all niches above threshold
        all_niches = self.db.get_niches(min_score=min_score, limit=limit)

        # Rank them
        ranked = self.intelligence.opportunity_scorer.rank_opportunities(all_niches)

        return [
            {
                "opportunity": n.to_dict(),
                "score": score,
                "breakdown": breakdown,
            }
            for n, score, breakdown in ranked
        ]

    async def get_signals(self) -> Dict[str, List[Dict[str, Any]]]:
        """Get buy/sell signals for trends."""
        return self.intelligence.get_trend_signals()

    async def detect_drifts(self, lookback_days: int = 7) -> List[Dict[str, Any]]:
        """Detect significant trend changes."""
        license_gate.gate("std.trendscope.advanced")
        drifts = self.intelligence.drift_detector.detect_drifts(lookback_days=lookback_days)
        return [d.to_dict() for d in drifts]

    async def find_correlations(self, min_correlation: float = 0.3) -> List[Dict[str, Any]]:
        """Find correlations between trends."""
        license_gate.gate("std.trendscope.advanced")
        correlations = self.intelligence.find_correlations(min_correlation=min_correlation)
        return [c.to_dict() for c in correlations]

    async def get_intelligence_report(self) -> Dict[str, Any]:
        """Generate comprehensive intelligence report."""
        license_gate.gate("std.trendscope.advanced")
        return self.intelligence.generate_intelligence_report()

    async def get_executive_report(self, executive_code: str) -> Dict[str, Any]:
        """
        Generate a report tailored for a specific executive.

        Args:
            executive_code: The executive code (CMO, CPO, CRO, CEO)

        Returns:
            Executive-specific trend report
        """
        license_gate.gate("std.trendscope.enterprise")
        base_report = self.intelligence.generate_intelligence_report()

        if executive_code == "CMO":
            # Marketing focus: campaigns, segments, content trends
            report = {
                "executive": "CMO",
                "focus": "Marketing & Growth",
                "generated_at": base_report["generated_at"],
                "key_trends": await self.get_top_trends(limit=5),
                "emerging_opportunities": await self.get_emerging_trends(limit=5),
                "campaign_signals": {
                    "hot_topics": [s for s in base_report["signals"]["strong_buy"][:3]],
                    "declining_topics": [s for s in base_report["signals"]["strong_sell"][:3]],
                },
                "content_recommendations": self._get_content_recommendations(base_report),
                "market_pulse": base_report["summary"],
            }

        elif executive_code == "CPO":
            # Product focus: opportunities, niches, innovation
            opportunities = await self.find_opportunities(min_score=50, limit=5)
            report = {
                "executive": "CPO",
                "focus": "Product & Innovation",
                "generated_at": base_report["generated_at"],
                "product_opportunities": opportunities,
                "technology_trends": [
                    t for t in await self.get_trends(category="technology", limit=10)
                ],
                "innovation_signals": base_report["signals"]["strong_buy"][:5],
                "market_gaps": [
                    opp["opportunity"]["pain_points"]
                    for opp in opportunities
                    if opp["opportunity"].get("pain_points")
                ],
                "recommendations": base_report["recommendations"],
                "available_tooling": self._get_available_tooling(opportunities) if _HAS_KH else [],
            }

        elif executive_code == "CRO":
            # Revenue focus: commercial trends, pricing signals
            report = {
                "executive": "CRO",
                "focus": "Revenue & Research",
                "generated_at": base_report["generated_at"],
                "commercial_trends": await self.get_trends(category="ecommerce", limit=10),
                "revenue_signals": {
                    "growth": base_report["signals"]["strong_buy"],
                    "caution": base_report["signals"]["strong_sell"],
                },
                "market_drifts": base_report["alerts"]["drifts"],
                "correlations": base_report["alerts"]["correlations"][:5],
                "research_priorities": self._get_research_priorities(base_report),
            }

        elif executive_code == "CEO":
            # Strategic overview: high-level summary
            report = {
                "executive": "CEO",
                "focus": "Strategic Overview",
                "generated_at": base_report["generated_at"],
                "executive_summary": {
                    "trends_analyzed": base_report["summary"]["total_trends_analyzed"],
                    "opportunities_identified": len(base_report["top_opportunities"]),
                    "market_sentiment": self._calculate_sentiment(base_report["signals"]),
                },
                "strategic_signals": base_report["signals"]["strong_buy"][:3],
                "risk_indicators": base_report["signals"]["strong_sell"][:3],
                "top_opportunities": base_report["top_opportunities"][:3],
                "key_recommendations": base_report["recommendations"][:3],
                "ecosystem_health": self._get_ecosystem_health() if _HAS_KH else {},
            }

        else:
            # Default: full report
            return base_report

        # Add narrative briefing
        narrative = self.narrative_generator.generate_briefing(executive_code, report)
        report["narrative"] = narrative
        return report

    def _get_content_recommendations(self, report: Dict[str, Any]) -> List[str]:
        """Generate content recommendations for CMO."""
        recommendations = []

        for signal in report["signals"]["strong_buy"][:3]:
            recommendations.append(f"Create content around '{signal['name']}' - trending upward")

        for signal in report["signals"]["buy"][:2]:
            recommendations.append(f"Consider exploring '{signal['name']}' in upcoming campaigns")

        return recommendations

    def _get_research_priorities(self, report: Dict[str, Any]) -> List[str]:
        """Generate research priorities for CRO."""
        priorities = []

        if report["alerts"]["drifts"]:
            priorities.append(f"Investigate drift: {report['alerts']['drifts'][0]['analysis']}")

        for opp in report["top_opportunities"][:2]:
            priorities.append(f"Research opportunity: {opp['niche']['name']}")

        return priorities

    def _calculate_sentiment(self, signals: Dict[str, List]) -> str:
        """Calculate overall market sentiment."""
        buy_count = len(signals["strong_buy"]) + len(signals["buy"])
        sell_count = len(signals["strong_sell"]) + len(signals["sell"])
        hold_count = len(signals["hold"])

        total = buy_count + sell_count + hold_count
        if total == 0:
            return "neutral"

        buy_ratio = buy_count / total
        sell_ratio = sell_count / total

        if buy_ratio > 0.6:
            return "bullish"
        elif sell_ratio > 0.6:
            return "bearish"
        elif buy_ratio > sell_ratio:
            return "slightly_bullish"
        elif sell_ratio > buy_ratio:
            return "slightly_bearish"
        else:
            return "neutral"

    def _enrich_with_artifacts(self, trends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enrich trend data with artifact evidence from Knowledge Harvester."""
        if not _HAS_KH:
            return trends

        for trend in trends:
            keywords = trend.get("keywords", [])
            category = trend.get("category", "")

            # Get KH categories that map to this trend's category
            kh_categories = map_ts_category_to_kh(category)

            # Query KH for matching artifacts
            artifacts = []
            if kh_categories:
                for kh_cat in kh_categories[:2]:  # Limit queries
                    arts = get_artifacts(category=kh_cat, quality_min=50, limit=5)
                    artifacts.extend(arts)

            if artifacts:
                avg_quality = sum(a.get("quality_score", 0) for a in artifacts) / len(artifacts)
                trend["artifact_evidence"] = {
                    "artifact_count": len(artifacts),
                    "avg_quality": round(avg_quality, 1),
                    "top_artifacts": [
                        {"name": a.get("name", ""), "quality": a.get("quality_score", 0)}
                        for a in sorted(artifacts, key=lambda x: x.get("quality_score", 0), reverse=True)[:3]
                    ],
                }

        return trends

    def _get_available_tooling(self, opportunities: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get available tooling from KH for top opportunities."""
        tooling = []
        for opp in opportunities[:3]:
            niche = opp.get("opportunity", {})
            categories = niche.get("product_categories", [])
            for cat in categories[:1]:
                kh_cats = map_ts_category_to_kh(cat)
                for kh_cat in kh_cats[:1]:
                    artifacts = get_artifacts(category=kh_cat, quality_min=60, limit=3)
                    if artifacts:
                        tooling.append({
                            "opportunity": niche.get("name", ""),
                            "artifacts_available": len(artifacts),
                            "top_artifact": artifacts[0].get("name", "") if artifacts else "",
                        })
        return tooling

    def _get_ecosystem_health(self) -> Dict[str, Any]:
        """Get ecosystem health summary from KH trending artifacts."""
        trending = get_trending_artifacts(limit=10)
        if not trending:
            return {"status": "unknown", "trending_count": 0}

        return {
            "status": "healthy" if len(trending) >= 5 else "growing" if trending else "unknown",
            "trending_count": len(trending),
            "categories": list(set(
                a.get("primary_category", "") for a in trending if a.get("primary_category")
            )),
        }

    def get_telemetry(self) -> Dict[str, Any]:
        """Get telemetry data (metrics + traces). Returns empty dict if telemetry not installed."""
        if not _HAS_TELEMETRY:
            return {}
        return {
            "metrics": _collector.to_dict(),
            "traces": len(_tracer.get_completed()),
        }

    async def get_stats(self) -> Dict[str, Any]:
        """Get service statistics."""
        db_stats = self.db.get_stats()
        collector_stats = self.collector_manager.get_collector_stats()

        return {
            "database": db_stats,
            "collectors": collector_stats,
            "last_refresh": self._last_refresh.isoformat() if self._last_refresh else None,
            "initialized": self._initialized,
        }

    async def run_autonomous_analysis(self) -> Dict[str, Any]:
        """
        Run autonomous analysis cycle.

        This method is designed to be called by the scheduler for
        periodic autonomous trend analysis.
        """
        license_gate.gate("std.trendscope.enterprise")
        if _HAS_TELEMETRY:
            _analysis_counter.inc()

        if not self._initialized:
            await self.initialize()

        # 1. Refresh data
        refresh_result = await self.refresh_trends()

        # 2. Run analysis
        analysis_result = self.intelligence.analyze_all()

        # 3. Identify niches
        niches = self.collector_manager.identify_niches()

        # 4. Detect drifts
        drifts = await self.detect_drifts()

        # 5. Generate report
        report = await self.get_intelligence_report()

        # 6. Evaluate alert rules against analyzed trends
        analyzed_trends = self.db.get_trends(limit=200)
        alerts_triggered = self.alert_manager.evaluate_rules(analyzed_trends)

        # Sync trends to KH intelligence graph
        if _HAS_GRAPH_SYNC:
            try:
                graph_trends = self.db.get_trends(limit=100)
                sync_trends_to_graph(graph_trends)
            except Exception:
                pass  # Graph sync is best-effort

        return {
            "cycle_completed_at": datetime.now(timezone.utc).isoformat(),
            "refresh": refresh_result,
            "analysis": analysis_result,
            "niches_identified": len(niches),
            "drifts_detected": len(drifts),
            "alerts_triggered": len(alerts_triggered),
            "report_generated": True,
            "next_actions": report.get("recommendations", []),
        }

    # =========================================================================
    # Scheduler
    # =========================================================================

    def get_scheduler(self) -> TrendScheduler:
        """Get the scheduler instance."""
        return self._scheduler

    # =========================================================================
    # Anomaly Detection
    # =========================================================================

    def detect_anomalies(self, lookback_days: int = 14) -> list:
        """Run anomaly detection on all trends."""
        results = self._anomaly_detector.detect_all(lookback_days=lookback_days)
        if results:
            self._feed.push_event("anomaly.detected", {
                "count": len(results),
                "severities": list({r.severity for r in results}),
            })
            # Notify KH about anomalies for auto-refresh
            if hasattr(self, '_kh_notifier'):
                try:
                    self._kh_notifier.notify_anomalies(results)
                except Exception:
                    pass  # graceful degradation
        return results

    # =========================================================================
    # Snapshots
    # =========================================================================

    def create_snapshot(self, label: str):
        """Create a point-in-time snapshot."""
        return self._snapshot_manager.create_snapshot(label)

    def list_snapshots(self):
        """List all snapshots."""
        return self._snapshot_manager.list_snapshots()

    def compare_snapshots(self, id1: str, id2: str) -> dict:
        """Compare two snapshots."""
        return self._snapshot_manager.compare_snapshots(id1, id2)

    # =========================================================================
    # Lifecycle
    # =========================================================================

    def get_lifecycle(self, trend_id: str) -> list:
        """Get lifecycle history for a trend."""
        return self._lifecycle_tracker.get_lifecycle(trend_id)

    def get_lifecycle_distribution(self) -> dict:
        """Get distribution of trends across lifecycle stages."""
        return self._lifecycle_tracker.get_stage_distribution()

    def get_aging_trends(self, min_days: int = 7) -> list:
        """Get aging trends."""
        return self._lifecycle_tracker.get_aging_trends(min_days)

    def update_lifecycle(self, trend_id: str, trend=None):
        """Update lifecycle for a single trend."""
        return self._lifecycle_tracker.update_lifecycle(trend_id, trend)

    # =========================================================================
    # Coverage
    # =========================================================================

    def get_coverage_report(self) -> dict:
        """Get category coverage report."""
        return self._coverage_analyzer.get_coverage_report()

    def get_blind_spots(self) -> list:
        """Get coverage blind spots."""
        return self._coverage_analyzer.identify_blind_spots()

    # =========================================================================
    # Time Comparison
    # =========================================================================

    def compare_time_windows(self, period: str = "week") -> dict:
        """Compare current period vs previous."""
        return self._time_comparator.this_vs_last(period)

    def get_movers(self, period: str = "week") -> dict:
        """Get biggest gainers and losers."""
        return self._time_comparator.movers_report(period)

    # =========================================================================
    # Feed
    # =========================================================================

    def get_feed_summary(self, minutes: int = 5) -> dict:
        """Get feed summary."""
        return self._feed.get_summary(minutes)

    # =========================================================================
    # KH Sync
    # =========================================================================

    def sync_with_kh(self) -> dict:
        """Sync with Knowledge Harvester."""
        return self._kh_sync.sync_from_kh()

    def get_sync_status(self) -> dict:
        """Get KH sync status."""
        return self._kh_sync.get_sync_status()

    def receive_kh_intelligence(self, payload: dict) -> dict:
        """Receive intelligence webhook from KH."""
        return self._kh_sync.receive_intelligence(payload)

    # =========================================================================
    # Autonomy Dashboard
    # =========================================================================

    def get_system_pulse(self) -> dict:
        """Get full system pulse."""
        return self._autonomy_dashboard.get_system_pulse()

    def get_autonomy_timeline(self, hours: int = 24) -> list:
        """Get autonomy timeline."""
        return self._autonomy_dashboard.get_timeline(hours)

    def get_health_score(self) -> int:
        """Get system health score."""
        return self._autonomy_dashboard.get_health_score()

    # =========================================================================
    # Research Agent
    # =========================================================================

    def get_strong_buy_trends(self, min_score=80):
        """Get trends with STRONG_BUY signal."""
        from trendscope.integrations.research_hooks import get_strong_buy_trends
        return get_strong_buy_trends(self.db, min_score)

    # =========================================================================
    # Forecasting
    # =========================================================================

    def get_forecast(self, trend_id):
        """Get forecast for a specific trend."""
        return self.intelligence.forecaster.forecast_trend(trend_id)

    def get_forecasts(self, limit=20):
        """Get forecasts for top trends."""
        trends = self.db.get_top_trends(limit=limit)
        forecasts = []
        for trend in trends:
            forecast = self.intelligence.forecaster.forecast_trend(trend.id)
            if forecast:
                forecasts.append(forecast)
        return {"forecasts": forecasts, "total": len(forecasts)}

    # =========================================================================
    # Credibility
    # =========================================================================

    def get_credibility_report(self):
        """Get credibility analysis for all trends."""
        trends = self.db.get_trends(limit=200)
        scorer = self.intelligence.credibility_scorer
        report = []
        for trend in trends:
            _, count, sources, multiplier = scorer.apply_weighting(trend, trends)
            report.append({
                "trend_id": trend.id,
                "trend_name": trend.name,
                "source": trend.source.name,
                "source_weight": scorer.get_source_weight(trend.source.name),
                "confirmation_count": count,
                "confirmed_by": sources,
                "confidence_multiplier": multiplier,
                "original_score": trend.score,
                "weighted_score": trend.score * multiplier,
            })
        return {"trends": report, "total": len(report)}

    # =========================================================================
    # Alerts
    # =========================================================================

    def register_alert_rule(self, name, conditions, webhook_url, secret=""):
        """Register a new alert rule."""
        return self.alert_manager.register_rule(name, conditions, webhook_url, webhook_secret=secret)

    def get_alert_rules(self):
        """Get all alert rules."""
        return self.alert_manager.get_rules()

    def delete_alert_rule(self, rule_id):
        """Delete an alert rule. Returns True if deleted."""
        return self.alert_manager.delete_rule(rule_id)

    def get_alert_history(self, limit=50):
        """Get alert trigger history."""
        return self.alert_manager.get_history(limit=limit)

    # =========================================================================
    # MCP Interface Methods (aliases for consistency with MCP tool handlers)
    # =========================================================================

    async def run_analysis_cycle(
        self,
        sources: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Run analysis cycle - MCP interface alias.

        Alias for run_autonomous_analysis() that accepts sources parameter.
        """
        license_gate.gate("std.trendscope.advanced")
        if sources:
            await self.refresh_trends(sources=sources)
        return await self.run_autonomous_analysis()

    async def get_trending(
        self,
        category: Optional[str] = None,
        min_score: float = 0,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Get trending topics - MCP interface alias.

        Alias for get_trends() for MCP compatibility.
        """
        return await self.get_trends(
            category=category,
            min_score=min_score,
            limit=limit,
        )

    async def identify_niches(
        self,
        min_opportunity_score: float = 50,
    ) -> List[Dict[str, Any]]:
        """
        Identify niche opportunities - MCP interface alias.

        Alias for find_opportunities() for MCP compatibility.
        """
        license_gate.gate("std.trendscope.advanced")
        return await self.find_opportunities(
            min_score=min_opportunity_score,
            limit=20,
        )

    async def get_correlations(
        self,
        trend_id: Optional[str] = None,
        min_correlation: float = 0.3,
    ) -> List[Dict[str, Any]]:
        """
        Get trend correlations - MCP interface alias.

        Alias for find_correlations() for MCP compatibility.
        If trend_id is provided, filters results to that trend.
        """
        correlations = await self.find_correlations(min_correlation=min_correlation)

        if trend_id:
            # Filter to correlations involving this trend
            correlations = [
                c for c in correlations
                if c.get("trend_a_id") == trend_id or c.get("trend_b_id") == trend_id
            ]

        return correlations
