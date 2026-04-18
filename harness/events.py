"""Event bus for real-time dashboard streaming."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any


@dataclass
class HarnessEvent:
    """A single event emitted by the harness."""

    type: str  # "agent_start", "agent_output", "agent_end", "team_start", "team_done", "session_start", "session_end", "cost_update", "routing"
    agent: str | None = None
    team: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        """Serialize to JSON string."""
        return json.dumps(
            {
                "type": self.type,
                "agent": self.agent,
                "team": self.team,
                "data": self.data,
                "timestamp": self.timestamp,
            },
            ensure_ascii=False,
        )


class EventBus:
    """Async event bus — multiple subscribers receive all events."""

    def __init__(self, max_history: int = 1000) -> None:
        self._subscribers: list[asyncio.Queue[HarnessEvent]] = []
        self._history: list[HarnessEvent] = []
        self._max_history = max_history

    def subscribe(self) -> asyncio.Queue[HarnessEvent]:
        """Create a new subscriber queue."""
        q: asyncio.Queue[HarnessEvent] = asyncio.Queue()
        self._subscribers.append(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[HarnessEvent]) -> None:
        """Remove a subscriber queue."""
        if q in self._subscribers:
            self._subscribers.remove(q)

    def emit(self, event: HarnessEvent) -> None:
        """Emit an event to all subscribers (non-blocking)."""
        self._history.append(event)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history :]
        for q in self._subscribers:
            q.put_nowait(event)

    def get_history(self, since: float = 0.0) -> list[HarnessEvent]:
        """Get events since a timestamp."""
        return [e for e in self._history if e.timestamp > since]

    def get_team_tree(self) -> dict[str, Any]:
        """Override point — dashboard server will populate from orchestrator."""
        return {}
