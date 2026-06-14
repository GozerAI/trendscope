"""Real-time intelligence feed using internal deque."""

import json
import uuid
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Optional

try:
    from gozerai_telemetry.metrics import get_collector
    _collector = get_collector("trendscope")
    _feed_counter = _collector.counter("feed_events_total", "Total feed events pushed")
except ImportError:
    _feed_counter = None


class IntelligenceFeed:
    def __init__(self, maxlen: int = 500):
        self._events: deque = deque(maxlen=maxlen)

    def push_event(self, event_type: str, data: dict) -> dict:
        event = {
            "id": str(uuid.uuid4()),
            "type": event_type,
            "data": data,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        self._events.append(event)
        if _feed_counter:
            _feed_counter.inc(type=event_type)
        return event

    def get_recent(self, minutes: int = 5) -> list[dict]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        cutoff_str = cutoff.isoformat()
        return [e for e in self._events if e["timestamp"] >= cutoff_str]

    def get_all(self) -> list[dict]:
        """Return all events in the feed."""
        return list(self._events)

    def get_summary(self, minutes: int = 5) -> dict:
        recent = self.get_recent(minutes)
        type_counts: dict[str, int] = {}
        for e in recent:
            t = e["type"]
            type_counts[t] = type_counts.get(t, 0) + 1
        return {
            "total": len(recent),
            "by_type": type_counts,
            "window_minutes": minutes,
        }

    async def stream(
        self, types: Optional[list[str]] = None
    ):
        """Async generator for SSE streaming."""
        import asyncio

        last_idx = len(self._events)
        while True:
            current = list(self._events)
            new_events = current[last_idx:] if last_idx < len(current) else []
            for event in new_events:
                if types and event["type"] not in types:
                    continue
                yield f"data: {json.dumps(event)}\n\n"
            last_idx = len(current)
            await asyncio.sleep(1)
