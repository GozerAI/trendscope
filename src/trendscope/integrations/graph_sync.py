"""Sync trend data to Knowledge Harvester's intelligence graph."""

import json
import logging
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)


def sync_trends_to_graph(trends, kh_base_url=None):
    """Push trend nodes to KH's intelligence graph.

    Args:
        trends: List of Trend objects to sync
        kh_base_url: KH API base URL (default from env)

    Returns:
        dict with sync results, or None on failure.
    """
    import os
    base_url = kh_base_url or os.environ.get("KH_BASE_URL", "http://localhost:8011")

    nodes = []
    for trend in trends:
        nodes.append({
            "type": "trend",
            "id": trend.id,
            "data": {
                "label": trend.name,
                "source": trend.source.name if hasattr(trend.source, 'name') else str(trend.source),
                "category": trend.category.name if hasattr(trend.category, 'name') else str(trend.category),
                "score": trend.score,
                "velocity": trend.velocity,
                "momentum": trend.momentum,
                "status": trend.status.name if hasattr(trend.status, 'name') else str(trend.status),
                "signal": trend.get_signal().name if hasattr(trend.get_signal(), 'name') else str(trend.get_signal()),
            },
        })

    if not nodes:
        return {"synced": 0, "status": "no_trends"}

    try:
        url = f"{base_url}/api/graph/nodes"
        body = json.dumps({"nodes": nodes}).encode("utf-8")
        req = Request(url, data=body, headers={"Content-Type": "application/json"})
        with urlopen(req, timeout=15) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            return {"synced": len(nodes), "status": "ok", "response": result}
    except (URLError, OSError) as e:
        logger.warning(f"Graph sync failed: {e}")
        return {"synced": 0, "status": "failed", "error": str(e)}
    except Exception as e:
        logger.warning(f"Unexpected graph sync error: {e}")
        return {"synced": 0, "status": "error", "error": str(e)}
