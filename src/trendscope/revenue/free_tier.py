"""
#372 -- Limited free tier with premium preview.

Defines the free tier feature set with hard limits and premium teasers.
Tracks usage against limits and generates upgrade prompts at limit boundaries.
"""

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


FREE_TIER_LIMITS = {
    "trends_per_day": 10,
    "forecasts_per_day": 2,
    "exports_per_day": 1,
    "alerts": 2,
    "history_days": 7,
    "categories": 3,
    "api_calls_per_day": 0,
}

PREMIUM_FEATURES = [
    "unlimited_trends", "unlimited_forecasts", "full_history",
    "api_access", "json_export", "competitive_intelligence",
    "custom_alerts", "velocity_data", "momentum_data",
]


@dataclass
class UsageCounter:
    """Tracks daily usage for a free-tier user."""
    user_id: str = ""
    trends_viewed: int = 0
    forecasts_generated: int = 0
    exports_made: int = 0
    alerts_created: int = 0
    last_reset: float = field(default_factory=time.time)

    def reset_if_new_day(self) -> None:
        now = time.time()
        if now - self.last_reset > 86400:
            self.trends_viewed = 0
            self.forecasts_generated = 0
            self.exports_made = 0
            self.last_reset = now


class FreeTierManager:
    """Manages free tier limits and premium preview upsells."""

    def __init__(self, limits: Optional[Dict[str, int]] = None):
        self._limits = limits or dict(FREE_TIER_LIMITS)
        self._usage: Dict[str, UsageCounter] = {}

    def check_limit(self, user_id: str, feature: str) -> Dict[str, Any]:
        """Check if user can use a feature. Returns access status + optional upsell."""
        counter = self._get_counter(user_id)
        counter.reset_if_new_day()

        limit_key = self._feature_to_limit(feature)
        if limit_key is None:
            return {"allowed": True, "feature": feature}

        limit_val = self._limits.get(limit_key, 0)
        current = self._get_current_usage(counter, limit_key)

        if limit_val == 0:
            return {
                "allowed": False,
                "feature": feature,
                "reason": "premium_only",
                "upsell": {
                    "message": feature + " is a premium feature. Upgrade to unlock.",
                    "action": "upgrade_to_pro",
                    "target_url": "/pricing?ref=free_gate_" + feature,
                },
            }

        if current >= limit_val:
            return {
                "allowed": False,
                "feature": feature,
                "reason": "limit_reached",
                "current": current,
                "limit": limit_val,
                "upsell": {
                    "message": "Daily limit reached for " + feature + ". Upgrade for unlimited access.",
                    "action": "upgrade_to_pro",
                    "target_url": "/pricing?ref=free_limit_" + feature,
                },
            }

        result: Dict[str, Any] = {
            "allowed": True,
            "feature": feature,
            "current": current,
            "limit": limit_val,
            "remaining": limit_val - current,
        }
        if current >= limit_val * 0.8:
            result["warning"] = "Approaching daily limit for " + feature + "."
        return result

    def record_usage(self, user_id: str, feature: str) -> None:
        """Record that a user consumed a unit of a feature."""
        counter = self._get_counter(user_id)
        counter.reset_if_new_day()
        limit_key = self._feature_to_limit(feature)
        if limit_key == "trends_per_day":
            counter.trends_viewed += 1
        elif limit_key == "forecasts_per_day":
            counter.forecasts_generated += 1
        elif limit_key == "exports_per_day":
            counter.exports_made += 1

    def get_usage_summary(self, user_id: str) -> Dict[str, Any]:
        """Get usage summary for a user."""
        counter = self._get_counter(user_id)
        counter.reset_if_new_day()
        summary = {}
        for limit_key, limit_val in self._limits.items():
            current = self._get_current_usage(counter, limit_key)
            summary[limit_key] = {
                "current": current,
                "limit": limit_val,
                "remaining": max(0, limit_val - current),
                "pct_used": current / limit_val if limit_val > 0 else 1.0,
            }
        return {"user_id": user_id, "limits": summary, "premium_features": PREMIUM_FEATURES}

    def get_upgrade_prompt(self, user_id: str) -> Dict[str, Any]:
        """Generate a contextual upgrade prompt based on usage patterns."""
        counter = self._get_counter(user_id)
        counter.reset_if_new_day()
        bottlenecks = []
        for limit_key, limit_val in self._limits.items():
            if limit_val == 0:
                continue
            current = self._get_current_usage(counter, limit_key)
            if current >= limit_val * 0.5:
                bottlenecks.append(limit_key)
        if not bottlenecks:
            return {"show_prompt": False}
        return {
            "show_prompt": True,
            "bottlenecks": bottlenecks,
            "message": "You are actively using features near their limits. Upgrade to Pro for unlimited access.",
            "action": "upgrade_to_pro",
            "target_url": "/pricing?ref=usage_prompt",
        }

    def _get_counter(self, user_id: str) -> UsageCounter:
        if user_id not in self._usage:
            self._usage[user_id] = UsageCounter(user_id=user_id)
        return self._usage[user_id]

    def _feature_to_limit(self, feature: str) -> Optional[str]:
        mapping = {
            "view_trend": "trends_per_day",
            "generate_forecast": "forecasts_per_day",
            "export_data": "exports_per_day",
            "create_alert": "alerts",
            "api_call": "api_calls_per_day",
        }
        return mapping.get(feature)

    def _get_current_usage(self, counter: UsageCounter, limit_key: str) -> int:
        mapping = {
            "trends_per_day": counter.trends_viewed,
            "forecasts_per_day": counter.forecasts_generated,
            "exports_per_day": counter.exports_made,
            "alerts": counter.alerts_created,
            "api_calls_per_day": 0,
        }
        return mapping.get(limit_key, 0)
