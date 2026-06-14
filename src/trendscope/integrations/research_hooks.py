"""Research hooks for the autonomous research agent."""

from trendscope.core import TrendSignal


def get_strong_buy_trends(db, min_score=80):
    """Get trends with STRONG_BUY signal.

    Args:
        db: TrendDatabase instance
        min_score: Minimum score threshold

    Returns:
        List of trend dicts with strong buy signals.
    """
    trends = db.get_trends(limit=200)
    strong_buys = []
    for trend in trends:
        signal = trend.get_signal()
        if signal == TrendSignal.STRONG_BUY and trend.score >= min_score:
            strong_buys.append({
                "id": trend.id,
                "name": trend.name,
                "score": trend.score,
                "velocity": trend.velocity,
                "momentum": trend.momentum,
                "category": trend.category.name,
                "source": trend.source.name,
                "signal": signal.name,
                "keywords": trend.keywords or [],
            })
    return strong_buys
