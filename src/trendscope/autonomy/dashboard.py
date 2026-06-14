"""Autonomy dashboard -- unified system pulse."""

from datetime import datetime, timezone


class AutonomyDashboard:
    def __init__(self, service):
        """Takes the service instance to access all subsystems."""
        self.service = service

    def get_system_pulse(self) -> dict:
        """Aggregate health/status of entire autonomous system."""
        pulse = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "scheduler": self._get_scheduler_status(),
            "anomalies": self._get_anomaly_status(),
            "coverage": self._get_coverage_status(),
            "feed": self._get_feed_status(),
        }
        pulse["health_score"] = self.get_health_score()
        return pulse

    def _get_scheduler_status(self) -> dict:
        try:
            scheduler = self.service._scheduler
            schedules = scheduler.list_schedules()
            active = sum(1 for s in schedules if s.get("enabled"))
            return {"total": len(schedules), "active": active, "status": "ok"}
        except Exception:
            return {"status": "unavailable"}

    def _get_anomaly_status(self) -> dict:
        try:
            results = self.service.detect_anomalies(lookback_days=1)
            return {"recent_count": len(results), "status": "ok"}
        except Exception:
            return {"status": "unavailable"}

    def _get_coverage_status(self) -> dict:
        try:
            report = self.service._coverage_analyzer.get_coverage_report()
            return {
                "categories": report["summary"]["total_categories"],
                "blind_spots": report["summary"]["blind_spot_count"],
                "status": "ok",
            }
        except Exception:
            return {"status": "unavailable"}

    def _get_feed_status(self) -> dict:
        try:
            summary = self.service._feed.get_summary(minutes=60)
            return {"events_last_hour": summary["total"], "status": "ok"}
        except Exception:
            return {"status": "unavailable"}

    def get_timeline(self, hours: int = 24) -> list[dict]:
        """Get autonomous actions timeline."""
        try:
            return self.service._feed.get_recent(minutes=hours * 60)
        except Exception:
            return []

    def get_health_score(self) -> int:
        """0-100 composite health score."""
        score = 100
        try:
            scheduler = self.service._scheduler
            schedules = scheduler.list_schedules()
            errors = sum(
                1 for s in schedules if s.get("last_status") == "error"
            )
            score -= errors * 15
        except Exception:
            score -= 20

        try:
            blind_spots = self.service._coverage_analyzer.identify_blind_spots()
            score -= min(len(blind_spots) * 5, 30)
        except Exception:
            score -= 10

        return max(0, min(100, score))
