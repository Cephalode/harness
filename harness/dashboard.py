"""FastAPI dashboard server — WebSocket event streaming + REST API."""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import load_config, validate_config
from .events import EventBus, HarnessEvent
from .models import CostTracker
from .orchestrator import Orchestrator
from .session import Session


class MessageRequest(BaseModel):
    message: str


def create_app(config_path: str = "configs/multi_team.yaml") -> FastAPI:
    app = FastAPI(title="Harness Dashboard")

    # State
    event_bus = EventBus()
    config = load_config(config_path)
    cost_tracker = CostTracker()
    session = Session(sessions_dir=str(Path(config_path).parent.parent / "sessions"))
    orchestrator = Orchestrator(
        config=config,
        cost_tracker=cost_tracker,
        session=session,
        event_bus=event_bus,
    )

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
                    "status": "idle",
                })
            teams.append({
                "name": name,
                "color": team.color,
                "lead": {"name": team.lead.name, "model": team.lead.model},
                "workers": workers,
            })
        return {
            "orchestrator": {"name": orchestrator.agent.name, "model": orchestrator.agent.model},
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

    @app.post("/api/message")
    async def send_message(req: MessageRequest) -> dict[str, Any]:
        result = await orchestrator.process_message(req.message)
        return {"response": result}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue = event_bus.subscribe()
        try:
            # Send team tree on connect
            teams_data = await get_teams()
            await ws.send_json({"type": "init", "data": teams_data})
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
    app.state.session = session

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
