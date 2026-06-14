"""
#297 — Premium insight preview for free users.

Shows free users a teaser of premium insights (blurred details, partial data)
to demonstrate value and drive conversion to paid plans.
"""

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Fields visible to free users in a preview
_FREE_PREVIEW_FIELDS = {"name", "category", "status", "score"}
# Fields that get redacted (shown as teaser)
_PREMIUM_FIELDS = {
    "velocity", "momentum", "market_opportunity", "competition_level",
    "entry_barrier", "keywords", "related_trends", "history",
}
# Maximum number of full insights free users can see per day
FREE_DAILY_INSIGHT_LIMIT = 3
# Percentage of detail shown in blurred previews
PREVIEW_DETAIL_RATIO = 0.25


@dataclass
class PreviewImpression:
    """Tracks when a free user views a premium preview."""
    user_id: str
    insight_id: str
    timestamp: float = field(default_factory=time.time)
    converted: bool = False


class PremiumInsightPreview:
    """Generates gated previews of premium trend insights for free-tier users.

    Free users see a limited view of trend data: name, category, status, and
    a rounded score. Premium fields (velocity, momentum, keywords, etc.) are
    replaced with redacted placeholders that hint at the value behind the paywall.
    """

    def __init__(self, daily_limit: int = FREE_DAILY_INSIGHT_LIMIT):
        self._daily_limit = daily_limit
        self._impressions: List[PreviewImpression] = []
        self._conversion_clicks: Dict[str, int] = {}

    # ── Public API ───────────────────────────────────────────────

    def generate_preview(self, trend_dict: Dict[str, Any], user_id: str) -> Dict[str, Any]:
        """Return a gated preview of a trend insight.

        Args:
            trend_dict: Full trend data as a dict (from Trend.to_dict()).
            user_id: Identifier for the requesting user.

        Returns:
            Dict with visible fields intact, premium fields redacted, and
            an ``upgrade_cta`` block with conversion messaging.
        """
        preview: Dict[str, Any] = {}

        for key in _FREE_PREVIEW_FIELDS:
            if key in trend_dict:
                val = trend_dict[key]
                # Round score to nearest 5 to tease precision
                if key == "score" and isinstance(val, (int, float)):
                    val = round(val / 5) * 5
                preview[key] = val

        redacted_count = 0
        for key in _PREMIUM_FIELDS:
            if key in trend_dict:
                preview[key] = self._redact_value(key, trend_dict[key])
                redacted_count += 1

        preview["is_preview"] = True
        preview["redacted_fields"] = redacted_count
        preview["upgrade_cta"] = self._build_cta(trend_dict, user_id)

        self._record_impression(user_id, trend_dict.get("id", ""))
        return preview

    def generate_batch_preview(
        self, trends: List[Dict[str, Any]], user_id: str
    ) -> Dict[str, Any]:
        """Generate previews for multiple trends, enforcing daily limits.

        Returns a dict with ``previews`` (list) and ``remaining_today`` count.
        """
        remaining = self.get_remaining_today(user_id)
        previews = []
        for trend in trends:
            previews.append(self.generate_preview(trend, user_id))
        return {
            "previews": previews,
            "total": len(previews),
            "remaining_today": max(0, remaining - len(trends)),
            "daily_limit": self._daily_limit,
        }

    def get_remaining_today(self, user_id: str) -> int:
        """How many full-detail previews this user has left today."""
        today_start = _day_start()
        count = sum(
            1 for imp in self._impressions
            if imp.user_id == user_id and imp.timestamp >= today_start
        )
        return max(0, self._daily_limit - count)

    def record_conversion_click(self, user_id: str) -> None:
        """Record that a user clicked an upgrade CTA from a preview."""
        self._conversion_clicks[user_id] = self._conversion_clicks.get(user_id, 0) + 1

    def get_conversion_stats(self) -> Dict[str, Any]:
        """Return aggregate conversion metrics."""
        total_impressions = len(self._impressions)
        unique_users = len({imp.user_id for imp in self._impressions})
        total_clicks = sum(self._conversion_clicks.values())
        click_users = len(self._conversion_clicks)
        return {
            "total_impressions": total_impressions,
            "unique_users": unique_users,
            "total_cta_clicks": total_clicks,
            "clicking_users": click_users,
            "click_rate": total_clicks / total_impressions if total_impressions else 0.0,
        }

    # ── Internals ────────────────────────────────────────────────

    def _redact_value(self, key: str, value: Any) -> Any:
        """Replace a premium field value with a teaser placeholder."""
        if isinstance(value, (int, float)):
            # Show direction but not magnitude
            if value > 0:
                return {"hint": "positive", "unlock": True}
            elif value < 0:
                return {"hint": "negative", "unlock": True}
            return {"hint": "neutral", "unlock": True}
        if isinstance(value, list):
            shown = max(1, int(len(value) * PREVIEW_DETAIL_RATIO))
            return {
                "sample": value[:shown],
                "hidden_count": len(value) - shown,
                "unlock": True,
            }
        if isinstance(value, str):
            return {"hint": value[:12] + "..." if len(value) > 12 else value, "unlock": True}
        return {"unlock": True}

    def _build_cta(self, trend_dict: Dict[str, Any], user_id: str) -> Dict[str, str]:
        """Build a contextual upgrade call-to-action."""
        name = trend_dict.get("name", "this trend")
        score = trend_dict.get("score", 0)
        if score >= 80:
            message = f"'{name}' is a high-signal trend. Upgrade to see full velocity, momentum, and competitive data."
        elif score >= 50:
            message = f"'{name}' is gaining traction. Unlock detailed analysis with a Pro subscription."
        else:
            message = f"Get full insights on '{name}' and every other trend with Trendscope Pro."
        return {
            "message": message,
            "action": "upgrade_to_pro",
            "target_url": "/pricing?ref=preview",
        }

    def _record_impression(self, user_id: str, insight_id: str) -> None:
        self._impressions.append(PreviewImpression(user_id=user_id, insight_id=insight_id))


def _day_start() -> float:
    """Epoch timestamp for start of current UTC day."""
    t = time.gmtime()
    return time.mktime(time.strptime(time.strftime("%Y-%m-%d", t), "%Y-%m-%d"))
