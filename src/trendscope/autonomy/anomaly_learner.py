"""Anomaly learner — learns to detect anomalous trend patterns."""


class AnomalyLearner:
    """Learns anomaly patterns from trend data."""

    def __init__(self):
        self.patterns: list[dict] = []

    async def detect(self, data: dict) -> list[dict]:
        """Detect anomalies in trend data."""
        return []
