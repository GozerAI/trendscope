"""Time-window comparison analysis."""

import sqlite3
from datetime import datetime, timezone, timedelta


class TimeComparator:
    def __init__(self, db):
        self.db = db

    def compare_windows(self, window_a: dict, window_b: dict) -> dict:
        """Compare trend metrics between two time windows."""

        def get_window_stats(start, end):
            with sqlite3.connect(self.db.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT category, COUNT(*) as count, AVG(score) as avg_score "
                    "FROM trends WHERE last_updated BETWEEN ? AND ? "
                    "GROUP BY category",
                    (start, end),
                )
                stats: dict = {}
                total = 0
                for row in cursor.fetchall():
                    cat = row[0] or "uncategorized"
                    stats[cat] = {
                        "count": row[1],
                        "avg_score": round(row[2] or 0, 2),
                    }
                    total += row[1]
                return {"categories": stats, "total": total}

        a_stats = get_window_stats(window_a["start"], window_a["end"])
        b_stats = get_window_stats(window_b["start"], window_b["end"])

        total_delta = b_stats["total"] - a_stats["total"]

        return {
            "window_a": {**window_a, "stats": a_stats},
            "window_b": {**window_b, "stats": b_stats},
            "delta": {
                "total": total_delta,
                "percent": (
                    round(total_delta / a_stats["total"] * 100, 2)
                    if a_stats["total"] > 0
                    else 0
                ),
            },
        }

    def this_vs_last(self, period: str = "week") -> dict:
        """Compare current period vs previous period."""
        now = datetime.now(timezone.utc)
        if period == "day":
            delta = timedelta(days=1)
        elif period == "month":
            delta = timedelta(days=30)
        else:  # week
            delta = timedelta(weeks=1)

        window_b = {"start": (now - delta).isoformat(), "end": now.isoformat()}
        window_a = {
            "start": (now - 2 * delta).isoformat(),
            "end": (now - delta).isoformat(),
        }
        return self.compare_windows(window_a, window_b)

    def movers_report(self, period: str = "week") -> dict:
        """Find biggest gainers and losers."""
        now = datetime.now(timezone.utc)

        if period == "day":
            delta = timedelta(days=1)
        elif period == "month":
            delta = timedelta(days=30)
        else:
            delta = timedelta(weeks=1)

        cutoff = (now - delta).isoformat()

        trends = self.db.get_trends(limit=1000)
        movers = []
        for trend in trends:
            history = self.db.get_trend_history(trend.id)
            if len(history) < 2:
                continue
            recent = [
                h
                for h in history
                if isinstance(h, dict) and h.get("timestamp", "") >= cutoff
            ]
            if not recent:
                continue
            first_score = (
                recent[0].get("score", recent[0].get("value", 0))
                if isinstance(recent[0], dict)
                else 0
            )
            last_score = (
                recent[-1].get("score", recent[-1].get("value", 0))
                if isinstance(recent[-1], dict)
                else 0
            )
            change = last_score - first_score
            if abs(change) > 0:
                movers.append(
                    {
                        "trend_id": trend.id,
                        "trend_name": trend.name,
                        "change": change,
                        "direction": "up" if change > 0 else "down",
                    }
                )

        movers.sort(key=lambda x: abs(x["change"]), reverse=True)
        gainers = [m for m in movers if m["direction"] == "up"][:10]
        losers = [m for m in movers if m["direction"] == "down"][:10]

        return {"gainers": gainers, "losers": losers, "period": period}
