"""Tests for real-time intelligence feed."""

import pytest
import asyncio
from trendscope.feed import IntelligenceFeed


class TestIntelligenceFeed:
    @pytest.fixture
    def feed(self):
        return IntelligenceFeed(maxlen=500)

    def test_push_event(self, feed):
        event = feed.push_event("test.event", {"key": "value"})
        assert event["type"] == "test.event"
        assert event["data"]["key"] == "value"
        assert "id" in event
        assert "timestamp" in event

    def test_push_event_auto_id(self, feed):
        e1 = feed.push_event("a", {})
        e2 = feed.push_event("b", {})
        assert e1["id"] != e2["id"]

    def test_get_recent_empty(self, feed):
        result = feed.get_recent(minutes=5)
        assert result == []

    def test_get_recent_returns_recent_events(self, feed):
        feed.push_event("a", {"x": 1})
        feed.push_event("b", {"x": 2})
        result = feed.get_recent(minutes=5)
        assert len(result) == 2

    def test_get_all(self, feed):
        feed.push_event("a", {})
        feed.push_event("b", {})
        assert len(feed.get_all()) == 2

    def test_get_summary_empty(self, feed):
        summary = feed.get_summary(minutes=5)
        assert summary["total"] == 0
        assert summary["by_type"] == {}
        assert summary["window_minutes"] == 5

    def test_get_summary_with_events(self, feed):
        feed.push_event("anomaly", {"x": 1})
        feed.push_event("anomaly", {"x": 2})
        feed.push_event("refresh", {"x": 3})
        summary = feed.get_summary(minutes=5)
        assert summary["total"] == 3
        assert summary["by_type"]["anomaly"] == 2
        assert summary["by_type"]["refresh"] == 1

    def test_maxlen_overflow(self):
        feed = IntelligenceFeed(maxlen=5)
        for i in range(10):
            feed.push_event("test", {"i": i})
        assert len(feed.get_all()) == 5

    def test_maxlen_drops_oldest(self):
        feed = IntelligenceFeed(maxlen=3)
        feed.push_event("a", {"i": 0})
        feed.push_event("b", {"i": 1})
        feed.push_event("c", {"i": 2})
        feed.push_event("d", {"i": 3})
        events = feed.get_all()
        assert events[0]["data"]["i"] == 1
        assert events[-1]["data"]["i"] == 3

    def test_event_shape(self, feed):
        event = feed.push_event("test.type", {"key": "val"})
        assert set(event.keys()) == {"id", "type", "data", "timestamp"}

    def test_get_summary_custom_window(self, feed):
        feed.push_event("test", {})
        summary = feed.get_summary(minutes=60)
        assert summary["window_minutes"] == 60
        assert summary["total"] == 1

    @pytest.mark.asyncio
    async def test_stream_yields_new_events(self):
        feed = IntelligenceFeed(maxlen=100)
        feed.push_event("pre", {"x": 0})

        async def push_later():
            await asyncio.sleep(0.1)
            feed.push_event("new", {"x": 1})

        asyncio.create_task(push_later())

        count = 0
        async for data in feed.stream():
            count += 1
            assert "data:" in data
            if count >= 1:
                break
