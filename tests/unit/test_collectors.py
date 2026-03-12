"""Unit tests for Trendscope collectors module."""

import pytest
from unittest.mock import patch, MagicMock
from trendscope.core import Trend, TrendCategory, TrendSource, TrendDatabase, NicheOpportunity
from trendscope.collectors import (
    GoogleTrendsCollector,
    RedditCollector,
    HackerNewsCollector,
    ProductHuntCollector,
    NicheIdentifier,
    TrendCollectorManager,
)


# =============================================================================
# GoogleTrendsCollector
# =============================================================================


class TestGoogleTrendsCollector:

    SAMPLE_RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:ht="https://trends.google.com/trending/rss">
      <channel>
        <title>Trending Searches</title>
        <item>
          <title>AI Agents</title>
          <ht:approx_traffic>500,000+</ht:approx_traffic>
          <description>Trending topic about AI agents</description>
        </item>
        <item>
          <title>Sustainable Fashion</title>
          <ht:approx_traffic>100,000+</ht:approx_traffic>
          <description>Eco-friendly clothing trends</description>
        </item>
        <item>
          <title>Home Fitness</title>
          <ht:approx_traffic>50,000+</ht:approx_traffic>
          <description>Working out at home</description>
        </item>
      </channel>
    </rss>"""

    @pytest.fixture
    def collector(self):
        return GoogleTrendsCollector()

    def test_init(self, collector):
        assert collector.name == "Google Trends"
        assert collector.source == TrendSource.GOOGLE_TRENDS
        assert collector.collection_count == 0

    @pytest.mark.asyncio
    async def test_collect_returns_trends(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_RSS):
            trends = await collector.collect()
            assert len(trends) == 3
            assert all(isinstance(t, Trend) for t in trends)

    @pytest.mark.asyncio
    async def test_collect_updates_stats(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_RSS):
            await collector.collect()
            assert collector.collection_count == 1
            assert collector.last_collection is not None

    @pytest.mark.asyncio
    async def test_collect_sets_source(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_RSS):
            trends = await collector.collect()
            assert all(t.source == TrendSource.GOOGLE_TRENDS for t in trends)

    @pytest.mark.asyncio
    async def test_collect_parses_traffic_volume(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_RSS):
            trends = await collector.collect()
            # 500,000+ should give highest score
            assert trends[0].name == "AI Agents"
            assert trends[0].volume == 500000
            assert trends[0].score > trends[2].score

    @pytest.mark.asyncio
    async def test_collect_handles_network_failure(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=None):
            trends = await collector.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_collect_handles_malformed_xml(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=b"not xml at all"):
            trends = await collector.collect()
            assert trends == []

    def test_guess_category(self, collector):
        assert collector._guess_category("AI breakthrough") == TrendCategory.TECHNOLOGY
        assert collector._guess_category("stock market crash") == TrendCategory.BUSINESS
        assert collector._guess_category("fitness workout tips") == TrendCategory.HEALTH
        assert collector._guess_category("random thing") == TrendCategory.EMERGING


# =============================================================================
# RedditCollector
# =============================================================================


class TestRedditCollector:

    @pytest.fixture
    def collector(self):
        return RedditCollector(subreddits=["technology", "startups"])

    def test_init_default_subreddits(self):
        c = RedditCollector()
        assert "technology" in c.subreddits
        assert len(c.subreddits) == 7

    def test_init_custom_subreddits(self, collector):
        assert collector.subreddits == ["technology", "startups"]

    def test_categorize_subreddit(self, collector):
        assert collector._categorize_subreddit("technology") == TrendCategory.TECHNOLOGY
        assert collector._categorize_subreddit("startups") == TrendCategory.BUSINESS
        assert collector._categorize_subreddit("ecommerce") == TrendCategory.ECOMMERCE
        assert collector._categorize_subreddit("unknown") == TrendCategory.EMERGING

    def test_extract_keywords(self, collector):
        keywords = collector._extract_keywords("Python and Machine Learning for Data Science")
        assert "python" in keywords
        assert "machine" in keywords
        assert "learning" in keywords
        # Short words filtered out
        assert "and" not in keywords
        assert "for" not in keywords

    def test_extract_keywords_stopwords(self, collector):
        keywords = collector._extract_keywords("This is from that with been they were have")
        assert len(keywords) == 0

    @pytest.mark.asyncio
    async def test_collect_with_mocked_request(self, collector):
        mock_data = {
            "data": {
                "children": [
                    {
                        "data": {
                            "title": "AI breakthrough in coding",
                            "selftext": "Amazing new tool",
                            "score": 5000,
                            "num_comments": 200,
                            "stickied": False,
                            "url": "https://example.com",
                            "author": "user1",
                            "upvote_ratio": 0.95,
                        }
                    },
                    {
                        "data": {
                            "title": "Stickied post",
                            "stickied": True,
                            "score": 100,
                        }
                    },
                ]
            }
        }
        with patch.object(collector, "_make_request", return_value=mock_data):
            trends = await collector.collect()
            # Stickied posts are filtered out
            assert len(trends) >= 1
            assert trends[0].source == TrendSource.REDDIT

    @pytest.mark.asyncio
    async def test_collect_handles_failed_request(self, collector):
        with patch.object(collector, "_make_request", return_value=None):
            trends = await collector.collect()
            assert trends == []


# =============================================================================
# HackerNewsCollector
# =============================================================================


class TestHackerNewsCollector:

    @pytest.fixture
    def collector(self):
        return HackerNewsCollector()

    def test_init(self, collector):
        assert collector.name == "Hacker News"
        assert collector.source == TrendSource.HACKER_NEWS

    def test_extract_keywords(self, collector):
        keywords = collector._extract_keywords("Show HN: Python Framework for Machine Learning")
        assert "python" in keywords
        assert "machine" in keywords

    @pytest.mark.asyncio
    async def test_collect_with_mocked_api(self, collector):
        story_data = {
            "title": "Rust is the future",
            "score": 500,
            "descendants": 150,
            "url": "https://example.com",
            "by": "hacker",
            "type": "story",
        }

        def mock_request(url, **kwargs):
            if "topstories" in url:
                return [1, 2]
            return story_data

        with patch.object(collector, "_make_request", side_effect=mock_request):
            trends = await collector.collect()
            assert len(trends) == 2
            assert all(t.category == TrendCategory.TECHNOLOGY for t in trends)

    @pytest.mark.asyncio
    async def test_collect_empty_when_api_fails(self, collector):
        with patch.object(collector, "_make_request", return_value=None):
            trends = await collector.collect()
            assert trends == []


# =============================================================================
# ProductHuntCollector
# =============================================================================


class TestProductHuntCollector:

    SAMPLE_FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
    <feed xmlns="http://www.w3.org/2005/Atom">
      <title>Product Hunt</title>
      <entry>
        <title>AI Writing Assistant</title>
        <summary>Write better content with AI-powered suggestions</summary>
      </entry>
      <entry>
        <title>E-commerce Analytics</title>
        <summary>Understand your online sales data</summary>
      </entry>
      <entry>
        <title>Remote Team Tools</title>
        <summary>Collaborate with distributed teams</summary>
      </entry>
    </feed>"""

    @pytest.fixture
    def collector(self):
        return ProductHuntCollector()

    def test_init(self, collector):
        assert collector.name == "Product Hunt"
        assert collector.source == TrendSource.PRODUCT_HUNT

    @pytest.mark.asyncio
    async def test_collect_from_feed(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_FEED):
            trends = await collector.collect()
            assert len(trends) == 3
            assert all(isinstance(t, Trend) for t in trends)
            assert trends[0].name == "AI Writing Assistant"

    @pytest.mark.asyncio
    async def test_collect_score_capped_at_100(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_FEED):
            trends = await collector.collect()
            for t in trends:
                assert t.score <= 100

    @pytest.mark.asyncio
    async def test_collect_feed_score_decreases_by_position(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=self.SAMPLE_FEED):
            trends = await collector.collect()
            assert trends[0].score > trends[2].score

    @pytest.mark.asyncio
    async def test_collect_handles_network_failure(self, collector):
        with patch.object(collector, "_make_raw_request", return_value=None):
            trends = await collector.collect()
            assert trends == []

    @pytest.mark.asyncio
    async def test_collect_homepage_fallback(self, collector):
        """Falls back to homepage parsing when feed fails."""
        homepage_html = b"""<html><script id="__NEXT_DATA__" type="application/json">
        {"props":{"pageProps":{"posts":[
            {"name":"Cool App","tagline":"Do cool things","votesCount":200},
            {"name":"Dev Tool","tagline":"Build faster","votesCount":150}
        ]}}}</script></html>"""

        call_count = 0
        def mock_raw_request(url, **kwargs):
            nonlocal call_count
            call_count += 1
            if "feed" in url:
                return None  # Feed fails
            return homepage_html

        with patch.object(collector, "_make_raw_request", side_effect=mock_raw_request):
            trends = await collector.collect()
            assert len(trends) == 2
            assert trends[0].name == "Cool App"
            assert trends[0].volume == 200


# =============================================================================
# NicheIdentifier
# =============================================================================


class TestNicheIdentifier:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "niche.db")

    @pytest.fixture
    def identifier(self, db):
        return NicheIdentifier(db)

    def test_identify_niches_empty(self, identifier):
        niches = identifier.identify_niches([])
        assert niches == []

    def test_identify_niches_single_trend(self, identifier):
        trends = [Trend(name="Single", keywords=["ai"])]
        niches = identifier.identify_niches(trends)
        # Need at least 2 trends per keyword to form a niche
        assert niches == []

    def test_identify_niches_cluster(self, identifier):
        trends = [
            Trend(name="AI Tool 1", score=80, keywords=["ai", "tool"], velocity=0.5),
            Trend(name="AI Tool 2", score=70, keywords=["ai", "automation"], velocity=0.3),
            Trend(name="AI Tool 3", score=75, keywords=["ai", "ml"], velocity=0.4),
        ]
        niches = identifier.identify_niches(trends, min_confidence=0.3)
        assert len(niches) >= 1
        # "ai" keyword shared by all 3
        ai_niches = [n for n in niches if "ai" in n.name.lower()]
        assert len(ai_niches) >= 1

    def test_recommend_action_immediate(self, identifier):
        action = identifier._recommend_action(80, 0.5)
        assert "IMMEDIATE" in action

    def test_recommend_action_monitor(self, identifier):
        action = identifier._recommend_action(45, 0.1)
        assert "MONITOR" in action

    def test_calculate_urgency(self, identifier):
        assert identifier._calculate_urgency(0.6, 80) == "critical"
        assert identifier._calculate_urgency(0.4, 65) == "high"
        assert identifier._calculate_urgency(0.1, 45) == "medium"
        assert identifier._calculate_urgency(-0.1, 30) == "low"


# =============================================================================
# TrendCollectorManager
# =============================================================================


class TestTrendCollectorManager:

    @pytest.fixture
    def db(self, tmp_path):
        return TrendDatabase(db_path=tmp_path / "mgr.db")

    @pytest.fixture
    def manager(self, db):
        return TrendCollectorManager(db=db)

    def test_add_collector(self, manager):
        c = GoogleTrendsCollector()
        manager.add_collector(c)
        assert "Google Trends" in manager.collectors

    def test_add_default_collectors(self, manager):
        manager.add_default_collectors()
        assert len(manager.collectors) == 6

    @pytest.mark.asyncio
    async def test_collect_all(self, manager):
        manager.add_default_collectors()
        # Mock all network calls to avoid real HTTP
        for collector in manager.collectors.values():
            collector._make_request = MagicMock(return_value=None)
            collector._make_raw_request = MagicMock(return_value=None)
        # With no network, all collectors return empty
        trends = await manager.collect_all(save=True)
        assert isinstance(trends, list)

    @pytest.mark.asyncio
    async def test_collect_from_specific(self, manager):
        manager.add_default_collectors()
        rss = TestGoogleTrendsCollector.SAMPLE_RSS
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(return_value=rss)
        trends = await manager.collect_from("Google Trends")
        assert len(trends) == 3

    @pytest.mark.asyncio
    async def test_collect_from_unknown_raises(self, manager):
        with pytest.raises(ValueError, match="Unknown collector"):
            await manager.collect_from("NonExistent")

    def test_get_collector_stats(self, manager):
        manager.add_default_collectors()
        stats = manager.get_collector_stats()
        assert "Google Trends" in stats
        assert stats["Google Trends"]["collection_count"] == 0

    @pytest.mark.asyncio
    async def test_identify_niches_after_collection(self, manager):
        manager.add_default_collectors()
        rss = TestGoogleTrendsCollector.SAMPLE_RSS
        feed = TestProductHuntCollector.SAMPLE_FEED
        manager.collectors["Google Trends"]._make_raw_request = MagicMock(return_value=rss)
        manager.collectors["Product Hunt"]._make_raw_request = MagicMock(return_value=feed)
        manager.collectors["Reddit"]._make_request = MagicMock(return_value=None)
        manager.collectors["Hacker News"]._make_request = MagicMock(return_value=None)
        await manager.collect_all(save=True)
        niches = manager.identify_niches(min_confidence=0.3)
        assert isinstance(niches, list)

    def test_validate_trend_rejects_empty_name(self, manager):
        """Trends with empty names are rejected."""
        trend = Trend(name="", score=50.0)
        assert manager._validate_trend(trend, "test") is False

    def test_validate_trend_rejects_long_name(self, manager):
        """Trends with names over 500 chars are rejected."""
        trend = Trend(name="x" * 501, score=50.0)
        assert manager._validate_trend(trend, "test") is False

    def test_validate_trend_rejects_bad_score(self, manager):
        """Trends with score outside 0-100 are rejected."""
        trend = Trend(name="Valid", score=150.0)
        assert manager._validate_trend(trend, "test") is False
        trend2 = Trend(name="Valid", score=-5.0)
        assert manager._validate_trend(trend2, "test") is False

    def test_validate_trend_rejects_negative_volume(self, manager):
        """Trends with negative volume are rejected."""
        trend = Trend(name="Valid", score=50.0, volume=-1)
        assert manager._validate_trend(trend, "test") is False

    def test_validate_trend_accepts_valid(self, manager):
        """Valid trends pass validation."""
        trend = Trend(name="AI Tools", score=75.0, volume=1000)
        assert manager._validate_trend(trend, "test") is True
