"""
Nexus publisher for Trendscope — publishes market intelligence to
the shared Nexus knowledge base.

Sends trend signals, market analysis, and intelligence findings so
that C-Suite executives and other products can query them.

Configuration:
    NEXUS_BASE_URL: Nexus service URL (default: http://localhost:8008)
"""

import logging
import os
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

NEXUS_BASE_URL = os.environ.get("NEXUS_BASE_URL", "http://localhost:8008")
NEXUS_TIMEOUT = 10.0


class NexusPublisher:
    """Publishes Trendscope intelligence to Nexus knowledge base."""

    def __init__(self, base_url: Optional[str] = None):
        self._base_url = base_url or NEXUS_BASE_URL

    async def publish_trend_signal(
        self,
        signal_name: str,
        category: str,
        analysis: str,
        confidence: float = 0.7,
        tags: Optional[List[str]] = None,
    ) -> Optional[str]:
        """Publish a trend signal to Nexus.

        Returns knowledge_id on success, None on failure (never raises).
        """
        payload = {
            "content": f"Trend signal ({category}): {signal_name} — {analysis}",
            "knowledge_type": "factual",
            "source": f"trendscope:{category}",
            "confidence": confidence,
            "context_tags": ["trendscope", "trend_signal", category] + (tags or []),
        }
        return await self._post_knowledge(payload)

    async def publish_market_analysis(
        self,
        topic: str,
        analysis: str,
        domain: str = "market",
        confidence: float = 0.8,
    ) -> Optional[str]:
        """Publish a market analysis finding to Nexus."""
        payload = {
            "content": f"Market analysis ({domain}): {topic} — {analysis[:2000]}",
            "knowledge_type": "experiential",
            "source": f"trendscope:{domain}",
            "confidence": confidence,
            "context_tags": ["trendscope", "market_analysis", domain],
        }
        return await self._post_knowledge(payload)

    async def get_relevant_knowledge(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """Fetch knowledge relevant to a query from Nexus."""
        try:
            async with httpx.AsyncClient(timeout=NEXUS_TIMEOUT) as client:
                resp = await client.get(
                    f"{self._base_url}/api/knowledge/search",
                    params={"q": query[:200], "limit": limit},
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("items", [])
        except Exception as e:
            logger.debug("Nexus knowledge fetch failed: %s", e)
            return []

    async def _post_knowledge(self, payload: Dict[str, Any]) -> Optional[str]:
        """Post a knowledge item to Nexus. Returns ID or None."""
        try:
            async with httpx.AsyncClient(timeout=NEXUS_TIMEOUT) as client:
                resp = await client.post(
                    f"{self._base_url}/api/knowledge",
                    json=payload,
                )
                resp.raise_for_status()
                data = resp.json()
                kid = data.get("id")
                if kid:
                    logger.info("Published to Nexus: %s", kid)
                return kid
        except Exception as e:
            logger.debug("Nexus publish failed: %s", e)
            return None
