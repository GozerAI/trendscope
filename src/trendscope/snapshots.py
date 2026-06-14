"""Point-in-time state capture and comparison."""

import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional


@dataclass
class Snapshot:
    id: str
    label: str
    data: dict
    created_at: str


class SnapshotManager:
    def __init__(self, db):
        self.db = db
        self._init_tables()

    def _init_tables(self):
        with sqlite3.connect(self.db.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS snapshots (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    snapshot_data TEXT NOT NULL,
                    created_at TEXT DEFAULT (datetime('now'))
                )
            """)
            conn.commit()

    def create_snapshot(self, label: str) -> Snapshot:
        """Capture current state as a snapshot."""
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()

            # Get aggregate stats
            cursor.execute(
                "SELECT category, COUNT(*) as count, AVG(score) as avg_score "
                "FROM trends GROUP BY category"
            )
            categories = {}
            for row in cursor.fetchall():
                categories[row[0] or "uncategorized"] = {
                    "count": row[1],
                    "avg_score": round(row[2] or 0, 2),
                }

            cursor.execute("SELECT COUNT(*) FROM trends")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT status, COUNT(*) FROM trends GROUP BY status")
            statuses = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

            snapshot_data = {
                "total_trends": total,
                "by_category": categories,
                "by_status": statuses,
            }

            snap_id = str(uuid.uuid4())
            created_at = datetime.now(timezone.utc).isoformat()
            cursor.execute(
                "INSERT INTO snapshots (id, label, snapshot_data, created_at) "
                "VALUES (?, ?, ?, ?)",
                (snap_id, label, json.dumps(snapshot_data), created_at),
            )
            conn.commit()
            return Snapshot(
                id=snap_id, label=label, data=snapshot_data, created_at=created_at
            )

    def list_snapshots(self) -> list[Snapshot]:
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, label, snapshot_data, created_at "
                "FROM snapshots ORDER BY created_at DESC"
            )
            return [
                Snapshot(id=r[0], label=r[1], data=json.loads(r[2]), created_at=r[3])
                for r in cursor.fetchall()
            ]

    def get_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
        with sqlite3.connect(self.db.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, label, snapshot_data, created_at "
                "FROM snapshots WHERE id = ?",
                (snapshot_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return Snapshot(
                id=row[0], label=row[1], data=json.loads(row[2]), created_at=row[3]
            )

    def compare_snapshots(self, id1: str, id2: str) -> dict:
        s1 = self.get_snapshot(id1)
        s2 = self.get_snapshot(id2)
        if not s1 or not s2:
            return {"error": "Snapshot not found"}

        diff = {"additions": {}, "removals": {}, "changes": {}}
        d1, d2 = s1.data, s2.data

        all_keys = set(list(d1.keys()) + list(d2.keys()))
        for key in all_keys:
            if key not in d1:
                diff["additions"][key] = d2[key]
            elif key not in d2:
                diff["removals"][key] = d1[key]
            elif d1[key] != d2[key]:
                diff["changes"][key] = {"before": d1[key], "after": d2[key]}

        return {
            "snapshot_a": {
                "id": s1.id,
                "label": s1.label,
                "created_at": s1.created_at,
            },
            "snapshot_b": {
                "id": s2.id,
                "label": s2.label,
                "created_at": s2.created_at,
            },
            "diff": diff,
        }
