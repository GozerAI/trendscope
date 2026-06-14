"""Offline operation support for Trendscope.

Enables trend analysis, data collection queuing, forecast generation,
and data source auto-maintenance when network connectivity is unavailable.
"""

from trendscope.offline.cache import OfflineTrendCache, CachedTrendData
from trendscope.offline.analysis import OfflineTrendAnalyzer, OfflineAnalysisResult, OfflineCorrelation
from trendscope.offline.queue import OfflineCollectionQueue, QueuedRequest, QueueStatus
from trendscope.offline.forecast import OfflineForecastGenerator, OfflineForecast
from trendscope.offline.source_maintenance import (
    SourceMaintenanceManager,
    SourceConfig,
    SourceStatus,
)

__all__ = [
    "OfflineTrendCache",
    "CachedTrendData",
    "OfflineTrendAnalyzer",
    "OfflineAnalysisResult",
    "OfflineCorrelation",
    "OfflineCollectionQueue",
    "QueuedRequest",
    "QueueStatus",
    "OfflineForecastGenerator",
    "OfflineForecast",
    "SourceMaintenanceManager",
    "SourceConfig",
    "SourceStatus",
]
