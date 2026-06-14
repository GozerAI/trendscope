"""Cross-system sync with Knowledge Harvester."""

import json
from datetime import datetime, timezone
from typing import Optional

# Optional telemetry
try:
    from gozerai_telemetry.metrics import get_collector
    _collector = get_collector("trendscope")
    _sync_counter = _collector.counter("kh_sync_total", "Total KH sync operations")
except ImportError:
    _sync_counter = None

# Optional resilience
try:
    from gozerai_telemetry.resilience import (
        resilient_fetch,
        get_circuit_breaker,
        CONSERVATIVE_RETRY,
    )
    _HAS_RESILIENCE = True
except ImportError:
    _HAS_RESILIENCE = False


def _fetch_kh(base_url: str, path: str) -> Optional[dict]:
    """Fetch from KH with graceful degradation."""
    url = f"{base_url}{path}"
    if _HAS_RESILIENCE:
        _cb = get_circuit_breaker("kh", failure_threshold=3, recovery_timeout=120)
        return resilient_fetch(
            url, headers={"Accept": "application/json"},
            timeout=5.0, retry_policy=CONSERVATIVE_RETRY, circuit_breaker=_cb,
        )
    try:
        import urllib.request

        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


class KHSync:
    def __init__(self, db, kh_base_url: str = "http://localhost:8011"):
        self.db = db
        self.kh_base_url = kh_base_url
        self._last_sync: Optional[str] = None
        self._sync_status = "never"

    def sync_from_kh(self) -> dict:
        """Fetch KH coverage gaps and create monitoring targets."""
        gaps = _fetch_kh(self.kh_base_url, "/api/coverage/gaps")
        if gaps is None:
            self._sync_status = "failed"
            if _sync_counter:
                _sync_counter.inc(status="failed")
            return {"status": "failed", "reason": "KH unreachable"}

        new_targets = []
        if isinstance(gaps, list):
            for gap in gaps:
                category = gap.get("category", "")
                if category:
                    new_targets.append(
                        {
                            "category": category,
                            "source": "kh_gap",
                            "priority": gap.get("deficit", 0),
                        }
                    )

        self._last_sync = datetime.now(timezone.utc).isoformat()
        self._sync_status = "success"
        if _sync_counter:
            _sync_counter.inc(status="success")
        return {
            "status": "success",
            "new_targets": len(new_targets),
            "targets": new_targets,
            "synced_at": self._last_sync,
        }

    def get_sync_status(self) -> dict:
        return {
            "status": self._sync_status,
            "last_sync": self._last_sync,
            "kh_base_url": self.kh_base_url,
        }

    def receive_intelligence(self, payload: dict) -> dict:
        """Process intelligence webhook from KH."""
        event_type = payload.get("event", "")
        data = payload.get("data", {})
        self._last_sync = datetime.now(timezone.utc).isoformat()

        if event_type == "intelligence.update":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "processed_at": self._last_sync,
            }

        if event_type == "artifact.stale":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "stale_alert",
                "processed_at": self._last_sync,
            }

        if event_type == "harvest.complete":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "sync_refresh",
                "processed_at": self._last_sync,
            }

        if event_type == "graph.materialized":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "graph_update",
                "processed_at": self._last_sync,
            }

        if event_type == "pipeline.run.complete":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "pipeline_complete",
                "processed_at": self._last_sync,
            }

        if event_type == "refresh.complete":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "refresh_logged",
                "processed_at": self._last_sync,
            }

        if event_type == "snapshot.diff":
            self._sync_status = "success"
            return {
                "status": "accepted",
                "event": event_type,
                "action": "diff_received",
                "processed_at": self._last_sync,
            }

        return {"status": "ignored", "event": event_type}
