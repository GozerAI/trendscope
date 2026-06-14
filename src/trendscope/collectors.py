"""
Trend Collectors - Data collection from various sources.

Provides collectors for gathering trend data from external platforms
including Google Trends, Reddit, Hacker News, Product Hunt, and more.
"""

import asyncio
import json
import logging
import re
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from trendscope.core import (
    Trend,
    TrendCategory,
    TrendSource,
    TrendStatus,
    TrendDatabase,
    NicheOpportunity,
)

logger = logging.getLogger(__name__)


class TrendCollector(ABC):
    """Base class for trend collectors."""

    def __init__(self, name: str, source: TrendSource):
        self.name = name
        self.source = source
        self.last_collection: Optional[datetime] = None
        self.collection_count = 0
        self.error_count = 0

    @abstractmethod
    async def collect(self) -> List[Trend]:
        """Collect trends from the source."""
        pass

    def _make_request(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Optional[Dict[str, Any]]:
        """Make HTTP request and return JSON response."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Trendscope/1.0")
            if headers:
                for key, value in headers.items():
                    req.add_header(key, value)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP {e.code} for {url}: {e.reason}")
            self.error_count += 1
            return None
        except urllib.error.URLError as e:
            logger.error(f"Connection error for {url}: {e.reason}")
            self.error_count += 1
            return None
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            self.error_count += 1
            return None

    def _make_raw_request(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
    ) -> Optional[bytes]:
        """Make HTTP request and return raw bytes."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", "Trendscope/1.0")
            if headers:
                for key, value in headers.items():
                    req.add_header(key, value)

            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except urllib.error.HTTPError as e:
            logger.error(f"HTTP {e.code} for {url}: {e.reason}")
            self.error_count += 1
            return None
        except urllib.error.URLError as e:
            logger.error(f"Connection error for {url}: {e.reason}")
            self.error_count += 1
            return None
        except Exception as e:
            logger.error(f"Request failed for {url}: {e}")
            self.error_count += 1
            return None

    def _create_trend(
        self,
        name: str,
        description: str = "",
        score: float = 50.0,
        category: TrendCategory = TrendCategory.EMERGING,
        **kwargs,
    ) -> Trend:
        """Create a trend with common defaults."""
        return Trend(
            id=str(uuid4()),
            name=name,
            description=description,
            category=category,
            source=self.source,
            score=score,
            first_seen=datetime.now(timezone.utc),
            last_updated=datetime.now(timezone.utc),
            **kwargs,
        )


class GoogleTrendsCollector(TrendCollector):
    """Collector for Google Trends data via the public RSS feed."""

    def __init__(self, geo: str = "US"):
        super().__init__("Google Trends", TrendSource.GOOGLE_TRENDS)
        self.geo = geo
        self.daily_trends_url = f"https://trends.google.com/trending/rss?geo={geo}"

    async def collect(self) -> List[Trend]:
        """Collect trending searches from Google Trends RSS feed."""
        trends = []

        raw = self._make_raw_request(self.daily_trends_url)
        if not raw:
            return trends

        try:
            trends = self._parse_rss(raw)
        except Exception as e:
            logger.error(f"Failed to parse Google Trends RSS: {e}")
            self.error_count += 1
            return []

        self.last_collection = datetime.now(timezone.utc)
        self.collection_count += 1
        return trends

    def _parse_rss(self, raw: bytes) -> List[Trend]:
        """Parse Google Trends RSS XML into Trend objects."""
        trends = []
        root = ET.fromstring(raw)

        # Google Trends RSS uses the ht: namespace for traffic data
        ns = {"ht": "https://trends.google.com/trending/rss"}

        for item in root.iter("item"):
            title_el = item.find("title")
            if title_el is None or not title_el.text:
                continue

            name = title_el.text.strip()

            # Extract approximate traffic volume from ht:approx_traffic
            traffic_el = item.find("ht:approx_traffic", ns)
            volume = 0
            score = 50.0
            if traffic_el is not None and traffic_el.text:
                traffic_str = traffic_el.text.replace("+", "").replace(",", "")
                try:
                    volume = int(traffic_str)
                    # Scale: 10K → 50, 100K → 70, 500K+ → 90
                    score = min(100, 40 + (volume / 10000) * 3)
                except ValueError:
                    logger.debug(f"Could not parse traffic volume: {traffic_str!r}")

            desc_el = item.find("description")
            description = desc_el.text.strip() if desc_el is not None and desc_el.text else f"Trending on Google: {name}"

            category = self._guess_category(name)

            trend = self._create_trend(
                name=name,
                description=description,
                score=score,
                category=category,
                keywords=[w.lower() for w in name.split() if len(w) > 2],
                volume=volume,
                raw_data={"geo": self.geo, "source_url": self.daily_trends_url},
            )
            trends.append(trend)

        return trends

    def _guess_category(self, name: str) -> TrendCategory:
        """Guess trend category from the name."""
        name_lower = name.lower()
        tech_words = {"ai", "app", "software", "tech", "crypto", "bitcoin", "robot", "code", "gpu", "chip"}
        health_words = {"health", "fitness", "diet", "medical", "vaccine", "workout", "mental"}
        biz_words = {"stock", "market", "business", "economy", "company", "ceo", "ipo"}
        lifestyle_words = {"fashion", "travel", "food", "recipe", "home", "garden"}

        tokens = set(name_lower.split())
        if tokens & tech_words:
            return TrendCategory.TECHNOLOGY
        if tokens & health_words:
            return TrendCategory.HEALTH
        if tokens & biz_words:
            return TrendCategory.BUSINESS
        if tokens & lifestyle_words:
            return TrendCategory.LIFESTYLE
        return TrendCategory.EMERGING


class RedditCollector(TrendCollector):
    """Collector for Reddit trends."""

    def __init__(self, subreddits: Optional[List[str]] = None):
        super().__init__("Reddit", TrendSource.REDDIT)
        self.subreddits = subreddits or [
            "technology", "gadgets", "startups", "entrepreneur",
            "ecommerce", "dropship", "smallbusiness",
        ]
        self.base_url = "https://www.reddit.com"

    async def collect(self) -> List[Trend]:
        """Collect trends from Reddit."""
        trends = []

        for subreddit in self.subreddits:
            url = f"{self.base_url}/r/{subreddit}/hot.json?limit=10"
            data = self._make_request(url)

            if not data:
                continue

            posts = data.get("data", {}).get("children", [])
            for post in posts[:5]:
                post_data = post.get("data", {})
                if post_data.get("stickied"):
                    continue

                score = min(100, post_data.get("score", 0) / 100)
                trend = self._create_trend(
                    name=post_data.get("title", "")[:100],
                    description=post_data.get("selftext", "")[:500],
                    score=score,
                    category=self._categorize_subreddit(subreddit),
                    keywords=self._extract_keywords(post_data.get("title", "")),
                    volume=post_data.get("num_comments", 0),
                    raw_data={
                        "subreddit": subreddit,
                        "url": post_data.get("url"),
                        "author": post_data.get("author"),
                        "upvote_ratio": post_data.get("upvote_ratio"),
                    },
                )
                trends.append(trend)

        self.last_collection = datetime.now(timezone.utc)
        self.collection_count += 1
        return trends

    def _categorize_subreddit(self, subreddit: str) -> TrendCategory:
        """Map subreddit to trend category."""
        mapping = {
            "technology": TrendCategory.TECHNOLOGY,
            "gadgets": TrendCategory.TECHNOLOGY,
            "startups": TrendCategory.BUSINESS,
            "entrepreneur": TrendCategory.BUSINESS,
            "ecommerce": TrendCategory.ECOMMERCE,
            "dropship": TrendCategory.ECOMMERCE,
            "smallbusiness": TrendCategory.BUSINESS,
        }
        return mapping.get(subreddit.lower(), TrendCategory.EMERGING)

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from text."""
        # Simple keyword extraction
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        stopwords = {"this", "that", "with", "from", "have", "been", "were", "they"}
        return list(set(words) - stopwords)[:10]


class HackerNewsCollector(TrendCollector):
    """Collector for Hacker News trends."""

    def __init__(self):
        super().__init__("Hacker News", TrendSource.HACKER_NEWS)
        self.base_url = "https://hacker-news.firebaseio.com/v0"

    async def collect(self) -> List[Trend]:
        """Collect trends from Hacker News."""
        trends = []

        # Get top stories
        top_stories = self._make_request(f"{self.base_url}/topstories.json")
        if not top_stories:
            return trends

        for story_id in top_stories[:15]:
            story = self._make_request(f"{self.base_url}/item/{story_id}.json")
            if not story:
                continue

            score = min(100, story.get("score", 0) / 10)
            trend = self._create_trend(
                name=story.get("title", "")[:100],
                description=f"HN discussion with {story.get('descendants', 0)} comments",
                score=score,
                category=TrendCategory.TECHNOLOGY,
                keywords=self._extract_keywords(story.get("title", "")),
                volume=story.get("descendants", 0),
                raw_data={
                    "hn_id": story_id,
                    "url": story.get("url"),
                    "author": story.get("by"),
                    "type": story.get("type"),
                },
            )
            trends.append(trend)

        self.last_collection = datetime.now(timezone.utc)
        self.collection_count += 1
        return trends

    def _extract_keywords(self, text: str) -> List[str]:
        """Extract keywords from title."""
        words = re.findall(r'\b[a-zA-Z]{4,}\b', text.lower())
        tech_terms = {"python", "javascript", "rust", "golang", "kubernetes", "docker",
                      "machine", "learning", "startup", "cloud", "data", "open", "source"}
        keywords = [w for w in words if w in tech_terms or len(w) > 5]
        return list(set(keywords))[:10]


class ProductHuntCollector(TrendCollector):
    """Collector for Product Hunt trends via their public feed."""

    def __init__(self):
        super().__init__("Product Hunt", TrendSource.PRODUCT_HUNT)
        self.feed_url = "https://www.producthunt.com/feed"
        self.homepage_url = "https://www.producthunt.com"

    async def collect(self) -> List[Trend]:
        """Collect trends from Product Hunt's Atom feed or homepage."""
        trends = []

        # Try Atom/RSS feed first (structured data)
        raw = self._make_raw_request(self.feed_url)
        if raw:
            try:
                trends = self._parse_feed(raw)
            except Exception as e:
                logger.warning(f"Feed parse failed, trying homepage: {e}")

        # Fallback: scrape homepage JSON data
        if not trends:
            raw = self._make_raw_request(self.homepage_url)
            if raw:
                try:
                    trends = self._parse_homepage(raw)
                except Exception as e:
                    logger.error(f"Homepage parse failed: {e}")
                    self.error_count += 1
                    return []

        if not trends:
            return []

        self.last_collection = datetime.now(timezone.utc)
        self.collection_count += 1
        return trends

    def _parse_feed(self, raw: bytes) -> List[Trend]:
        """Parse Product Hunt Atom/RSS feed."""
        trends = []
        root = ET.fromstring(raw)

        # Handle Atom namespace
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        entries = root.findall("atom:entry", ns)
        if not entries:
            entries = root.findall(".//item")

        for i, entry in enumerate(entries[:20]):
            title_el = entry.find("atom:title", ns)
            if title_el is None:
                title_el = entry.find("title")
            if title_el is None or not title_el.text:
                continue

            name = title_el.text.strip()

            summary_el = entry.find("atom:summary", ns)
            if summary_el is None:
                summary_el = entry.find("description")
            description = ""
            if summary_el is not None and summary_el.text:
                description = re.sub(r"<[^>]+>", "", summary_el.text).strip()[:500]

            # Score based on position (top posts are more popular)
            score = max(30, 90 - (i * 3))

            trend = self._create_trend(
                name=name,
                description=description or f"Featured on Product Hunt: {name}",
                score=score,
                category=TrendCategory.TECHNOLOGY,
                keywords=[w.lower() for w in name.split() if len(w) > 2],
            )
            trends.append(trend)

        return trends

    def _parse_homepage(self, raw: bytes) -> List[Trend]:
        """Extract product data from Product Hunt homepage __NEXT_DATA__ or JSON-LD."""
        trends = []
        html = raw.decode("utf-8", errors="replace")

        # Try to find __NEXT_DATA__ JSON
        match = re.search(r'<script\s+id="__NEXT_DATA__"\s+type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                # Navigate the Next.js data structure for posts
                props = data.get("props", {}).get("pageProps", {})
                posts = props.get("posts", []) or props.get("initialPosts", [])
                for i, post in enumerate(posts[:20]):
                    name = post.get("name", "")
                    if not name:
                        continue
                    tagline = post.get("tagline", "")
                    votes = post.get("votesCount", 0)
                    score = min(100, 40 + votes / 5)
                    trend = self._create_trend(
                        name=name,
                        description=tagline or f"Featured on Product Hunt: {name}",
                        score=score,
                        category=TrendCategory.TECHNOLOGY,
                        keywords=[w.lower() for w in name.split() if len(w) > 2],
                        volume=votes,
                    )
                    trends.append(trend)
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning(f"Failed to parse Product Hunt __NEXT_DATA__: {e}")
                self.error_count += 1

        return trends


class NicheIdentifier:
    """Identifies niche market opportunities from trend data."""

    def __init__(self, db: TrendDatabase):
        self.db = db

        # Niche storefront mapping
        self.storefronts = {
            "tech_gadgets": ["technology", "gadgets", "electronics"],
            "home_wellness": ["health", "lifestyle", "home"],
            "fashion_accessories": ["fashion", "lifestyle", "accessories"],
            "pet_supplies": ["pets", "animals", "lifestyle"],
            "outdoor_adventure": ["outdoor", "sports", "adventure"],
            "sustainable_living": ["eco", "sustainable", "green"],
            "creative_tools": ["art", "creative", "design"],
            "productivity": ["productivity", "work", "business"],
        }

    def identify_niches(
        self,
        trends: List[Trend],
        min_confidence: float = 0.5,
    ) -> List[NicheOpportunity]:
        """Identify niche opportunities from trends."""
        niches = []

        # Group trends by keywords
        keyword_groups: Dict[str, List[Trend]] = {}
        for trend in trends:
            for keyword in trend.keywords:
                if keyword not in keyword_groups:
                    keyword_groups[keyword] = []
                keyword_groups[keyword].append(trend)

        # Find keyword clusters with high scores
        for keyword, group_trends in keyword_groups.items():
            if len(group_trends) < 2:
                continue

            avg_score = sum(t.score for t in group_trends) / len(group_trends)
            avg_velocity = sum(t.velocity for t in group_trends) / len(group_trends)

            if avg_score < 50:
                continue

            # Calculate opportunity metrics
            opportunity_score = (avg_score + (avg_velocity * 50)) / 2
            confidence = min(1.0, len(group_trends) / 5)

            if confidence < min_confidence:
                continue

            # Determine storefront fit
            storefront_fit = []
            for sf, sf_keywords in self.storefronts.items():
                if keyword in sf_keywords or any(kw in keyword for kw in sf_keywords):
                    storefront_fit.append(sf)

            niche = NicheOpportunity(
                name=f"{keyword.title()} Market",
                description=f"Emerging opportunity in {keyword} space based on {len(group_trends)} related trends",
                parent_trend_ids=[t.id for t in group_trends],
                opportunity_score=opportunity_score,
                confidence=confidence,
                growth_rate=avg_velocity * 100,
                competition_density=sum(t.competition_level for t in group_trends) / len(group_trends),
                product_ideas=self._generate_product_ideas(keyword, group_trends),
                target_audience=self._identify_target_audience(group_trends),
                pain_points=self._extract_pain_points(group_trends),
                storefront_fit=storefront_fit,
                product_categories=[keyword],
                recommended_action=self._recommend_action(opportunity_score, avg_velocity),
                urgency=self._calculate_urgency(avg_velocity, opportunity_score),
            )
            niches.append(niche)

        # Sort by opportunity score
        niches.sort(key=lambda n: n.opportunity_score, reverse=True)
        return niches[:20]

    def _generate_product_ideas(self, keyword: str, trends: List[Trend]) -> List[str]:
        """Generate product ideas based on trend data."""
        ideas = []

        # Extract common themes
        all_keywords = []
        for t in trends:
            all_keywords.extend(t.keywords)

        top_keywords = sorted(set(all_keywords), key=all_keywords.count, reverse=True)[:5]

        for kw in top_keywords:
            ideas.append(f"{kw.title()}-focused {keyword} products")

        return ideas[:5]

    def _identify_target_audience(self, trends: List[Trend]) -> str:
        """Identify target audience from trends."""
        categories = [t.category.value for t in trends]
        primary_category = max(set(categories), key=categories.count)

        audience_map = {
            "technology": "Tech enthusiasts and early adopters",
            "ecommerce": "Online shoppers and digital natives",
            "lifestyle": "Lifestyle-conscious consumers",
            "health": "Health and wellness seekers",
            "business": "Entrepreneurs and business professionals",
        }

        return audience_map.get(primary_category, "General consumers")

    def _extract_pain_points(self, trends: List[Trend]) -> List[str]:
        """Extract potential pain points from trend descriptions."""
        pain_points = []

        for trend in trends:
            desc = trend.description.lower()
            if "problem" in desc or "issue" in desc or "need" in desc:
                pain_points.append(f"Addressing {trend.name[:50]} needs")

        return pain_points[:5] or ["Market gap to be explored"]

    def _recommend_action(self, opportunity_score: float, velocity: float) -> str:
        """Recommend action based on metrics."""
        if opportunity_score >= 75 and velocity > 0.3:
            return "IMMEDIATE: High opportunity with strong momentum - act now"
        elif opportunity_score >= 60:
            return "PRIORITIZE: Good opportunity - begin research and planning"
        elif opportunity_score >= 40:
            return "MONITOR: Moderate opportunity - track development"
        else:
            return "OBSERVE: Low priority - keep on watchlist"

    def _calculate_urgency(self, velocity: float, opportunity_score: float) -> str:
        """Calculate urgency level."""
        if velocity > 0.5 and opportunity_score > 70:
            return "critical"
        elif velocity > 0.3 or opportunity_score > 60:
            return "high"
        elif velocity > 0 or opportunity_score > 40:
            return "medium"
        else:
            return "low"


class TrendCollectorManager:
    """Manages multiple trend collectors."""

    def __init__(self, db: Optional[TrendDatabase] = None):
        self.db = db or TrendDatabase()
        self.collectors: Dict[str, TrendCollector] = {}
        self.niche_identifier = NicheIdentifier(self.db)

    def add_collector(self, collector: TrendCollector) -> None:
        """Add a collector."""
        self.collectors[collector.name] = collector
        logger.info(f"Added collector: {collector.name}")

    def add_default_collectors(self) -> None:
        """Add all default collectors."""
        self.add_collector(GoogleTrendsCollector())
        self.add_collector(RedditCollector())
        self.add_collector(HackerNewsCollector())
        self.add_collector(ProductHuntCollector())

        # Conditionally add competitive landscape collectors
        try:
            from trendscope.collectors_competitive import GitHubTrendingCollector, PackageDownloadsCollector
            self.add_collector(GitHubTrendingCollector())
            self.add_collector(PackageDownloadsCollector())
        except ImportError:
            pass  # Competitive collectors optional

        # Conditionally add Knowledge Harvester collector if KH_BASE_URL is set
        import os
        if os.environ.get("KH_BASE_URL"):
            from trendscope.integrations.kh_collector import KnowledgeHarvesterCollector
            self.add_collector(KnowledgeHarvesterCollector())

    def _validate_trend(self, trend: Trend, source_name: str) -> bool:
        """Validate a trend has required fields and sane values."""
        if not trend.name or not trend.name.strip():
            logger.warning(f"Rejected trend from {source_name}: empty name")
            return False
        if len(trend.name) > 500:
            logger.warning(f"Rejected trend from {source_name}: name too long ({len(trend.name)})")
            return False
        if not (0 <= trend.score <= 100):
            logger.warning(f"Rejected trend '{trend.name}' from {source_name}: score {trend.score} out of range")
            return False
        if trend.volume < 0:
            logger.warning(f"Rejected trend '{trend.name}' from {source_name}: negative volume")
            return False
        return True

    async def collect_all(self, save: bool = True) -> List[Trend]:
        """Collect from all sources."""
        all_trends = []

        for name, collector in self.collectors.items():
            try:
                logger.info(f"Collecting from {name}...")
                trends = await collector.collect()
                valid = [t for t in trends if self._validate_trend(t, name)]
                if len(valid) < len(trends):
                    logger.info(f"Filtered {len(trends) - len(valid)} invalid trends from {name}")
                all_trends.extend(valid)
                logger.info(f"Collected {len(valid)} trends from {name}")
            except Exception as e:
                logger.error(f"Collection failed for {name}: {e}")

        if save:
            for trend in all_trends:
                self.db.save_trend(trend)

        return all_trends

    async def collect_from(self, source_name: str, save: bool = True) -> List[Trend]:
        """Collect from a specific source."""
        collector = self.collectors.get(source_name)
        if not collector:
            raise ValueError(f"Unknown collector: {source_name}")

        trends = await collector.collect()
        valid = [t for t in trends if self._validate_trend(t, source_name)]

        if save:
            for trend in valid:
                self.db.save_trend(trend)

        return valid

    def identify_niches(self, min_confidence: float = 0.5) -> List[NicheOpportunity]:
        """Identify niche opportunities from collected trends."""
        trends = self.db.get_trends(limit=200)
        niches = self.niche_identifier.identify_niches(trends, min_confidence)

        # Save niches
        for niche in niches:
            self.db.save_niche(niche)

        return niches

    def get_collector_stats(self) -> Dict[str, Any]:
        """Get statistics for all collectors."""
        stats = {}
        for name, collector in self.collectors.items():
            stats[name] = {
                "source": collector.source.value,
                "last_collection": collector.last_collection.isoformat() if collector.last_collection else None,
                "collection_count": collector.collection_count,
                "error_count": collector.error_count,
            }
        return stats
