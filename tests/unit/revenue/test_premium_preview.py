"""Tests for #297 — Premium insight preview for free users."""

import pytest
import time

from trendscope.revenue.premium_preview import (
    PremiumInsightPreview,
    PreviewImpression,
    FREE_DAILY_INSIGHT_LIMIT,
    PREVIEW_DETAIL_RATIO,
    _FREE_PREVIEW_FIELDS,
    _PREMIUM_FIELDS,
    _day_start,
)


def _make_trend(**overrides):
    base = {
        "id": "t1",
        "name": "AI Agents",
        "category": "technology",
        "status": "growing",
        "score": 85,
        "velocity": 0.72,
        "momentum": 0.55,
        "market_opportunity": 0.8,
        "competition_level": 0.4,
        "entry_barrier": 0.3,
        "keywords": ["ai", "agents", "automation", "llm"],
        "related_trends": ["chatbots", "rpa"],
        "history": [10, 25, 40, 60, 85],
    }
    base.update(overrides)
    return base


class TestPremiumInsightPreview:

    def test_generate_preview_includes_free_fields(self):
        pip = PremiumInsightPreview()
        trend = _make_trend()
        preview = pip.generate_preview(trend, "u1")
        assert preview["name"] == "AI Agents"
        assert preview["category"] == "technology"
        assert preview["status"] == "growing"

    def test_generate_preview_rounds_score(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(score=83), "u1")
        assert preview["score"] == 85  # rounded to nearest 5

    def test_generate_preview_rounds_score_low(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(score=22), "u1")
        assert preview["score"] == 20

    def test_premium_fields_are_redacted(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(), "u1")
        assert preview["is_preview"] is True
        assert preview["redacted_fields"] > 0
        # velocity should be redacted, not the raw number
        assert isinstance(preview["velocity"], dict)
        assert preview["velocity"]["unlock"] is True

    def test_redact_positive_number(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("velocity", 0.72)
        assert result["hint"] == "positive"
        assert result["unlock"] is True

    def test_redact_negative_number(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("momentum", -0.3)
        assert result["hint"] == "negative"

    def test_redact_zero(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("velocity", 0)
        assert result["hint"] == "neutral"

    def test_redact_list_shows_sample(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("keywords", ["ai", "agents", "automation", "llm"])
        assert "sample" in result
        assert "hidden_count" in result
        assert result["unlock"] is True
        assert len(result["sample"]) == 1  # 25% of 4 = 1

    def test_redact_string_truncates(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("history", "long_string_value_here")
        assert result["hint"].endswith("...")

    def test_redact_short_string_not_truncated(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("history", "short")
        assert result["hint"] == "short"

    def test_redact_other_type(self):
        pip = PremiumInsightPreview()
        result = pip._redact_value("something", {"nested": True})
        assert result == {"unlock": True}

    def test_upgrade_cta_high_score(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(score=90), "u1")
        assert "high-signal" in preview["upgrade_cta"]["message"]
        assert preview["upgrade_cta"]["action"] == "upgrade_to_pro"

    def test_upgrade_cta_medium_score(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(score=60), "u1")
        assert "gaining traction" in preview["upgrade_cta"]["message"]

    def test_upgrade_cta_low_score(self):
        pip = PremiumInsightPreview()
        preview = pip.generate_preview(_make_trend(score=30), "u1")
        assert "full insights" in preview["upgrade_cta"]["message"].lower()

    def test_impression_recorded(self):
        pip = PremiumInsightPreview()
        pip.generate_preview(_make_trend(), "u1")
        assert len(pip._impressions) == 1
        assert pip._impressions[0].user_id == "u1"

    def test_batch_preview(self):
        pip = PremiumInsightPreview()
        trends = [_make_trend(id=f"t{i}") for i in range(5)]
        result = pip.generate_batch_preview(trends, "u1")
        assert result["total"] == 5
        assert len(result["previews"]) == 5
        assert result["daily_limit"] == FREE_DAILY_INSIGHT_LIMIT

    def test_remaining_today_decreases(self):
        pip = PremiumInsightPreview(daily_limit=5)
        assert pip.get_remaining_today("u1") == 5
        pip.generate_preview(_make_trend(), "u1")
        assert pip.get_remaining_today("u1") == 4

    def test_conversion_click_recording(self):
        pip = PremiumInsightPreview()
        pip.record_conversion_click("u1")
        pip.record_conversion_click("u1")
        pip.record_conversion_click("u2")
        stats = pip.get_conversion_stats()
        assert stats["total_cta_clicks"] == 3
        assert stats["clicking_users"] == 2

    def test_conversion_stats_empty(self):
        pip = PremiumInsightPreview()
        stats = pip.get_conversion_stats()
        assert stats["total_impressions"] == 0
        assert stats["click_rate"] == 0.0

    def test_conversion_stats_with_impressions(self):
        pip = PremiumInsightPreview()
        pip.generate_preview(_make_trend(), "u1")
        pip.generate_preview(_make_trend(), "u2")
        pip.record_conversion_click("u1")
        stats = pip.get_conversion_stats()
        assert stats["unique_users"] == 2
        assert stats["total_cta_clicks"] == 1
        assert stats["click_rate"] == 0.5

    def test_day_start_returns_float(self):
        result = _day_start()
        assert isinstance(result, float)
        assert result <= time.time()

    def test_preview_impression_defaults(self):
        imp = PreviewImpression(user_id="u1", insight_id="i1")
        assert imp.converted is False
        assert imp.timestamp > 0

    def test_batch_preview_remaining_calculation(self):
        pip = PremiumInsightPreview(daily_limit=5)
        trends = [_make_trend(id=f"t{i}") for i in range(3)]
        result = pip.generate_batch_preview(trends, "u1")
        assert result["remaining_today"] == 2
