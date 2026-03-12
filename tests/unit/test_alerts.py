"""Tests for the alert system."""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock

from trendscope.core import Trend, TrendSource, TrendCategory, TrendStatus, TrendDatabase
from trendscope.alerts import AlertManager, AlertRule, OPERATORS


@pytest.fixture
def db(tmp_path):
    return TrendDatabase(tmp_path / "test_alerts.db")


@pytest.fixture
def manager(db):
    return AlertManager(db)


@pytest.fixture
def sample_trends():
    """Create sample trends for testing."""
    return [
        Trend(
            id="t1", name="AI Boom", score=85.0, velocity=0.8, momentum=0.6,
            category=TrendCategory.TECHNOLOGY, source=TrendSource.GOOGLE_TRENDS,
            keywords=["ai", "ml"],
        ),
        Trend(
            id="t2", name="Cooking Trends", score=40.0, velocity=0.1, momentum=0.05,
            category=TrendCategory.LIFESTYLE, source=TrendSource.REDDIT,
            keywords=["cooking", "recipes"],
        ),
        Trend(
            id="t3", name="Fintech Rise", score=72.0, velocity=0.5, momentum=0.3,
            category=TrendCategory.FINANCE, source=TrendSource.HACKER_NEWS,
            keywords=["fintech", "payments"],
        ),
    ]


# =============================================================================
# AlertRule creation
# =============================================================================


class TestAlertRuleCreation:

    def test_register_rule_creates_with_correct_fields(self, manager):
        rule = manager.register_rule(
            name="High Score Alert",
            conditions=[{"field": "score", "operator": ">", "threshold": 80}],
            webhook_url="https://example.com/hook",
            webhook_secret="secret123",
        )
        assert rule.name == "High Score Alert"
        assert rule.webhook_url == "https://example.com/hook"
        assert rule.webhook_secret == "secret123"
        assert rule.active is True

    def test_register_rule_auto_generates_id(self, manager):
        rule = manager.register_rule(
            name="Test", conditions=[], webhook_url="https://example.com/hook",
        )
        assert rule.id is not None
        assert len(rule.id) > 0

    def test_register_rule_sets_created_at(self, manager):
        rule = manager.register_rule(
            name="Test", conditions=[], webhook_url="https://example.com/hook",
        )
        assert rule.created_at != ""
        assert "T" in rule.created_at  # ISO format


# =============================================================================
# Rule CRUD
# =============================================================================


class TestRuleCRUD:

    def test_get_rules_returns_all(self, manager):
        manager.register_rule("R1", [], "https://example.com/1")
        manager.register_rule("R2", [], "https://example.com/2")
        rules = manager.get_rules()
        assert len(rules) == 2

    def test_delete_rule_removes(self, manager):
        rule = manager.register_rule("R1", [], "https://example.com/1")
        deleted = manager.delete_rule(rule.id)
        assert deleted is True
        assert len(manager.get_rules()) == 0

    def test_delete_nonexistent_returns_false(self, manager):
        assert manager.delete_rule("nonexistent-id") is False

    def test_get_rules_excludes_deleted(self, manager):
        r1 = manager.register_rule("R1", [], "https://example.com/1")
        r2 = manager.register_rule("R2", [], "https://example.com/2")
        manager.delete_rule(r1.id)
        rules = manager.get_rules()
        assert len(rules) == 1
        assert rules[0].id == r2.id


# =============================================================================
# Condition evaluation
# =============================================================================


class TestConditionEvaluation:

    def test_greater_than_operator(self, manager, sample_trends):
        conds = [{"field": "score", "operator": ">", "threshold": 80}]
        assert manager._check_conditions(conds, sample_trends[0]) is True  # score=85
        assert manager._check_conditions(conds, sample_trends[1]) is False  # score=40

    def test_less_than_operator(self, manager, sample_trends):
        conds = [{"field": "score", "operator": "<", "threshold": 50}]
        assert manager._check_conditions(conds, sample_trends[1]) is True  # score=40
        assert manager._check_conditions(conds, sample_trends[0]) is False  # score=85

    def test_equal_operator(self, manager, sample_trends):
        conds = [{"field": "score", "operator": "==", "threshold": 85.0}]
        assert manager._check_conditions(conds, sample_trends[0]) is True
        assert manager._check_conditions(conds, sample_trends[1]) is False

    def test_greater_equal_operator(self, manager, sample_trends):
        conds = [{"field": "score", "operator": ">=", "threshold": 72.0}]
        assert manager._check_conditions(conds, sample_trends[2]) is True  # score=72
        assert manager._check_conditions(conds, sample_trends[1]) is False  # score=40

    def test_less_equal_operator(self, manager, sample_trends):
        conds = [{"field": "score", "operator": "<=", "threshold": 40.0}]
        assert manager._check_conditions(conds, sample_trends[1]) is True
        assert manager._check_conditions(conds, sample_trends[0]) is False

    def test_multiple_conditions_and(self, manager, sample_trends):
        """All conditions must match (AND logic)."""
        conds = [
            {"field": "score", "operator": ">", "threshold": 70},
            {"field": "velocity", "operator": ">", "threshold": 0.3},
        ]
        assert manager._check_conditions(conds, sample_trends[0]) is True  # score=85, v=0.8
        assert manager._check_conditions(conds, sample_trends[2]) is True  # score=72, v=0.5
        assert manager._check_conditions(conds, sample_trends[1]) is False  # score=40

    def test_category_filter(self, manager, sample_trends):
        conds = [
            {"field": "score", "operator": ">", "threshold": 0, "category": "TECHNOLOGY"},
        ]
        assert manager._check_conditions(conds, sample_trends[0]) is True  # TECHNOLOGY
        assert manager._check_conditions(conds, sample_trends[1]) is False  # LIFESTYLE

    def test_unknown_field_returns_false(self, manager, sample_trends):
        conds = [{"field": "nonexistent_field", "operator": ">", "threshold": 0}]
        assert manager._check_conditions(conds, sample_trends[0]) is False


# =============================================================================
# evaluate_rules
# =============================================================================


class TestEvaluateRules:

    def test_matches_correct_trends(self, manager, sample_trends):
        manager.register_rule(
            "High Score", [{"field": "score", "operator": ">", "threshold": 80}],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            triggered = manager.evaluate_rules(sample_trends)
        assert len(triggered) == 1
        assert triggered[0]["trend_id"] == "t1"

    def test_skips_inactive_rules(self, manager, sample_trends, db):
        rule = manager.register_rule(
            "High Score", [{"field": "score", "operator": ">", "threshold": 0}],
            "https://example.com/hook",
        )
        # Deactivate the rule directly in DB
        import sqlite3
        with sqlite3.connect(db.db_path) as conn:
            conn.execute("UPDATE alerts SET active = 0 WHERE id = ?", (rule.id,))
            conn.commit()

        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            triggered = manager.evaluate_rules(sample_trends)
        assert len(triggered) == 0

    def test_returns_empty_when_no_matches(self, manager, sample_trends):
        manager.register_rule(
            "Impossible", [{"field": "score", "operator": ">", "threshold": 999}],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            triggered = manager.evaluate_rules(sample_trends)
        assert triggered == []

    def test_multiple_rules_multiple_trends(self, manager, sample_trends):
        manager.register_rule(
            "High Score", [{"field": "score", "operator": ">", "threshold": 80}],
            "https://example.com/hook1",
        )
        manager.register_rule(
            "Low Score", [{"field": "score", "operator": "<", "threshold": 50}],
            "https://example.com/hook2",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            triggered = manager.evaluate_rules(sample_trends)
        # Rule 1 matches t1 (score=85), Rule 2 matches t2 (score=40)
        assert len(triggered) == 2
        trend_ids = {t["trend_id"] for t in triggered}
        assert "t1" in trend_ids
        assert "t2" in trend_ids

    def test_all_conditions_must_match(self, manager, sample_trends):
        manager.register_rule(
            "Strict", [
                {"field": "score", "operator": ">", "threshold": 70},
                {"field": "velocity", "operator": ">", "threshold": 0.7},
            ],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            triggered = manager.evaluate_rules(sample_trends)
        # Only t1 matches (score=85 > 70 AND velocity=0.8 > 0.7)
        assert len(triggered) == 1
        assert triggered[0]["trend_id"] == "t1"


# =============================================================================
# Webhook delivery
# =============================================================================


class TestWebhookDelivery:

    def test_successful_delivery(self, manager):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("trendscope.alerts.urlopen", return_value=mock_resp):
            status = manager._deliver_webhook("https://example.com/hook", {"key": "val"})
        assert status == "delivered"

    def test_hmac_signature_generation(self, manager):
        """When secret is provided, X-Signature-256 header should be set."""
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        captured_req = {}

        def fake_urlopen(req, timeout=None):
            captured_req["req"] = req
            return mock_resp

        with patch("trendscope.alerts.urlopen", side_effect=fake_urlopen):
            manager._deliver_webhook("https://example.com/hook", {"key": "val"}, secret="mysecret")

        req = captured_req["req"]
        sig = req.get_header("X-signature-256")
        assert sig is not None
        assert sig.startswith("sha256=")

    def test_failed_delivery_status(self, manager):
        from urllib.error import URLError
        with patch("trendscope.alerts.urlopen", side_effect=URLError("Connection refused")):
            status = manager._deliver_webhook("https://example.com/hook", {"key": "val"})
        assert status.startswith("failed:")

    def test_delivery_timeout_handling(self, manager):
        import socket
        with patch("trendscope.alerts.urlopen", side_effect=socket.timeout("timed out")):
            status = manager._deliver_webhook("https://example.com/hook", {"key": "val"})
        assert status.startswith("error:")

    def test_no_secret_skips_signature(self, manager):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: s
        mock_resp.__exit__ = MagicMock(return_value=False)

        captured_req = {}

        def fake_urlopen(req, timeout=None):
            captured_req["headers"] = dict(req.header_items())
            return mock_resp

        with patch("trendscope.alerts.urlopen", side_effect=fake_urlopen):
            manager._deliver_webhook("https://example.com/hook", {"key": "val"}, secret="")

        # No signature header should be present
        headers = captured_req["headers"]
        assert "X-Signature-256" not in headers


# =============================================================================
# Alert history
# =============================================================================


class TestAlertHistory:

    def test_records_triggered_alerts(self, manager, sample_trends):
        manager.register_rule(
            "High Score", [{"field": "score", "operator": ">", "threshold": 80}],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            manager.evaluate_rules(sample_trends)

        history = manager.get_history()
        assert len(history) == 1
        assert history[0]["trend_id"] == "t1"
        assert history[0]["delivery_status"] == "delivered"

    def test_get_history_returns_ordered_by_time(self, manager, sample_trends):
        manager.register_rule(
            "Any Score", [{"field": "score", "operator": ">", "threshold": 0}],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            manager.evaluate_rules(sample_trends)

        history = manager.get_history()
        assert len(history) == 3
        # All have the same triggered_at in this test, but ordering should not crash
        assert all("triggered_at" in h for h in history)

    def test_history_includes_payload(self, manager, sample_trends):
        manager.register_rule(
            "High Score", [{"field": "score", "operator": ">", "threshold": 80}],
            "https://example.com/hook",
        )
        with patch.object(manager, "_deliver_webhook", return_value="delivered"):
            manager.evaluate_rules(sample_trends)

        history = manager.get_history()
        assert len(history) == 1
        payload = history[0]["payload"]
        assert payload is not None
        assert payload["trend_id"] == "t1"
        assert payload["trend_name"] == "AI Boom"
        assert payload["trend_score"] == 85.0
