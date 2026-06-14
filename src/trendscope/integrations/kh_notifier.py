"""Notify Knowledge Harvester when anomalies are detected."""
import json
from typing import Optional

# Optional resilience
try:
    from gozerai_telemetry.resilience import (
        get_circuit_breaker,
        RetryPolicy,
    )
    _HAS_RESILIENCE = True
except ImportError:
    _HAS_RESILIENCE = False


# Reverse map from TS categories to KH categories
TS_TO_KH_CATEGORY = {
    'technology': 'ai-agent',
    'ecommerce': 'ecommerce',
    'business': 'lead-gen-crm',
    'consumer': 'customer-support',
    'niche_market': 'data-pipeline',
    'emerging': 'multi-step-automation',
    'finance': 'finance-accounting',
    'social': 'content-marketing',
}


def _post_to_kh(base_url: str, path: str, payload: dict) -> Optional[dict]:
    """POST JSON to KH with graceful degradation and optional circuit breaker."""
    if _HAS_RESILIENCE:
        _cb = get_circuit_breaker("kh_notifier", failure_threshold=3, recovery_timeout=120)
        _retry = RetryPolicy(max_retries=2, base_delay=1.0)
    else:
        _cb = None
        _retry = None

    import urllib.request
    import time

    url = f"{base_url}{path}"
    body = json.dumps(payload).encode()
    max_attempts = _retry.max_retries + 1 if _retry else 1

    for attempt in range(max_attempts):
        # Check circuit breaker before attempting
        if _cb is not None and not _cb.allow_request():
            return None
        try:
            req = urllib.request.Request(
                url,
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                result = json.loads(resp.read())
                if _cb is not None:
                    _cb.record_success()
                return result
        except Exception:
            if _cb is not None:
                _cb.record_failure()
            if attempt < max_attempts - 1 and _retry:
                time.sleep(_retry.base_delay * (2 ** attempt))
            continue
    return None


class KHAnomalyNotifier:
    def __init__(self, kh_base_url: str = "http://localhost:8011"):
        self.kh_base_url = kh_base_url
        self._notifications_sent = 0
        self._errors = 0

    def notify_anomalies(self, anomalies: list) -> dict:
        """Group anomalies by category and notify KH."""
        if not anomalies:
            return {"sent": 0, "errors": 0}

        # Group by trend category (from anomaly results)
        categories_seen = set()
        for anomaly in anomalies:
            # AnomalyResult has trend_name but we need category
            # Map through the trend_id or use a generic approach
            cat = getattr(anomaly, 'category', None) or 'technology'
            kh_cat = TS_TO_KH_CATEGORY.get(cat, cat)
            categories_seen.add(kh_cat)

        sent = 0
        errors = 0
        for kh_category in categories_seen:
            result = _post_to_kh(
                self.kh_base_url,
                "/api/research/gaps",
                {
                    "source": "trendscope_anomaly",
                    "category": kh_category,
                    "reason": f"Anomaly detected in {kh_category} trends",
                    "anomaly_count": len(anomalies),
                }
            )
            if result is not None:
                sent += 1
                self._notifications_sent += 1
            else:
                errors += 1
                self._errors += 1

        return {"sent": sent, "errors": errors, "categories": list(categories_seen)}

    def get_stats(self) -> dict:
        return {"notifications_sent": self._notifications_sent, "errors": self._errors}
