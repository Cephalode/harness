"""FastAPI dashboard server — WebSocket event streaming + REST API."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from dataclasses import asdict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from .config import load_config, validate_config
from .events import EventBus, HarnessEvent
from .models import CostTracker
from .orchestrator import Orchestrator
from .rate_limiter import ConcurrencyLimiter
from .task_queue import TaskQueue
from .session import Session
from .state import StateStore


class MessageRequest(BaseModel):
    message: str


class EventPayload(BaseModel):
    """Payload for incoming events from external processes (via DashboardRelay)."""
    type: str
    agent: str | None = None
    team: str | None = None
    data: dict[str, Any] = {}
    timestamp: float = 0.0


class AgentStatusTracker:
    """Tracks agent statuses derived from the event stream."""

    def __init__(self) -> None:
        self._statuses: dict[str, str] = {}

    def process_event(self, event: HarnessEvent) -> None:
        """Update status based on event type."""
        if not event.agent:
            return
        if event.type == "agent_start":
            self._statuses[event.agent] = "running"
        elif event.type == "agent_end":
            self._statuses[event.agent] = "done"
        elif event.type == "agent_error":
            self._statuses[event.agent] = "error"

    def get_status(self, agent_name: str) -> str:
        """Get the current status of an agent."""
        return self._statuses.get(agent_name, "idle")

    def get_all_statuses(self) -> dict[str, str]:
        """Get a copy of all agent statuses."""
        return dict(self._statuses)


class WorkerStatusEntry:
    """Latest status for a single worker."""
    def __init__(self):
        self.message: str = "Idle"
        self.timestamp: float = 0.0
        self.team: str | None = None
        self.task: str | None = None

    def to_dict(self, agent_name: str) -> dict:
        return {
            "agent": agent_name,
            "message": self.message,
            "timestamp": self.timestamp,
            "team": self.team,
            "task": self.task,
        }


class WorkerStatusTracker:
    """Tracks the latest status message from each worker."""
    def __init__(self):
        self._statuses: dict[str, WorkerStatusEntry] = {}

    def process_event(self, event: HarnessEvent) -> None:
        if not event.agent:
            return
        name = event.agent
        if name not in self._statuses:
            self._statuses[name] = WorkerStatusEntry()

        entry = self._statuses[name]
        entry.timestamp = event.timestamp

        if event.type == "worker_status":
            entry.message = event.data.get("message", "Working...")
            entry.team = event.team or entry.team
            entry.task = event.data.get("task", entry.task)
        elif event.type == "agent_start":
            entry.message = "Starting..."
            entry.team = event.team or entry.team
        elif event.type == "agent_end":
            status = event.data.get("status", "")
            if status == "success":
                entry.message = "Completed"
            else:
                entry.message = f"Finished ({status})"

    def get_all(self) -> list[dict]:
        return [entry.to_dict(name) for name, entry in self._statuses.items()]

    def get_all_dict(self) -> dict[str, dict]:
        return {name: entry.to_dict(name) for name, entry in self._statuses.items()}


def create_app(config_path: str = "configs/multi_team.yaml") -> FastAPI:
    app = FastAPI(title="Harness Dashboard")

    task_queue: TaskQueue | None = None

    @app.on_event("startup")
    async def on_startup():
        nonlocal task_queue
        await state_store.init()
        task_queue = TaskQueue(orchestrator, event_bus)
        await task_queue.start()
        app.state.task_queue = task_queue

    @app.on_event("shutdown")
    async def on_shutdown():
        if task_queue:
            await task_queue.stop()

    # State
    state_store = StateStore(state_dir=str(Path(config_path).parent.parent / "state"))
    # Ensure dirs exist synchronously (async init happens on first access)
    state_store.state_dir.mkdir(parents=True, exist_ok=True)
    (state_store.state_dir / "agents").mkdir(exist_ok=True)
    (state_store.state_dir / "stages").mkdir(exist_ok=True)
    (state_store.state_dir / "artifacts").mkdir(exist_ok=True)

    event_bus = EventBus(state_store=state_store)
    config = load_config(config_path)
    cost_tracker = CostTracker()
    rate_limiter = ConcurrencyLimiter()
    session = Session(sessions_dir=str(Path(config_path).parent.parent / "sessions"))
    orchestrator = Orchestrator(
        config=config,
        cost_tracker=cost_tracker,
        session=session,
        event_bus=event_bus,
        state_store=state_store,
        rate_limiter=rate_limiter,
    )
    status_tracker = AgentStatusTracker()
    worker_status_tracker = WorkerStatusTracker()

    @app.get("/api/teams")
    async def get_teams() -> dict[str, Any]:
        teams = []
        for name, team in orchestrator.teams.items():
            workers = []
            for wname, worker in team.workers.items():
                workers.append({
                    "name": wname,
                    "model": worker.model,
                    "vision": worker.config.vision,
                    "status": status_tracker.get_status(wname),
                })
            teams.append({
                "name": name,
                "color": team.color,
                "lead": {
                    "name": team.lead.name,
                    "model": team.lead.model,
                    "status": status_tracker.get_status(team.lead.name),
                },
                "workers": workers,
            })
        return {
            "orchestrator": {
                "name": orchestrator.agent.name,
                "model": orchestrator.agent.model,
                "status": status_tracker.get_status(orchestrator.agent.name),
            },
            "teams": teams,
        }

    @app.get("/api/costs")
    async def get_costs() -> dict[str, Any]:
        return {
            "total_cost": cost_tracker.total_cost,
            "total_usage": {
                "input_tokens": cost_tracker.total_usage.input_tokens,
                "output_tokens": cost_tracker.total_usage.output_tokens,
            },
            "by_agent": cost_tracker.cost_by_agent(),
            "by_team": cost_tracker.cost_by_team(),
        }

    @app.get("/api/session")
    async def get_session_info() -> dict[str, Any]:
        return {
            "session_id": session.session_id,
            "message_count": len(session.messages),
            "created_at": session.created_at,
        }

    @app.get("/api/history")
    async def get_history(since: float = 0.0) -> list[dict]:
        events = event_bus.get_history(since)
        return [json.loads(e.to_json()) for e in events]

    @app.post("/api/events")
    async def receive_event(payload: EventPayload) -> dict[str, Any]:
        """Receive an event from an external process (e.g. Discord orchestrator).

        This is the ingress point for the DashboardRelay. The event is injected
        into the local EventBus so it gets broadcast to all WebSocket clients.
        """
        ts = payload.timestamp if payload.timestamp > 0 else time.time()
        event = HarnessEvent(
            type=payload.type,
            agent=payload.agent,
            team=payload.team,
            data=payload.data,
            timestamp=ts,
        )
        # Update status tracker before emitting so status is ready when
        # WebSocket clients process the event.
        status_tracker.process_event(event)
        worker_status_tracker.process_event(event)
        event_bus.emit(event)
        return {"ok": True}

    @app.post("/api/events/batch")
    async def receive_events(payloads: list[EventPayload]) -> dict[str, Any]:
        """Receive a batch of events from an external process."""
        for payload in payloads:
            ts = payload.timestamp if payload.timestamp > 0 else time.time()
            event = HarnessEvent(
                type=payload.type,
                agent=payload.agent,
                team=payload.team,
                data=payload.data,
                timestamp=ts,
            )
            status_tracker.process_event(event)
            worker_status_tracker.process_event(event)
            event_bus.emit(event)
        return {"ok": True, "count": len(payloads)}

    @app.post("/api/message")
    async def send_message(req: MessageRequest) -> dict[str, Any]:
        """Enqueue a message for processing. Returns task_id immediately."""
        task_id = await task_queue.enqueue(req.message, platform="dashboard")
        return {"task_id": task_id, "status": "queued"}

    @app.get("/api/task/{task_id}")
    async def get_task_status(task_id: str) -> dict[str, Any]:
        """Get status/result of a specific task."""
        result = task_queue.get_result(task_id)
        if result is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": f"Task '{task_id}' not found"}, status_code=404)
        return result

    @app.get("/api/queue")
    async def get_queue_status() -> dict[str, Any]:
        """Get full queue status."""
        return task_queue.get_status()

    @app.get("/api/worker-statuses")
    async def get_worker_statuses() -> dict[str, Any]:
        return {"workers": worker_status_tracker.get_all()}

    @app.get("/api/rate-limits")
    async def get_rate_limits() -> dict[str, Any]:
        """Current per-model concurrency status from the rate limiter."""
        return {"models": rate_limiter.get_status()}

    # --- State API ---

    @app.get("/api/state")
    async def get_state() -> dict[str, Any]:
        """Full state snapshot."""
        return await state_store.snapshot()

    @app.get("/api/state/agents")
    async def get_state_agents() -> dict[str, Any]:
        agents = await state_store.get_agents()
        return {"agents": {name: asdict(a) for name, a in agents.items()}}

    @app.get("/api/state/agents/{name}")
    async def get_state_agent(name: str) -> dict[str, Any]:
        agent = await state_store.get_agent(name)
        if agent is None:
            from fastapi.responses import JSONResponse
            return JSONResponse({"error": f"Agent '{name}' not found"}, status_code=404)
        return asdict(agent)

    @app.get("/api/state/task")
    async def get_state_task() -> dict[str, Any]:
        task = await state_store.get_task()
        return {"task": asdict(task) if task else None}

    @app.get("/api/state/stages")
    async def get_state_stages() -> dict[str, Any]:
        stages = await state_store.get_stages()
        return {"stages": [asdict(s) for s in stages]}

    @app.get("/api/state/events")
    async def get_state_events(since: float = 0.0) -> dict[str, Any]:
        events = await state_store.get_events(since)
        return {"events": events}

    @app.post("/api/state/task")
    async def set_state_task(req: MessageRequest) -> dict[str, Any]:
        await state_store.set_task(req.message, platform="external")
        return {"ok": True}

    @app.post("/api/state/agents/{name}")
    async def set_state_agent(name: str, status: str = "running") -> dict[str, Any]:
        await state_store.set_agent_status(name, status)
        return {"ok": True}

    # --- SSE endpoint for real-time state streaming ---

    @app.get("/api/state/events/stream")
    async def state_event_stream():
        """SSE endpoint for real-time state streaming."""
        async def event_generator():
            queue = event_bus.subscribe()
            try:
                # Send initial snapshot
                snapshot = await state_store.snapshot()
                yield f"data: {json.dumps({'type': 'init', 'data': snapshot}, ensure_ascii=False)}\n\n"
                # Stream events
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=30)
                        yield f"data: {event.to_json()}\n\n"
                    except asyncio.TimeoutError:
                        yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
            except GeneratorExit:
                pass
            finally:
                event_bus.unsubscribe(queue)
        return StreamingResponse(event_generator(), media_type="text/event-stream")

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue = event_bus.subscribe()
        try:
            # Send team tree + current agent statuses on connect
            teams_data = await get_teams()
            await ws.send_json({
                "type": "init",
                "data": teams_data,
                "agent_statuses": status_tracker.get_all_statuses(),
                "worker_statuses": worker_status_tracker.get_all_dict(),
            })
            # Stream events
            while True:
                event = await queue.get()
                await ws.send_text(event.to_json())
        except WebSocketDisconnect:
            event_bus.unsubscribe(queue)

    # Serve React build (static files)
    static_dir = Path(__file__).parent.parent / "dashboard" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    # Store refs
    app.state.orchestrator = orchestrator
    app.state.event_bus = event_bus
    app.state.cost_tracker = cost_tracker
    app.state.rate_limiter = rate_limiter
    app.state.session = session
    app.state.status_tracker = status_tracker
    app.state.worker_status_tracker = worker_status_tracker
    app.state.state_store = state_store

    return app


def run_dashboard(
    config_path: str = "configs/multi_team.yaml",
    host: str = "localhost",
    port: int = 5173,
) -> None:
    """Run the dashboard server."""
    import uvicorn
    app = create_app(config_path)
    uvicorn.run(app, host=host, port=port)
