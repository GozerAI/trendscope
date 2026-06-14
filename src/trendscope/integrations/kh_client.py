"""
Knowledge Harvester HTTP client for Trendscope.

Uses urllib.request (stdlib) — no external dependencies.
Graceful degradation: returns empty data if KH is unreachable.
"""

import json
import logging
import os
import urllib.request
import urllib.error
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Optional resilience
try:
    from gozerai_telemetry.resilience import (
        resilient_fetch,
        get_circuit_breaker,
        DEFAULT_RETRY,
    )
    _HAS_RESILIENCE = True
    _kh_cb = get_circuit_breaker("kh_client", failure_threshold=3, recovery_timeout=120)
except ImportError:
    _HAS_RESILIENCE = False
    _kh_cb = None

KH_BASE_URL = os.environ.get("KH_BASE_URL", "http://localhost:8011")

# TS category -> KH categories (reverse mapping)
CATEGORY_MAP: Dict[str, List[str]] = {
    "technology": [
        "ai-agent", "ai-image-generation", "ml-data-ops", "streaming-realtime",
        "ci-cd-pipeline", "devops-monitoring", "infrastructure-as-code", "security-automation",
    ],
    "ecommerce": ["ecommerce"],
    "business": ["lead-gen-crm", "finance-accounting", "business-process"],
    "consumer": ["customer-support", "general-productivity", "iot-home-automation"],
    "niche_market": ["data-pipeline", "data-processing", "orchestration", "integration-pipeline"],
    "emerging": ["multi-step-automation", "content-marketing"],
}


def _request(path: str, timeout: int = 5) -> Optional[Any]:
    """Make HTTP GET request to KH API. Returns parsed JSON or None on failure."""
    url = f"{KH_BASE_URL}{path}"
    if _HAS_RESILIENCE:
        return resilient_fetch(
            url, headers={"User-Agent": "Trendscope/1.0"},
            timeout=float(timeout), retry_policy=DEFAULT_RETRY, circuit_breaker=_kh_cb,
        )
    try:
        req = urllib.request.Request(url)
        req.add_header("User-Agent", "Trendscope/1.0")
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        logger.error("KH HTTP %d for %s: %s", e.code, url, e.reason)
        return None
    except urllib.error.URLError as e:
        logger.debug("KH unreachable: %s", e.reason)
        return None
    except Exception as e:
        logger.debug("KH request failed: %s", e)
        return None


def get_artifacts(
    tags: Optional[List[str]] = None,
    category: Optional[str] = None,
    quality_min: int = 0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """
    Get artifacts from KH, optionally filtered by tags, category, and quality.

    Returns empty list if KH is unreachable.
    """
    params = [f"limit={limit}"]
    if category:
        params.append(f"category={urllib.request.quote(category)}")
    if quality_min > 0:
        params.append(f"quality_min={quality_min}")
    if tags:
        params.append(f"tags={urllib.request.quote(','.join(tags))}")

    path = f"/api/artifacts?{'&'.join(params)}"
    result = _request(path)

    if result is None:
        return []

    # KH returns { artifacts: [...] } or a list
    if isinstance(result, dict):
        return result.get("artifacts", [])
    if isinstance(result, list):
        return result
    return []


def get_popular(window: str = "7d", limit: int = 20) -> List[Dict[str, Any]]:
    """Get popular artifacts from KH analytics."""
    result = _request(f"/api/analytics/popular?window={window}&limit={limit}")
    if result is None:
        return []
    if isinstance(result, dict):
        return result.get("results", [])
    return []


def get_analytics_trends(window: str = "7d") -> List[Dict[str, Any]]:
    """Get analytics trends from KH."""
    result = _request(f"/api/analytics/trends?window={window}")
    if result is None:
        return []
    if isinstance(result, dict):
        return result.get("results", [])
    return []


def get_trending_artifacts(limit: int = 20) -> List[Dict[str, Any]]:
    """Get artifacts that have been enriched with trend signals."""
    result = _request(f"/api/artifacts/trending?limit={limit}")
    if result is None:
        return []
    if isinstance(result, dict):
        return result.get("trending", [])
    return []


def map_ts_category_to_kh(ts_category: str) -> List[str]:
    """Map a Trendscope category to KH categories."""
    return CATEGORY_MAP.get(ts_category, [])


def map_kh_category_to_ts(kh_category: str) -> str:
    """Map a KH category to a Trendscope category."""
    for ts_cat, kh_cats in CATEGORY_MAP.items():
        if kh_category in kh_cats:
            return ts_cat
    return "technology"


def push_graph_nodes(nodes: List[Dict[str, Any]], base_url: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Push nodes to KH intelligence graph."""
    url_base = base_url or KH_BASE_URL
    try:
        body = json.dumps({"nodes": nodes}).encode("utf-8")
        req = urllib.request.Request(
            f"{url_base}/api/graph/nodes",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to push graph nodes: {e}")
        return None


def query_graph(
    start_type: str,
    start_id: str,
    edge_types: Optional[List[str]] = None,
    depth: int = 2,
    base_url: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Query KH intelligence graph."""
    url_base = base_url or KH_BASE_URL
    try:
        body = json.dumps({
            "start_type": start_type,
            "start_id": start_id,
            "edge_types": edge_types or [],
            "depth": depth,
        }).encode("utf-8")
        req = urllib.request.Request(
            f"{url_base}/api/graph/query",
            data=body,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.warning(f"Failed to query graph: {e}")
        return None
