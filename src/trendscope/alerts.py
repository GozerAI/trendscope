"""Configurable alert system with webhook delivery."""

import hashlib
import hmac
import json
import logging
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger(__name__)


@dataclass
class AlertCondition:
    field: str  # e.g., "score", "velocity", "momentum"
    operator: str  # ">", "<", "==", ">=", "<="
    threshold: float
    category: Optional[str] = None  # Optional category filter


@dataclass
class AlertRule:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    conditions: list = field(default_factory=list)  # List of AlertCondition dicts
    webhook_url: str = ""
    webhook_secret: str = ""
    active: bool = True
    created_at: str = ""
    last_triggered_at: Optional[str] = None


OPERATORS = {
    ">": lambda a, b: a > b,
    "<": lambda a, b: a < b,
    "==": lambda a, b: a == b,
    ">=": lambda a, b: a >= b,
    "<=": lambda a, b: a <= b,
}


class AlertManager:
    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alerts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    conditions TEXT NOT NULL,
                    webhook_url TEXT NOT NULL,
                    webhook_secret TEXT DEFAULT '',
                    active INTEGER DEFAULT 1,
                    created_at TEXT NOT NULL,
                    last_triggered_at TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS alert_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    alert_id TEXT NOT NULL,
                    trend_id TEXT,
                    triggered_at TEXT NOT NULL,
                    delivery_status TEXT NOT NULL,
                    payload TEXT,
                    FOREIGN KEY (alert_id) REFERENCES alerts(id)
                )
            """)
            conn.commit()

    def register_rule(self, name, conditions, webhook_url, webhook_secret=""):
        """Register a new alert rule. Returns the AlertRule."""
        rule = AlertRule(
            name=name,
            conditions=conditions,
            webhook_url=webhook_url,
            webhook_secret=webhook_secret,
            created_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(
                "INSERT INTO alerts (id, name, conditions, webhook_url, webhook_secret, active, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (rule.id, rule.name, json.dumps(conditions), rule.webhook_url, rule.webhook_secret, 1, rule.created_at),
            )
            conn.commit()
        return rule

    def get_rules(self):
        """Get all alert rules."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute("SELECT id, name, conditions, webhook_url, webhook_secret, active, created_at, last_triggered_at FROM alerts")
            rules = []
            for row in cursor.fetchall():
                rules.append(AlertRule(
                    id=row[0], name=row[1], conditions=json.loads(row[2]),
                    webhook_url=row[3], webhook_secret=row[4],
                    active=bool(row[5]), created_at=row[6], last_triggered_at=row[7],
                ))
            return rules

    def delete_rule(self, rule_id):
        """Delete an alert rule. Returns True if deleted."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute("DELETE FROM alerts WHERE id = ?", (rule_id,))
            conn.commit()
            return cursor.rowcount > 0

    def get_history(self, limit=50):
        """Get alert trigger history."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.execute(
                "SELECT id, alert_id, trend_id, triggered_at, delivery_status, payload FROM alert_history ORDER BY triggered_at DESC LIMIT ?",
                (limit,),
            )
            return [
                {"id": r[0], "alert_id": r[1], "trend_id": r[2], "triggered_at": r[3], "delivery_status": r[4], "payload": json.loads(r[5]) if r[5] else None}
                for r in cursor.fetchall()
            ]

    def evaluate_rules(self, trends):
        """Evaluate all active rules against trends. Returns list of triggered alerts."""
        rules = self.get_rules()
        triggered = []
        for rule in rules:
            if not rule.active:
                continue
            for trend in trends:
                if self._check_conditions(rule.conditions, trend):
                    result = self._trigger_alert(rule, trend)
                    triggered.append(result)
        return triggered

    ALLOWED_ALERT_FIELDS = {"score", "volume", "sentiment", "momentum", "category", "source", "velocity"}

    def _check_conditions(self, conditions, trend):
        """Check if all conditions match a trend."""
        for cond in conditions:
            # Category filter
            if cond.get("category") and trend.category.name != cond["category"]:
                return False

            field_name = cond.get("field", "")
            op = cond.get("operator", "")
            threshold = cond.get("threshold", 0)

            if field_name not in self.ALLOWED_ALERT_FIELDS:
                logger.warning("Invalid alert field: %s", field_name)
                return False

            value = getattr(trend, field_name, None)
            if value is None:
                return False

            op_fn = OPERATORS.get(op)
            if not op_fn:
                return False

            if not op_fn(value, threshold):
                return False
        return True

    def _trigger_alert(self, rule, trend):
        """Trigger an alert: deliver webhook and record history."""
        payload = {
            "alert_id": rule.id,
            "alert_name": rule.name,
            "trend_id": trend.id,
            "trend_name": trend.name,
            "trend_score": trend.score,
            "trend_velocity": trend.velocity,
            "triggered_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }

        delivery_status = self._deliver_webhook(rule.webhook_url, payload, rule.webhook_secret)

        # Record history
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute(
                "INSERT INTO alert_history (alert_id, trend_id, triggered_at, delivery_status, payload) VALUES (?, ?, ?, ?, ?)",
                (rule.id, trend.id, payload["triggered_at"], delivery_status, json.dumps(payload)),
            )
            # Update last_triggered_at
            conn.execute(
                "UPDATE alerts SET last_triggered_at = ? WHERE id = ?",
                (payload["triggered_at"], rule.id),
            )
            conn.commit()

        return {"alert_id": rule.id, "trend_id": trend.id, "delivery_status": delivery_status, "payload": payload}

    def _deliver_webhook(self, url, payload, secret=""):
        """Deliver webhook with optional HMAC signing. Returns delivery status."""
        # Validate URL to prevent SSRF
        from urllib.parse import urlparse
        import socket
        import ipaddress as _ipaddress
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https") or not parsed.hostname:
                return "failed:invalid_url"
            ip = socket.gethostbyname(parsed.hostname)
            addr = _ipaddress.ip_address(ip)
            if addr.is_private or addr.is_loopback or addr.is_link_local:
                return "failed:private_url"
        except Exception:
            return "failed:url_validation"
        try:
            body = json.dumps(payload).encode("utf-8")
            req = Request(url, data=body, headers={"Content-Type": "application/json"})

            if secret:
                signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
                req.add_header("X-Signature-256", f"sha256={signature}")

            with urlopen(req, timeout=10) as resp:
                return "delivered" if resp.status < 400 else f"failed:{resp.status}"
        except URLError as e:
            logger.warning(f"Webhook delivery failed: {e}")
            return f"failed:{e}"
        except Exception as e:
            logger.warning(f"Webhook delivery error: {e}")
            return f"error:{e}"
