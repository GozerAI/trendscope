"""Scheduled automation engine using threading.Timer with rearm."""

import sqlite3
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

try:
    from gozerai_telemetry.metrics import get_collector
    _collector = get_collector("trendscope")
    _scheduler_counter = _collector.counter("scheduler_runs_total", "Total scheduler runs")
except ImportError:
    _scheduler_counter = None


@dataclass
class ScheduleEntry:
    name: str
    interval_minutes: float
    callback: Callable
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    run_count: int = 0
    last_status: str = "pending"
    last_error: Optional[str] = None


class TrendScheduler:
    def __init__(self):
        self._schedules: dict[str, ScheduleEntry] = {}
        self._timers: dict[str, threading.Timer] = {}
        self._running: set[str] = set()  # concurrent-run protection
        self._started = False
        self._lock = threading.Lock()

    def register(self, name: str, interval_minutes: float, callback: Callable):
        """Register a named schedule."""
        self._schedules[name] = ScheduleEntry(
            name=name, interval_minutes=interval_minutes, callback=callback
        )

    def start(self):
        """Start all enabled schedules."""
        self._started = True
        for name, entry in self._schedules.items():
            if entry.enabled:
                self._arm_timer(name)

    def stop(self):
        """Stop all timers."""
        self._started = False
        for timer in self._timers.values():
            timer.cancel()
        self._timers.clear()

    def list_schedules(self) -> list[dict]:
        """Return all schedules as dicts."""
        return [
            {
                "name": e.name,
                "interval_minutes": e.interval_minutes,
                "enabled": e.enabled,
                "last_run": e.last_run.isoformat() if e.last_run else None,
                "run_count": e.run_count,
                "last_status": e.last_status,
                "last_error": e.last_error,
            }
            for e in self._schedules.values()
        ]

    def run_now(self, name: str) -> dict:
        """Execute a schedule immediately. Returns status dict."""
        if name not in self._schedules:
            return {"status": "error", "error": f"Schedule {name} not found"}
        with self._lock:
            if name in self._running:
                return {"status": "skipped", "reason": "already running"}
            self._running.add(name)
        try:
            entry = self._schedules[name]
            entry.callback()
            entry.last_run = datetime.now(timezone.utc)
            entry.run_count += 1
            entry.last_status = "success"
            entry.last_error = None
            if _scheduler_counter:
                _scheduler_counter.inc(name=name, status="success")
            return {"status": "success", "run_count": entry.run_count}
        except Exception as e:
            entry = self._schedules[name]
            entry.last_status = "error"
            entry.last_error = str(e)
            if _scheduler_counter:
                _scheduler_counter.inc(name=name, status="error")
            return {"status": "error", "error": str(e)}
        finally:
            with self._lock:
                self._running.discard(name)

    def enable(self, name: str):
        if name in self._schedules:
            self._schedules[name].enabled = True
            if self._started:
                self._arm_timer(name)

    def disable(self, name: str):
        if name in self._schedules:
            self._schedules[name].enabled = False
            if name in self._timers:
                self._timers[name].cancel()
                del self._timers[name]

    def get_schedule(self, name: str) -> Optional[ScheduleEntry]:
        """Get a schedule entry by name."""
        return self._schedules.get(name)

    def _arm_timer(self, name: str):
        entry = self._schedules[name]
        interval_sec = entry.interval_minutes * 60
        timer = threading.Timer(interval_sec, self._execute_and_rearm, args=(name,))
        timer.daemon = True
        self._timers[name] = timer
        timer.start()

    def _execute_and_rearm(self, name: str):
        if not self._started or name not in self._schedules:
            return
        self.run_now(name)
        if self._started and self._schedules.get(name) and self._schedules[name].enabled:
            self._arm_timer(name)
