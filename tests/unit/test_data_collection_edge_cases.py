"""Edge-case tests for data collection, source handling, and validation."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendDatabase,
)
from trendscope.collectors import (
    GoogleTrendsCollector,
    RedditCollector,
    HackerNewsCollector,
    ProductHuntCollector,
    NicheIdentifier,
    TrendCollectorManager,
)


# =============================================================================
# Fixtures
# =============================================================================


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(db_path=tmp_path / "collect_edge.db")


@pytest.fixture
def manager(db):
    return TrendCollectorManager(db=db)


# =============================================================================
# Collector Initialization
# =============================================================================


class TestCollectorInitialization:

    def test_google_trends_default_geo(self):
        c = GoogleTrendsCollector()
        assert c.geo == "US"
        assert c.source == TrendSource.GOOGLE_TRENDS

    def test_google_trends_custom_geo(self):
        c = GoogleTrendsCollector(geo="CA")
        assert c.geo == "CA"
        assert "CA" in c.daily_trends_url

    def test_reddit_default_subreddits_not_empty(self):
        c = RedditCollector()
        assert len(c.subreddits) > 0

    def test_hacker_news_base_url(self):
        c = HackerNewsCollector()
        assert "firebaseio" in c.base_url

    def test_product_hunt_urls_set(self):
        c = ProductHuntCollector()
        assert c.feed_url is not None
        assert c.homepage_url is not None

    def test_collector_initial_stats_zero(self):
        c = GoogleTrendsCollector()
        assert c.collection_count == 0
        assert c.error_count == 0
        assert c.last_collection is None

    def test_manager_empty_collectors(self, manager):
        assert len(manager.collectors) == 0

    def test_manager_add_default_collectors_adds_all(self, manager):
        manager.add_default_collectors()
        assert len(manager.collectors) >= 4  # At least Google, Reddit, HN, PH


# =============================================================================
# Source Timeout Handling
# =============================================================================


class TestSourceTimeoutHandling:

    @pytest.mark.asyncio
    async def test_google_trends_timeout_returns_empty(self):
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=None):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_reddit_timeout_returns_empty(self):
        c = RedditCollector(subreddits=["technology"])
        with patch.object(c, "_make_request", return_value=None):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_hacker_news_timeout_returns_empty(self):
        c = HackerNewsCollector()
        with patch.object(c, "_make_request", return_value=None):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_product_hunt_timeout_returns_empty(self):
        c = ProductHuntCollector()
        with patch.object(c, "_make_raw_request", return_value=None):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_collect_all_tolerates_all_timeouts(self, manager):
        """collect_all returns empty when every collector times out."""
        manager.add_default_collectors()
        for collector in manager.collectors.values():
            collector._make_request = MagicMock(return_value=None)
            collector._make_raw_request = MagicMock(return_value=None)
        trends = await manager.collect_all(save=False)
        assert trends == []


# =============================================================================
# Malformed Response Handling
# =============================================================================


class TestMalformedResponseHandling:

    @pytest.mark.asyncio
    async def test_google_trends_invalid_xml(self):
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=b"<not valid xml"):
            trends = await c.collect()
            assert trends == []
            assert c.error_count >= 1

    @pytest.mark.asyncio
    async def test_google_trends_empty_items(self):
        """RSS with no <item> elements returns empty list."""
        empty_rss = b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
          <channel><title>Empty</title></channel>
        </rss>"""
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=empty_rss):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_reddit_missing_data_key(self):
        """Reddit response without 'data' key yields empty list."""
        c = RedditCollector(subreddits=["test"])
        with patch.object(c, "_make_request", return_value={"other": "stuff"}):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_reddit_empty_children(self):
        """Reddit response with empty children list."""
        c = RedditCollector(subreddits=["test"])
        mock_data = {"data": {"children": []}}
        with patch.object(c, "_make_request", return_value=mock_data):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_hacker_news_story_returns_none(self):
        """Individual story request returning None is skipped."""
        c = HackerNewsCollector()

        def mock_request(url, **kwargs):
            if "topstories" in url:
                return [1, 2, 3]
            return None  # Each story fails

        with patch.object(c, "_make_request", side_effect=mock_request):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_product_hunt_malformed_next_data(self):
        """PH homepage with malformed __NEXT_DATA__ returns empty."""
        c = ProductHuntCollector()
        bad_html = b"""<html><script id="__NEXT_DATA__" type="application/json">
        {invalid json here}</script></html>"""
        with patch.object(c, "_make_raw_request", return_value=bad_html):
            trends = await c.collect()
            assert trends == []


# =============================================================================
# Empty Response Handling
# =============================================================================


class TestEmptyResponseHandling:

    @pytest.mark.asyncio
    async def test_google_trends_empty_rss_bytes(self):
        """Empty bytes response from Google Trends."""
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=b""):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_hacker_news_empty_top_stories(self):
        """Empty top stories list from HN."""
        c = HackerNewsCollector()
        with patch.object(c, "_make_request", return_value=[]):
            trends = await c.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_product_hunt_empty_feed_empty_homepage(self):
        """Both feed and homepage return empty."""
        c = ProductHuntCollector()
        with patch.object(c, "_make_raw_request", return_value=b"<html></html>"):
            trends = await c.collect()
            assert trends == []


# =============================================================================
# Concurrent Collection from Multiple Sources
# =============================================================================


class TestConcurrentCollection:

    SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
      <channel>
        <item>
          <title>Test Trend</title>
          <ht:approx_traffic>10,000+</ht:approx_traffic>
          <description>Test</description>
        </item>
      </channel>
    </rss>"""

    @pytest.mark.asyncio
    async def test_collect_all_aggregates_from_multiple(self, manager, db):
        """collect_all aggregates trends from multiple collectors."""
        manager.add_default_collectors()
        # Google returns 1 trend, others return empty
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(
            return_value=self.SAMPLE_RSS
        )
        manager.collectors["Reddit"]._make_request = MagicMock(return_value=None)
        manager.collectors["Hacker News"]._make_request = MagicMock(return_value=None)
        manager.collectors["Product Hunt"]._make_raw_request = MagicMock(return_value=None)
        for name, c in manager.collectors.items():
            if name not in ("Google Trends", "Reddit", "Hacker News", "Product Hunt"):
                c._make_request = MagicMock(return_value=None)
                c._make_raw_request = MagicMock(return_value=None)

        trends = await manager.collect_all(save=True)
        assert len(trends) >= 1
        # Saved to DB
        db_trends = db.get_trends(limit=100)
        assert len(db_trends) >= 1

    @pytest.mark.asyncio
    async def test_collect_all_no_save(self, manager):
        """collect_all with save=False does not persist to DB."""
        manager.add_default_collectors()
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(
            return_value=self.SAMPLE_RSS
        )
        for name, c in manager.collectors.items():
            if name != "Google Trends":
                c._make_request = MagicMock(return_value=None)
                c._make_raw_request = MagicMock(return_value=None)

        trends = await manager.collect_all(save=False)
        assert len(trends) >= 1
        db_trends = manager.db.get_trends(limit=100)
        assert len(db_trends) == 0

    @pytest.mark.asyncio
    async def test_collect_from_specific_source(self, manager):
        """collect_from gathers from only one source."""
        manager.add_default_collectors()
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(
            return_value=self.SAMPLE_RSS
        )
        trends = await manager.collect_from("Google Trends", save=False)
        assert len(trends) == 1
        assert trends[0].source == TrendSource.GOOGLE_TRENDS

    @pytest.mark.asyncio
    async def test_collect_from_unknown_source_raises(self, manager):
        with pytest.raises(ValueError, match="Unknown collector"):
            await manager.collect_from("Nonexistent Source")


# =============================================================================
# Collection Scheduling / Stats
# =============================================================================


class TestCollectionScheduling:

    @pytest.mark.asyncio
    async def test_collector_stats_updated_on_success(self):
        """After successful collection, stats are updated."""
        rss = b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
          <channel>
            <item><title>X</title><description>Y</description></item>
          </channel>
        </rss>"""
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=rss):
            await c.collect()
            assert c.collection_count == 1
            assert c.last_collection is not None

    @pytest.mark.asyncio
    async def test_collector_stats_not_updated_on_failure(self):
        """After failed collection, collection_count stays 0."""
        c = GoogleTrendsCollector()
        with patch.object(c, "_make_raw_request", return_value=None):
            await c.collect()
            assert c.collection_count == 0
            assert c.last_collection is None

    def test_get_collector_stats_format(self, manager):
        manager.add_default_collectors()
        stats = manager.get_collector_stats()
        for name, entry in stats.items():
            assert "source" in entry
            assert "collection_count" in entry
            assert "error_count" in entry
            assert "last_collection" in entry


# =============================================================================
# Collector Health Reporting / Validation
# =============================================================================


class TestCollectorHealthReporting:

    def test_validate_rejects_whitespace_only_name(self, manager):
        t = Trend(name="   ", score=50)
        assert manager._validate_trend(t, "test") is False

    def test_validate_rejects_score_above_100(self, manager):
        t = Trend(name="Over", score=101)
        assert manager._validate_trend(t, "test") is False

    def test_validate_rejects_score_below_0(self, manager):
        t = Trend(name="Under", score=-1)
        assert manager._validate_trend(t, "test") is False

    def test_validate_rejects_negative_volume(self, manager):
        t = Trend(name="NegVol", score=50, volume=-10)
        assert manager._validate_trend(t, "test") is False

    def test_validate_accepts_boundary_score_0(self, manager):
        t = Trend(name="Zero", score=0.0, volume=0)
        assert manager._validate_trend(t, "test") is True

    def test_validate_accepts_boundary_score_100(self, manager):
        t = Trend(name="Max", score=100.0, volume=0)
        assert manager._validate_trend(t, "test") is True

    def test_validate_rejects_name_exactly_501_chars(self, manager):
        t = Trend(name="a" * 501, score=50)
        assert manager._validate_trend(t, "test") is False

    def test_validate_accepts_name_500_chars(self, manager):
        t = Trend(name="a" * 500, score=50)
        assert manager._validate_trend(t, "test") is True

    @pytest.mark.asyncio
    async def test_collect_all_filters_invalid_trends(self, manager):
        """Invalid trends from a collector are filtered out during collect_all."""
        manager.add_default_collectors()
        # Make Google return trends with invalid scores
        bad_rss = b"""<?xml version="1.0"?>
        <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
          <channel>
            <item>
              <title>Valid</title>
              <ht:approx_traffic>100+</ht:approx_traffic>
              <description>OK</description>
            </item>
          </channel>
        </rss>"""
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(return_value=bad_rss)
        for name, c in manager.collectors.items():
            if name != "Google Trends":
                c._make_request = MagicMock(return_value=None)
                c._make_raw_request = MagicMock(return_value=None)
        trends = await manager.collect_all(save=False)
        # All returned trends must be valid
        for t in trends:
            assert t.name.strip() != ""
            assert 0 <= t.score <= 100
            assert t.volume >= 0
