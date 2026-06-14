"""Tests for free trial management (supporting #370)."""

import pytest
import time

from trendscope.revenue.free_trial import (
    FreeTrialManager,
    FreeTrial,
    TrialStatus,
    DEFAULT_TRIAL_DAYS,
    MAX_EXTENSION_DAYS,
)


class TestFreeTrialManager:

    def test_start_trial(self):
        ftm = FreeTrialManager()
        result = ftm.start_trial("u1")
        assert result["success"] is True
        assert "trial_id" in result
        assert result["trial_days"] == DEFAULT_TRIAL_DAYS

    def test_start_trial_duplicate_blocked(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        result = ftm.start_trial("u1")
        assert result["success"] is False
        assert result["error"] == "trial_already_active"

    def test_check_access_active(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        result = ftm.check_access("u1", "velocity_analysis")
        assert result["has_access"] is True
        assert result["days_remaining"] > 0

    def test_check_access_tracks_features(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        ftm.check_access("u1", "velocity_analysis")
        ftm.check_access("u1", "api_access")
        result = ftm.check_access("u1")
        assert result["features_used"] == 2

    def test_check_access_no_trial(self):
        ftm = FreeTrialManager()
        result = ftm.check_access("u1")
        assert result["has_access"] is False
        assert result["reason"] == "no_trial"

    def test_check_access_expired_trial(self):
        ftm = FreeTrialManager(trial_days=0)
        ftm.start_trial("u1")
        # Trial with 0 days expires immediately
        result = ftm.check_access("u1")
        assert result["has_access"] is False
        assert "upsell" in result

    def test_extend_trial(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        result = ftm.extend_trial("u1", 3)
        assert result["success"] is True
        assert result["extra_days"] == 3

    def test_extend_trial_capped(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        ftm.extend_trial("u1", 5)
        result = ftm.extend_trial("u1", 5)
        # MAX_EXTENSION_DAYS = 7, already used 5, so only 2 more
        assert result["success"] is True
        assert result["extra_days"] == 2

    def test_extend_trial_max_reached(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        ftm.extend_trial("u1", 7)
        result = ftm.extend_trial("u1", 1)
        assert result["success"] is False
        assert result["error"] == "max_extension_reached"

    def test_extend_trial_no_trial(self):
        ftm = FreeTrialManager()
        result = ftm.extend_trial("u1", 3)
        assert result["success"] is False

    def test_convert_trial(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        result = ftm.convert_trial("u1")
        assert result["success"] is True
        assert result["features_used"] >= 0

    def test_convert_trial_no_trial(self):
        ftm = FreeTrialManager()
        result = ftm.convert_trial("u1")
        assert result["success"] is False

    def test_converted_trial_cannot_restart(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        ftm.convert_trial("u1")
        result = ftm.start_trial("u1")
        assert result["success"] is False
        assert result["error"] == "trial_already_used"

    def test_get_trial_status(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        status = ftm.get_trial_status("u1")
        assert status is not None
        assert status["status"] == "active"
        assert status["days_remaining"] > 0

    def test_get_trial_status_no_trial(self):
        ftm = FreeTrialManager()
        assert ftm.get_trial_status("u1") is None

    def test_conversion_stats(self):
        ftm = FreeTrialManager()
        ftm.start_trial("u1")
        ftm.start_trial("u2")
        ftm.convert_trial("u1")
        stats = ftm.get_conversion_stats()
        assert stats["total_trials"] == 2
        assert stats["converted"] == 1
        assert stats["conversion_rate"] == 0.5

    def test_conversion_stats_empty(self):
        ftm = FreeTrialManager()
        stats = ftm.get_conversion_stats()
        assert stats["total_trials"] == 0
        assert stats["conversion_rate"] == 0.0

    def test_trial_features_list(self):
        ftm = FreeTrialManager()
        result = ftm.start_trial("u1")
        assert "features" in result
        assert "full_trend_data" in result["features"]
        assert "api_access" in result["features"]

    def test_free_trial_properties(self):
        trial = FreeTrial(user_id="u1")
        assert trial.is_active is True
        assert trial.days_remaining > 0
        assert trial.days_elapsed >= 0
