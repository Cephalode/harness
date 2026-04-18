# Web Dashboard Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Build a real-time web dashboard for the multi-team agentic harness — a dark-themed React UI with a live agent tree sidebar, streaming activity feed, system diagram, and cost metrics.

**Architecture:** Python FastAPI backend with WebSocket for real-time event streaming. React + Vite frontend with dark theme. The backend hooks into the existing `Session` and `Orchestrator` classes via an event bus that emits structured events (agent_start, agent_output, agent_end, team_done, etc.) which are forwarded to connected browser clients.

**Tech Stack:**
- Backend: FastAPI + uvicorn + websockets (Python)
- Frontend: React 18 + Vite + TypeScript (served as static build by FastAPI)
- Styling: Tailwind CSS (dark theme)
- State: Zustand (lightweight React state store)
- Diagram: React Flow (node-based system diagram)
- Icons: Lucide React

---

## UI Layout (from video analysis)

```
┌─────────────────────────────────────────────────────────┐
│ [☰] Workspace / Brand / App          Ctrl+S  [S][M][L] │  ← Breadcrumb
├──────────────┬──────────────────────────────────────────┤
│              │                                          │
│  Agent Tree  │          Main Content Area               │
│              │                                          │
│  ● You       │   [System Diagram] or [Activity Feed]    │
│  ● Orch      │                                          │
│    ● Setup L │   Nodes connected by lines showing       │
│      ○ Scaf  │   agent relationships and data flow      │
│    ● Brand L │                                          │
│      ○ Analyst│  Live streaming agent messages with      │
│    ● UGen A  │  timestamps, delegation chains           │
│    ● UGen B  │                                          │
│    ● Val L   │                                          │
│      ○ QA    │                                          │
│      ○ Sec   │                                          │
│              │                                          │
├──────────────┴──────────────────────────────────────────┤
│ Session: abc123  Duration: 7m 06s  Cost: $0.0042       │  ← Status bar
│ TillDone: Generation [3/8]   Tokens: 12K in / 4K out   │
└─────────────────────────────────────────────────────────┘
```

### Key Panels
1. **Left Sidebar** — Collapsible tree of agent hierarchy (orchestrator → leads → workers). Each node shows status (idle/running/done/error), cost, and model.
2. **Main Area** — Two views (tab-switchable):
   - **Activity Feed** — Live streaming messages between agents with timestamps, role badges, delegation indicators
   - **System Diagram** — React Flow canvas showing agent nodes connected by delegation edges
3. **Bottom Status Bar** — Session ID, duration, total cost, token usage, till-done progress
4. **Top Bar** — Breadcrumb navigation (future: multi-workspace), size controls, input field to send messages to orchestrator

---

## Task Breakdown

### Task 1: Event Bus — Structured Events + Async Queue

**Objective:** Create an event bus that the existing harness code emits events into, and WebSocket clients subscribe to.

**Files:**
- Create: `harness/events.py`

**Implementation:**

```python
"""Event bus for real-time dashboard streaming."""
from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Awaitable


@dataclass
class HarnessEvent:
    """A single event emitted by the harness."""
    type: str  # "agent_start", "agent_output", "agent_end", "team_start", "team_done", "session_start", "session_end", "cost_update", "routing"
    agent: str | None = None
    team: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_json(self) -> str:
        return json.dumps({
            "type": self.type,
            "agent": self.agent,
            "team": self.team,
            "data": self.data,
            "timestamp": self.timestamp,
        }, ensure_ascii=False)


class EventBus:
    """Async event bus — multiple subscribers receive all events."""

    def __init__(self) -> None:
        self._subscribers: list[asyncio.Queue[HarnessEvent]] = []
        self._history: list[HarnessEvent] = []
        self._max_history = 1000

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
            self._history = self._history[-self._max_history:]
        for q in self._subscribers:
            q.put_nowait(event)

    def get_history(self, since: float = 0.0) -> list[HarnessEvent]:
        """Get events since a timestamp."""
        return [e for e in self._history if e.timestamp > since]

    def get_team_tree(self) -> dict[str, Any]:
        """Override point — dashboard server will populate from orchestrator."""
        return {}
```

**Verification:** `cd ~/devel/harness && .venv/bin/python -c "from harness.events import EventBus, HarnessEvent; e = HarnessEvent('test', agent='bob'); print(e.to_json())"`

**Commit:** `feat: add event bus for real-time dashboard streaming`

---

### Task 2: Instrument Orchestrator + Agent + Team to Emit Events

**Objective:** Hook the event bus into the existing `Orchestrator`, `Agent`, and `Team` classes so every action emits structured events.

**Files:**
- Modify: `harness/orchestrator.py` — accept optional `EventBus`, emit routing/start/end events
- Modify: `harness/agent.py` — emit agent_start, agent_output, agent_end events around `_execute_pi`
- Modify: `harness/team.py` — emit team_start, delegation, team_done events
- Modify: `harness/config.py` — add `event_bus` param to `Orchestrator.__init__` signature

**Key changes to `orchestrator.py`:**
- Add `event_bus: EventBus | None = None` to `__init__`, store as `self.event_bus`
- In `process_message()`:
  - Emit `session_start` when user message arrives
  - Emit `routing` when teams are selected
  - Emit `session_end` after synthesis
- Pass `event_bus` through to `Team` and `Agent`

**Key changes to `agent.py`:**
- Add `event_bus` parameter to `Agent.__init__`
- In `run()`: emit `agent_start` before execution, `agent_end` after
- In `_execute_pi()`: emit `agent_output` with streaming chunks (if available from pi output)

**Key changes to `team.py`:**
- Add `event_bus` parameter to `Team.__init__`, pass to agents
- In `execute()`: emit `team_start`, delegation events per worker, `team_done` at end

**All event_bus.emit() calls must be guarded:**
```python
if self.event_bus:
    self.event_bus.emit(HarnessEvent(...))
```

**Verification:** Run CLI, confirm no import errors. Events will be visible once the dashboard connects.

**Commit:** `feat: instrument orchestrator, agent, and team with event bus`

---

### Task 3: FastAPI WebSocket Server

**Objective:** Create a FastAPI server that serves the React dashboard and streams events via WebSocket.

**Files:**
- Create: `harness/dashboard.py`

**Implementation outline:**

```python
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

from .config import load_config, validate_config
from .events import EventBus, HarnessEvent
from .models import CostTracker
from .orchestrator import Orchestrator
from .session import Session


def create_app(config_path: str = "configs/multi_team.yaml") -> FastAPI:
    app = FastAPI(title="Harness Dashboard")

    # State — shared across connections
    event_bus = EventBus()
    config = load_config(config_path)
    warnings = validate_config(config)
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
        """Return team hierarchy for sidebar tree."""
        teams = []
        for name, team in orchestrator.teams.items():
            workers = []
            for wname, worker in team.workers.items():
                workers.append({
                    "name": wname,
                    "model": worker.model,
                    "vision": worker.config.vision,
                    "status": "idle",  # Will be updated by events
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
    async def get_session() -> dict[str, Any]:
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
    async def send_message(message: str) -> dict[str, Any]:
        """Send a message to the orchestrator."""
        result = await orchestrator.process_message(message)
        return {"response": result}

    @app.websocket("/ws")
    async def websocket_endpoint(ws: WebSocket) -> None:
        await ws.accept()
        queue = event_bus.subscribe()
        try:
            # Send team tree on connect
            await ws.send_json({"type": "init", "teams": (await get_teams())})
            # Stream events
            while True:
                event = await queue.get()
                await ws.send_text(event.to_json())
        except WebSocketDisconnect:
            event_bus.unsubscribe(queue)

    # Serve React build (static files) — will exist after Task 5
    static_dir = Path(__file__).parent.parent / "dashboard" / "dist"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    # Store refs for external access
    app.state.orchestrator = orchestrator
    app.state.event_bus = event_bus
    app.state.cost_tracker = cost_tracker
    app.state.session = session

    return app


def run_dashboard(config_path: str = "configs/multi_team.yaml", host: str = "localhost", port: int = 5173) -> None:
    """Run the dashboard server."""
    import uvicorn
    app = create_app(config_path)
    uvicorn.run(app, host=host, port=port)
```

**Verification:** `.venv/bin/python -c "from harness.dashboard import create_app; app = create_app(); print('OK')"` (will need `uv pip install fastapi uvicorn`)

**Commit:** `feat: add FastAPI dashboard server with WebSocket streaming`

---

### Task 4: Dashboard CLI Entry Point + Install Dependencies

**Objective:** Add `dashboard` command to the CLI and install web dependencies.

**Files:**
- Modify: `harness/cli.py` — add `/dashboard` slash command
- Modify: `harness/__main__.py` — add `--dashboard` flag
- Modify: `requirements.txt` — add `fastapi>=0.110`, `uvicorn[standard]>=0.29`, `websockets>=12.0`

**CLI changes:**
- In `_handle_command()`: add `/dashboard` handler that starts the FastAPI server in a thread
- In `__main__.py`: add `--dashboard` flag that launches the dashboard directly
- The dashboard opens a browser tab automatically

**Verification:** `cd ~/devel/harness && .venv/bin/python -m harness --dashboard --config configs/multi_team.yaml` (server starts, browser may open)

**Commit:** `feat: add dashboard CLI entry point with dependencies`

---

### Task 5: React Frontend — Project Scaffold + Dark Theme Layout

**Objective:** Create the React + Vite + TypeScript frontend with the dark-themed layout matching the video.

**Files:**
- Create: `dashboard/` directory with full Vite + React + TypeScript project
- Key files: `dashboard/package.json`, `dashboard/vite.config.ts`, `dashboard/tsconfig.json`, `dashboard/index.html`
- Create: `dashboard/src/App.tsx` — main layout (sidebar + main + status bar)
- Create: `dashboard/src/index.css` — Tailwind dark theme
- Create: `dashboard/src/components/Sidebar.tsx` — agent tree sidebar
- Create: `dashboard/src/components/ActivityFeed.tsx` — streaming message feed
- Create: `dashboard/src/components/SystemDiagram.tsx` — React Flow diagram
- Create: `dashboard/src/components/StatusBar.tsx` — bottom status bar
- Create: `dashboard/src/components/MessageInput.tsx` — input field to send messages
- Create: `dashboard/src/hooks/useWebSocket.ts` — WebSocket connection hook
- Create: `dashboard/src/store.ts` — Zustand state store

**Component tree:**
```
App
├── Sidebar (collapsible agent tree)
│   ├── AgentNode (recursive — orchestrator → leads → workers)
│   └── Status indicators (running/idle/error/done)
├── MainArea
│   ├── TabSwitcher (Activity | Diagram)
│   ├── ActivityFeed
│   │   └── MessageBubble (per event — role badge, timestamp, content)
│   └── SystemDiagram
│       └── React Flow canvas with agent nodes + delegation edges
├── StatusBar (session, cost, tokens, duration)
└── MessageInput (text field + send button)
```

**Color scheme (dark):**
- Background: `#0f0f0f` (near black)
- Sidebar: `#1a1a2e`
- Cards/panels: `#16213e`
- Borders: `#2a2a4a`
- Accent: `#0f3460` (blue), `#e94560` (red for errors)
- Text: `#e0e0e0` (primary), `#888` (dim)
- Status colors: `#4ade80` (running), `#fbbf24` (idle), `#ef4444` (error), `#60a5fa` (done)

**Verification:** `cd ~/devel/harness/dashboard && npm install && npm run dev` — Vite dev server starts at localhost:5173 with dark layout visible.

**Commit:** `feat: add React frontend scaffold with dark-themed layout`

---

### Task 6: WebSocket Hook + Zustand Store + Real-Time Data Flow

**Objective:** Wire the frontend to the backend via WebSocket, populate the agent tree sidebar and activity feed with live events.

**Files:**
- Modify: `dashboard/src/hooks/useWebSocket.ts` — connect to `/ws`, parse events, dispatch to store
- Modify: `dashboard/src/store.ts` — Zustand store with:
  - `teams` (from init event)
  - `events` (accumulated from stream)
  - `agentStatuses` (map of agent → idle/running/done/error)
  - `costs` (from cost_update events)
  - `session` info
- Modify: `dashboard/src/components/Sidebar.tsx` — render agent tree from store, show live status badges
- Modify: `dashboard/src/components/ActivityFeed.tsx` — render events as they stream in, auto-scroll

**Event flow:**
```
Backend EventBus → WebSocket → useWebSocket hook → Zustand store → React components
```

**Agent status tracking:**
- `agent_start` → set status to "running" (pulsing green dot)
- `agent_end` → set status to "done" (blue dot) or "error" (red dot) based on result
- `agent_output` → append to activity feed

**Verification:** Start backend + frontend, send a message via input, watch agent tree nodes turn green/blue as agents run.

**Commit:** `feat: wire WebSocket to Zustand store for real-time dashboard updates`

---

### Task 7: System Diagram with React Flow

**Objective:** Add the node-based system diagram view showing agent relationships and delegation flow.

**Files:**
- Modify: `dashboard/src/components/SystemDiagram.tsx` — React Flow canvas
- The diagram reads from `store.teams` and creates:
  - Orchestrator node (top center)
  - Team lead nodes (middle row)
  - Worker nodes (bottom row, grouped under their lead)
  - Edges: orchestrator → leads, leads → workers (with animated flow)

**Node design:**
- Dark rounded rectangles with agent name, model badge, status indicator
- Edges: thin white/gray lines, animated when delegation is active
- Orchestrator gets a special larger node with glow effect

**Verification:** Switch to "Diagram" tab, see the full agent hierarchy rendered as a flowchart.

**Commit:** `feat: add React Flow system diagram view`

---

### Task 8: Build Pipeline + Static Serving Integration

**Objective:** Configure the React build so that `npm run build` outputs to `dashboard/dist/`, and FastAPI serves these static files in production mode.

**Files:**
- Modify: `dashboard/vite.config.ts` — set `base: '/'`, output to `dist/`
- Modify: `harness/dashboard.py` — ensure static file mounting works for built assets
- Add: `Makefile` or scripts in `package.json` for build commands

**Build commands:**
```bash
cd dashboard && npm run build   # outputs to dashboard/dist/
cd .. && python -m harness --dashboard  # serves from dashboard/dist/
```

**Verification:** Run `npm run build` then `python -m harness --dashboard` — browser shows the dashboard without Vite dev server.

**Commit:** `feat: integrate React build with FastAPI static serving`

---

## Dependencies to Install

```bash
# Python (backend)
.venv/bin/pip install fastapi uvicorn[standard] websockets

# Node.js (frontend) — requires Node 18+
cd dashboard && npm install
```

## Execution Order

Tasks 1-2 are sequential (events module must exist before instrumenting).
Task 3 depends on Tasks 1-2.
Task 4 depends on Task 3.
Tasks 5-7 can partially overlap (5 must be first for 6-7).
Task 8 depends on Tasks 3 + 5.

```
Wave 1: [Task 1]
Wave 2: [Task 2] (depends on Task 1)
Wave 3: [Task 3 + Task 5] (backend server || frontend scaffold — parallel)
Wave 4: [Task 4 + Task 6] (CLI wiring || real-time data — parallel, Task 4 needs Task 3, Task 6 needs Task 5)
Wave 5: [Task 7] (system diagram)
Wave 6: [Task 8] (build integration)
```

## Notes

- The dashboard runs alongside the existing CLI — they share the same `Orchestrator` instance
- For development, run FastAPI backend and Vite dev server separately (Vite proxies API/WebSocket to FastAPI)
- The video shows a separate "Infinite UI" product built by agents — our dashboard is the harness monitoring UI, not that product
- No authentication needed — this is a local dev tool (localhost only)
