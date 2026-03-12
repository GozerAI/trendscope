"""
Trendscope - Market Trend Intelligence.

Provides market trend analysis, niche identification, and opportunity detection.
Integrates with external trend sources and provides autonomous monitoring capabilities.
"""

from trendscope.core import (
    TrendCategory,
    TrendSource,
    TrendStatus,
    Trend,
    TrendDatabase,
    TrendAnalyzer,
)
from trendscope.collectors import (
    TrendCollector,
    TrendCollectorManager,
    GoogleTrendsCollector,
    RedditCollector,
    HackerNewsCollector,
    ProductHuntCollector,
    NicheIdentifier,
)
from trendscope.intelligence import (
    TrendIntelligenceManager,
    TrendCorrelation,
    TrendDriftDetector,
    OpportunityScorer,
)
from trendscope.forecasting import TrendForecaster
from trendscope.credibility import SourceCredibilityScorer
from trendscope.alerts import AlertManager
from trendscope.collectors_competitive import GitHubTrendingCollector, PackageDownloadsCollector
from trendscope.narratives import NarrativeGenerator
from trendscope.service import TrendService

__all__ = [
    # Core
    "TrendCategory",
    "TrendSource",
    "TrendStatus",
    "Trend",
    "TrendDatabase",
    "TrendAnalyzer",
    # Collectors
    "TrendCollector",
    "TrendCollectorManager",
    "GoogleTrendsCollector",
    "RedditCollector",
    "HackerNewsCollector",
    "ProductHuntCollector",
    "NicheIdentifier",
    # Intelligence
    "TrendIntelligenceManager",
    "TrendCorrelation",
    "TrendDriftDetector",
    "OpportunityScorer",
    # Forecasting
    "TrendForecaster",
    # Credibility
    "SourceCredibilityScorer",
    # Alerts
    "AlertManager",
    # Competitive collectors
    "GitHubTrendingCollector",
    "PackageDownloadsCollector",
    # Narratives
    "NarrativeGenerator",
    # Service
    "TrendService",
]
