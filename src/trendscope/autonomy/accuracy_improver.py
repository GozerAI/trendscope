"""Accuracy improver — learns from prediction outcomes to improve accuracy."""


class AccuracyImprover:
    """Improves trend prediction accuracy through feedback loops."""

    def __init__(self):
        self.feedback_history: list[dict] = []

    async def record_outcome(self, prediction_id: str, actual: dict) -> None:
        """Record actual outcome for a prediction to improve future accuracy."""
        self.feedback_history.append({"prediction_id": prediction_id, "actual": actual})
