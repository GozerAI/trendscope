"""Tests for trend lifecycle tracking."""

import pytest
from dataclasses import dataclass
from trendscope.core import Trend, TrendCategory, TrendDatabase
from trendscope.lifecycle import LifecycleStage, LifecycleTransition, LifecycleTracker


@dataclass
class FakeTrend:
    id: str = "t1"
    name: str = "Test"
    score: float = 50
    velocity: float = 0.0
    momentum: float = 0.0


class TestLifecycleStage:
    def test_all_stages_exist(self):
        assert len(LifecycleStage) == 7

    def test_stage_values(self):
        assert LifecycleStage.NASCENT.value == "nascent"
        assert LifecycleStage.DEAD.value == "dead"
        assert LifecycleStage.PEAK.value == "peak"


class TestLifecycleTransition:
    def test_transition_fields(self):
        t = LifecycleTransition(
            id="1", trend_id="t1", from_stage="nascent",
            to_stage="emerging", timestamp="2026-01-01T00:00:00Z", reason="test"
        )
        assert t.from_stage == "nascent"
        assert t.to_stage == "emerging"

    def test_transition_no_from(self):
        t = LifecycleTransition(
            id="1", trend_id="t1", from_stage=None,
            to_stage="nascent", timestamp="2026-01-01T00:00:00Z", reason="initial"
        )
        assert t.from_stage is None


class TestLifecycleTracker:
    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "test.db")

    @pytest.fixture
    def tracker(self, db):
        return LifecycleTracker(db)

    def test_classify_dead(self, tracker):
        trend = FakeTrend(score=5, velocity=-0.5)
        assert tracker.classify_stage(trend) == LifecycleStage.DEAD

    def test_classify_dormant(self, tracker):
        trend = FakeTrend(score=15, velocity=0.0)
        assert tracker.classify_stage(trend) == LifecycleStage.DORMANT

    def test_classify_declining(self, tracker):
        trend = FakeTrend(score=60, velocity=-0.3)
        assert tracker.classify_stage(trend) == LifecycleStage.DECLINING

    def test_classify_peak(self, tracker):
        trend = FakeTrend(score=85, velocity=0.05)
        assert tracker.classify_stage(trend) == LifecycleStage.PEAK

    def test_classify_growing(self, tracker):
        trend = FakeTrend(score=50, velocity=0.2)
        assert tracker.classify_stage(trend) == LifecycleStage.GROWING

    def test_classify_emerging(self, tracker):
        trend = FakeTrend(score=25, velocity=0.1)
        assert tracker.classify_stage(trend) == LifecycleStage.EMERGING

    def test_classify_nascent(self, tracker):
        # score=25 avoids dormant check (score<20), velocity=0.02 avoids dormant abs check
        trend = FakeTrend(score=25, velocity=0.02)
        assert tracker.classify_stage(trend) == LifecycleStage.NASCENT

    def test_classify_default_peak(self, tracker):
        trend = FakeTrend(score=75, velocity=0.0)
        assert tracker.classify_stage(trend) == LifecycleStage.PEAK

    def test_classify_default_growing(self, tracker):
        trend = FakeTrend(score=45, velocity=0.0)
        assert tracker.classify_stage(trend) == LifecycleStage.GROWING

    def test_classify_default_emerging(self, tracker):
        trend = FakeTrend(score=35, velocity=0.0)
        assert tracker.classify_stage(trend) == LifecycleStage.EMERGING

    def test_update_lifecycle_records_transition(self, db, tracker):
        trend = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        transition = tracker.update_lifecycle(trend.id, trend)
        assert transition is not None
        assert transition.to_stage == "peak"
        assert transition.from_stage is None

    def test_update_lifecycle_no_change(self, db, tracker):
        trend = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        tracker.update_lifecycle(trend.id, trend)
        # Second call with same stage should return None
        result = tracker.update_lifecycle(trend.id, trend)
        assert result is None

    def test_update_lifecycle_records_stage_change(self, db, tracker):
        trend = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        tracker.update_lifecycle(trend.id, trend)
        # Change to declining
        trend.score = 60
        trend.velocity = -0.3
        transition = tracker.update_lifecycle(trend.id, trend)
        assert transition is not None
        assert transition.from_stage == "peak"
        assert transition.to_stage == "declining"

    def test_update_lifecycle_unknown_trend(self, db, tracker):
        result = tracker.update_lifecycle("nonexistent")
        assert result is None

    def test_get_lifecycle_empty(self, db, tracker):
        result = tracker.get_lifecycle("nonexistent")
        assert result == []

    def test_get_lifecycle_with_history(self, db, tracker):
        trend = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        tracker.update_lifecycle(trend.id, trend)
        history = tracker.get_lifecycle(trend.id)
        assert len(history) == 1
        assert history[0]["to_stage"] == "peak"

    def test_get_stage_distribution(self, db, tracker):
        t1 = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        t2 = Trend(name="Crypto", score=5, velocity=-0.5, category=TrendCategory.FINANCE)
        db.save_trend(t1)
        db.save_trend(t2)
        dist = tracker.get_stage_distribution()
        assert "peak" in dist
        assert "dead" in dist

    def test_predict_time_to_peak_growing(self, db, tracker):
        trend = Trend(name="AI", score=50, velocity=0.3, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        result = tracker.predict_time_to_peak(trend.id)
        assert result is not None
        assert "estimated_days" in result
        assert result["estimated_days"] > 0

    def test_predict_time_to_peak_already_peaked(self, db, tracker):
        trend = Trend(name="AI", score=85, velocity=0.05, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        result = tracker.predict_time_to_peak(trend.id)
        assert result["prediction"] == "not_applicable"

    def test_predict_time_to_peak_declining(self, db, tracker):
        trend = Trend(name="AI", score=50, velocity=-0.3, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        result = tracker.predict_time_to_peak(trend.id)
        assert result["prediction"] == "not_applicable"

    def test_predict_time_to_peak_unknown(self, db, tracker):
        result = tracker.predict_time_to_peak("nonexistent")
        assert result is None

    def test_get_aging_trends_empty(self, db, tracker):
        result = tracker.get_aging_trends(min_days=7)
        assert result == []

    def test_get_aging_trends_recent_not_included(self, db, tracker):
        trend = Trend(name="AI", score=5, velocity=-0.5, category=TrendCategory.TECHNOLOGY)
        db.save_trend(trend)
        tracker.update_lifecycle(trend.id, trend)
        # Just entered declining, not aging yet
        result = tracker.get_aging_trends(min_days=7)
        assert len(result) == 0

    def test_classify_with_none_values(self, tracker):
        trend = FakeTrend(score=None, velocity=None)
        # Should not raise, returns nascent due to 0 score
        stage = tracker.classify_stage(trend)
        assert isinstance(stage, LifecycleStage)

    def test_classify_zero_velocity_moderate_score(self, tracker):
        trend = FakeTrend(score=55, velocity=0.0)
        stage = tracker.classify_stage(trend)
        assert stage in (LifecycleStage.GROWING, LifecycleStage.EMERGING)

    def test_stage_distribution_empty_db(self, db, tracker):
        dist = tracker.get_stage_distribution()
        assert isinstance(dist, dict)
        assert sum(dist.values()) == 0
