"""
Trendscope Revenue — Monetization, conversion, and engagement modules.

Provides premium previews, upsell flows, trial management, content pipelines,
and intelligence reports to drive revenue and user engagement.
"""

from trendscope.revenue.premium_preview import PremiumInsightPreview
from trendscope.revenue.free_trial import FreeTrialManager
from trendscope.revenue.free_tier import FreeTierManager

__all__ = [
    "PremiumInsightPreview",
    "FreeTrialManager",
    "FreeTierManager",
]
