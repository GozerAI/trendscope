"""Autonomy package -- autonomous trend intelligence subsystems.

Re-exports AutonomyDashboard for backward compatibility with
``from trendscope.autonomy import AutonomyDashboard``.
"""

from trendscope.autonomy.dashboard import AutonomyDashboard
from trendscope.autonomy.source_discovery import SourceDiscoveryEngine
from trendscope.autonomy.quality_validator import QualityValidator
from trendscope.autonomy.accuracy_improver import AccuracyImprover
from trendscope.autonomy.anomaly_learner import AnomalyLearner
from trendscope.autonomy.schedule_optimizer import ScheduleOptimizer

__all__ = [
    "AutonomyDashboard",
    "SourceDiscoveryEngine",
    "QualityValidator",
    "AccuracyImprover",
    "AnomalyLearner",
    "ScheduleOptimizer",
]
