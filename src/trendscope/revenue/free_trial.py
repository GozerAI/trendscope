"""
#366 -- Time-limited free trial with full access.

Manages time-limited trials giving users full premium access.
Handles trial creation, expiry, extension, and conversion tracking.
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DEFAULT_TRIAL_DAYS = 14
MAX_EXTENSION_DAYS = 7


class TrialStatus(Enum):
    ACTIVE = "active"
    EXPIRED = "expired"
    CONVERTED = "converted"
    CANCELLED = "cancelled"


@dataclass
class FreeTrial:
    """Represents a user free trial."""
    trial_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    user_id: str = ""
    started_at: float = field(default_factory=time.time)
    expires_at: float = 0.0
    status: TrialStatus = TrialStatus.ACTIVE
    converted_at: Optional[float] = None
    features_used: List[str] = field(default_factory=list)
    extension_days: int = 0

    def __post_init__(self):
        if self.expires_at == 0.0:
            self.expires_at = self.started_at + (DEFAULT_TRIAL_DAYS * 86400)

    @property
    def is_active(self) -> bool:
        return self.status == TrialStatus.ACTIVE and time.time() < self.expires_at

    @property
    def days_remaining(self) -> float:
        if not self.is_active:
            return 0.0
        return max(0.0, (self.expires_at - time.time()) / 86400)

    @property
    def days_elapsed(self) -> float:
        return (time.time() - self.started_at) / 86400


class FreeTrialManager:
    """Manages time-limited free trials with full premium access."""

    def __init__(self, trial_days: int = DEFAULT_TRIAL_DAYS):
        self._trial_days = trial_days
        self._trials: Dict[str, FreeTrial] = {}

    def start_trial(self, user_id: str) -> Dict[str, Any]:
        """Start a free trial for a user. Only one active trial allowed."""
        existing = self._get_user_trial(user_id)
        if existing and existing.is_active:
            return {
                "success": False,
                "error": "trial_already_active",
                "trial_id": existing.trial_id,
                "days_remaining": round(existing.days_remaining, 1),
            }
        if existing and existing.status in (TrialStatus.EXPIRED, TrialStatus.CONVERTED):
            return {
                "success": False,
                "error": "trial_already_used",
                "previous_status": existing.status.value,
            }
        trial = FreeTrial(
            user_id=user_id,
            expires_at=time.time() + (self._trial_days * 86400),
        )
        self._trials[trial.trial_id] = trial
        return {
            "success": True,
            "trial_id": trial.trial_id,
            "trial_days": self._trial_days,
            "expires_at": trial.expires_at,
            "features": self._get_trial_features(),
        }

    def check_access(self, user_id: str, feature: str = "") -> Dict[str, Any]:
        """Check if user has trial access to a feature."""
        trial = self._get_user_trial(user_id)
        if not trial:
            return {"has_access": False, "reason": "no_trial"}
        if not trial.is_active:
            self._expire_if_needed(trial)
            return {
                "has_access": False,
                "reason": "trial_expired",
                "upsell": {
                    "message": "Your free trial has ended. Upgrade to keep full access.",
                    "action": "upgrade_to_pro",
                    "target_url": "/pricing?ref=trial_expired",
                },
            }
        if feature and feature not in trial.features_used:
            trial.features_used.append(feature)
        return {
            "has_access": True,
            "trial_id": trial.trial_id,
            "days_remaining": round(trial.days_remaining, 1),
            "features_used": len(trial.features_used),
        }

    def extend_trial(self, user_id: str, extra_days: int) -> Dict[str, Any]:
        """Extend an active trial by up to MAX_EXTENSION_DAYS."""
        trial = self._get_user_trial(user_id)
        if not trial or not trial.is_active:
            return {"success": False, "error": "no_active_trial"}
        extra_days = min(extra_days, MAX_EXTENSION_DAYS - trial.extension_days)
        if extra_days <= 0:
            return {"success": False, "error": "max_extension_reached"}
        trial.expires_at += extra_days * 86400
        trial.extension_days += extra_days
        return {
            "success": True,
            "extra_days": extra_days,
            "new_expiry": trial.expires_at,
            "total_extension": trial.extension_days,
        }

    def convert_trial(self, user_id: str) -> Dict[str, Any]:
        """Mark trial as converted (user upgraded)."""
        trial = self._get_user_trial(user_id)
        if not trial:
            return {"success": False, "error": "no_trial"}
        trial.status = TrialStatus.CONVERTED
        trial.converted_at = time.time()
        return {
            "success": True,
            "trial_id": trial.trial_id,
            "days_used": round(trial.days_elapsed, 1),
            "features_used": len(trial.features_used),
        }

    def get_trial_status(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get current trial status for a user."""
        trial = self._get_user_trial(user_id)
        if not trial:
            return None
        self._expire_if_needed(trial)
        return {
            "trial_id": trial.trial_id,
            "status": trial.status.value,
            "days_remaining": round(trial.days_remaining, 1),
            "days_elapsed": round(trial.days_elapsed, 1),
            "features_used": trial.features_used,
            "extension_days": trial.extension_days,
        }

    def get_conversion_stats(self) -> Dict[str, Any]:
        """Get aggregate trial conversion statistics."""
        total = len(self._trials)
        active = sum(1 for t in self._trials.values() if t.is_active)
        converted = sum(1 for t in self._trials.values() if t.status == TrialStatus.CONVERTED)
        expired = sum(1 for t in self._trials.values() if t.status == TrialStatus.EXPIRED)
        return {
            "total_trials": total, "active": active,
            "converted": converted, "expired": expired,
            "conversion_rate": converted / total if total > 0 else 0.0,
        }

    def _get_trial_features(self) -> List[str]:
        return [
            "full_trend_data", "velocity_analysis", "momentum_tracking",
            "forecast_generation", "api_access", "json_export",
            "competitive_intelligence", "custom_alerts",
        ]

    def _get_user_trial(self, user_id: str) -> Optional[FreeTrial]:
        for trial in self._trials.values():
            if trial.user_id == user_id:
                return trial
        return None

    def _expire_if_needed(self, trial: FreeTrial) -> None:
        if trial.status == TrialStatus.ACTIVE and time.time() >= trial.expires_at:
            trial.status = TrialStatus.EXPIRED
