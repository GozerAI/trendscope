"""
Knowledge Harvester Collector — creates Trend objects from KH artifact data.

Converts surging artifact categories and popular artifacts into Trend objects,
using TrendSource.INTERNAL to indicate internally-derived trends.
"""

import logging
from typing import List

from trendscope.core import Trend, TrendCategory, TrendSource
from trendscope.collectors import TrendCollector
from trendscope.integrations.kh_client import (
    get_popular,
    get_analytics_trends,
    map_kh_category_to_ts,
)

logger = logging.getLogger(__name__)


class KnowledgeHarvesterCollector(TrendCollector):
    """Collector that creates trends from Knowledge Harvester artifact data."""

    def __init__(self):
        super().__init__("Knowledge Harvester", TrendSource.INTERNAL)

    async def collect(self) -> List[Trend]:
        """Collect trends from KH popular artifacts and analytics."""
        trends = []

        # Get popular artifacts
        popular = get_popular(window="7d", limit=30)
        analytics = get_analytics_trends(window="7d")

        if not popular and not analytics:
            logger.debug("KH unreachable or no data — skipping collection")
            return trends

        # Convert popular artifacts into trends
        seen_names = set()
        for item in popular:
            name = item.get("name") or item.get("artifact_name", "")
            if not name or name in seen_names:
                continue
            seen_names.add(name)

            category_str = item.get("primary_category") or item.get("category", "")
            ts_category = map_kh_category_to_ts(category_str) if category_str else "technology"

            try:
                category = TrendCategory(ts_category)
            except ValueError:
                category = TrendCategory.TECHNOLOGY

            quality = item.get("quality_score") or item.get("avg_quality", 0)
            score = min(100.0, max(0.0, float(quality)))
            volume = item.get("view_count") or item.get("event_count", 0)

            trend = self._create_trend(
                name=f"KH: {name[:90]}",
                description=f"Popular artifact in Knowledge Harvester ({category_str})",
                score=score,
                category=category,
                keywords=self._extract_keywords(name, category_str),
                volume=int(volume),
                raw_data={"source": "knowledge_harvester", "original": item},
            )
            trends.append(trend)

        # Convert analytics trends (category surges) into trends
        for item in analytics:
            category_str = item.get("category") or item.get("primary_category", "")
            count = item.get("count") or item.get("artifact_count", 0)
            if not category_str or int(count) < 2:
                continue

            name = f"KH Surge: {category_str}"
            if name in seen_names:
                continue
            seen_names.add(name)

            ts_category = map_kh_category_to_ts(category_str)
            try:
                category = TrendCategory(ts_category)
            except ValueError:
                category = TrendCategory.TECHNOLOGY

            score = min(100.0, 30.0 + float(count) * 5)

            trend = self._create_trend(
                name=name,
                description=f"Surging artifact category in Knowledge Harvester: {category_str} ({count} artifacts)",
                score=score,
                category=category,
                keywords=[w.lower() for w in category_str.replace("-", " ").split() if len(w) > 2],
                volume=int(count),
                raw_data={"source": "knowledge_harvester_analytics", "original": item},
            )
            trends.append(trend)

        return trends

    def _extract_keywords(self, name: str, category: str) -> List[str]:
        """Extract keywords from artifact name and category."""
        words = set()
        for text in [name, category]:
            for w in text.lower().replace("-", " ").replace("_", " ").split():
                if len(w) > 2:
                    words.add(w)
        return list(words)[:10]
