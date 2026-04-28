"""Event bus for real-time dashboard streaming."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .state import StateStore

logger = logging.getLogger(__name__)


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

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> HarnessEvent:
        """Deserialize a dict into a HarnessEvent."""
        return cls(
            type=data.get("type", "unknown"),
            agent=data.get("agent"),
            team=data.get("team"),
            data=data.get("data", {}),
            timestamp=data.get("timestamp", time.time()),
        )


class EventBus:
    """Async event bus — multiple subscribers receive all events."""

    def __init__(self, max_history: int = 1000, state_store: StateStore | None = None) -> None:
        self._subscribers: list[asyncio.Queue[HarnessEvent]] = []
        self._history: list[HarnessEvent] = []
        self._max_history = max_history
        self._state_store = state_store

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
        if self._state_store is not None:
            self._state_store.process_event(event)

    def get_history(self, since: float = 0.0) -> list[HarnessEvent]:
        """Get events since a timestamp."""
        return [e for e in self._history if e.timestamp > since]

    def get_team_tree(self) -> dict[str, Any]:
        """Override point — dashboard server will populate from orchestrator."""
        return {}


class DashboardRelay:
    """Forwards events from a local EventBus to the dashboard server via HTTP.

    Non-blocking: uses httpx async client. Fails gracefully if the dashboard
    is not running (logs a warning once, then suppresses further errors).
    """

    def __init__(
        self,
        event_bus: EventBus,
        dashboard_url: str = "http://localhost:5173",
    ) -> None:
        self._event_bus = event_bus
        self._dashboard_url = dashboard_url.rstrip("/")
        self._queue: asyncio.Queue[HarnessEvent] | None = None
        self._task: asyncio.Task | None = None
        self._suppress_errors = False

    async def start(self) -> None:
        """Subscribe to the event bus and start the relay loop."""
        import httpx

        self._client = httpx.AsyncClient(timeout=2.0)
        self._queue = self._event_bus.subscribe()
        self._task = asyncio.create_task(self._relay_loop())
        logger.info("DashboardRelay started → %s", self._dashboard_url)

    async def stop(self) -> None:
        """Stop the relay and clean up."""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._queue:
            self._event_bus.unsubscribe(self._queue)
            self._queue = None
        if hasattr(self, "_client") and self._client:
            await self._client.aclose()
        logger.info("DashboardRelay stopped")

    async def _relay_loop(self) -> None:
        """Background loop: forward events to the dashboard server."""
        while True:
            try:
                event = await self._queue.get()  # type: ignore[union-attr]
                await self._send_event(event)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                if not self._suppress_errors:
                    logger.warning(
                        "DashboardRelay error (suppressing further warnings): %s", exc
                    )
                    self._suppress_errors = True

    async def _send_event(self, event: HarnessEvent) -> None:
        """POST a single event to the dashboard server."""
        try:
            resp = await self._client.post(
                f"{self._dashboard_url}/api/events",
                json={
                    "type": event.type,
                    "agent": event.agent,
                    "team": event.team,
                    "data": event.data,
                    "timestamp": event.timestamp,
                },
            )
            if resp.status_code == 200:
                self._suppress_errors = False
            else:
                if not self._suppress_errors:
                    logger.warning(
                        "Dashboard returned %s for event relay", resp.status_code
                    )
                    self._suppress_errors = True
        except Exception as exc:
            if not self._suppress_errors:
                logger.warning(
                    "DashboardRelay connection failed (dashboard likely not running): %s",
                    exc,
                )
                self._suppress_errors = True
