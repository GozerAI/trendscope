"""Tests for #370 — Limited free tier with premium preview."""

import pytest

from trendscope.revenue.free_tier import (
    FreeTierManager,
    UsageCounter,
    FREE_TIER_LIMITS,
    PREMIUM_FEATURES,
)


class TestFreeTierManager:

    def test_check_limit_allowed(self):
        ftm = FreeTierManager()
        result = ftm.check_limit("u1", "view_trend")
        assert result["allowed"] is True
        assert result["remaining"] == FREE_TIER_LIMITS["trends_per_day"]

    def test_check_limit_unknown_feature(self):
        ftm = FreeTierManager()
        result = ftm.check_limit("u1", "unknown_feature")
        assert result["allowed"] is True

    def test_check_limit_premium_only(self):
        ftm = FreeTierManager()
        result = ftm.check_limit("u1", "api_call")
        assert result["allowed"] is False
        assert result["reason"] == "premium_only"
        assert "upsell" in result

    def test_record_usage_and_limit(self):
        ftm = FreeTierManager()
        for _ in range(10):
            ftm.record_usage("u1", "view_trend")
        result = ftm.check_limit("u1", "view_trend")
        assert result["allowed"] is False
        assert result["reason"] == "limit_reached"
        assert "upsell" in result

    def test_approaching_limit_warning(self):
        ftm = FreeTierManager()
        for _ in range(8):  # 80% of 10
            ftm.record_usage("u1", "view_trend")
        result = ftm.check_limit("u1", "view_trend")
        assert result["allowed"] is True
        assert "warning" in result

    def test_forecast_limit(self):
        ftm = FreeTierManager()
        for _ in range(2):
            ftm.record_usage("u1", "generate_forecast")
        result = ftm.check_limit("u1", "generate_forecast")
        assert result["allowed"] is False

    def test_export_limit(self):
        ftm = FreeTierManager()
        ftm.record_usage("u1", "export_data")
        result = ftm.check_limit("u1", "export_data")
        assert result["allowed"] is False

    def test_separate_users(self):
        ftm = FreeTierManager()
        for _ in range(10):
            ftm.record_usage("u1", "view_trend")
        result = ftm.check_limit("u2", "view_trend")
        assert result["allowed"] is True

    def test_usage_summary(self):
        ftm = FreeTierManager()
        ftm.record_usage("u1", "view_trend")
        ftm.record_usage("u1", "view_trend")
        summary = ftm.get_usage_summary("u1")
        assert summary["user_id"] == "u1"
        assert summary["limits"]["trends_per_day"]["current"] == 2
        assert summary["limits"]["trends_per_day"]["remaining"] == 8
        assert summary["premium_features"] == PREMIUM_FEATURES

    def test_usage_summary_pct_used(self):
        ftm = FreeTierManager()
        for _ in range(5):
            ftm.record_usage("u1", "view_trend")
        summary = ftm.get_usage_summary("u1")
        assert summary["limits"]["trends_per_day"]["pct_used"] == 0.5

    def test_usage_summary_premium_only_pct(self):
        ftm = FreeTierManager()
        summary = ftm.get_usage_summary("u1")
        # api_calls_per_day has limit 0, so pct_used = 1.0
        assert summary["limits"]["api_calls_per_day"]["pct_used"] == 1.0

    def test_upgrade_prompt_no_bottlenecks(self):
        ftm = FreeTierManager()
        result = ftm.get_upgrade_prompt("u1")
        assert result["show_prompt"] is False

    def test_upgrade_prompt_with_bottlenecks(self):
        ftm = FreeTierManager()
        for _ in range(6):
            ftm.record_usage("u1", "view_trend")
        result = ftm.get_upgrade_prompt("u1")
        assert result["show_prompt"] is True
        assert "trends_per_day" in result["bottlenecks"]

    def test_custom_limits(self):
        custom = {"trends_per_day": 5, "forecasts_per_day": 1, "exports_per_day": 0,
                  "alerts": 1, "history_days": 3, "categories": 1, "api_calls_per_day": 0}
        ftm = FreeTierManager(limits=custom)
        for _ in range(5):
            ftm.record_usage("u1", "view_trend")
        result = ftm.check_limit("u1", "view_trend")
        assert result["allowed"] is False

    def test_usage_counter_reset(self):
        counter = UsageCounter(user_id="u1")
        counter.trends_viewed = 10
        # Force a reset by setting last_reset to > 24h ago
        counter.last_reset = counter.last_reset - 100000
        counter.reset_if_new_day()
        assert counter.trends_viewed == 0

    def test_usage_counter_no_reset_same_day(self):
        counter = UsageCounter(user_id="u1")
        counter.trends_viewed = 5
        counter.reset_if_new_day()
        assert counter.trends_viewed == 5
