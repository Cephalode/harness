# Central State Store + State API Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Implement a persistent Central State Store + REST/SSE State API that enables cross-platform state synchronization for the Harness multi-agent orchestration system.

**Architecture:** Three-layer design — (1) file-based StateStore with JSON persistence, (2) State API (FastAPI routes integrated into existing dashboard.py) with SSE endpoint, (3) integration hooks into existing orchestrator/agent/team/session code to emit state mutations to the store.

**Tech Stack:** Python 3.11+, FastAPI, pydantic, asyncio, aiofiles (already in deps), SSE via `starlette.responses.StreamingResponse`

---

## Current State (What Already Exists)

- **EventBus** (`events.py`): In-memory async pub/sub with history — events are ephemeral, lost on restart
- **Dashboard** (`dashboard.py`): FastAPI with REST endpoints + WebSocket — creates its own orchestrator instance, not shared with CLI
- **Session** (`session.py`): JSONL conversation logging — persisted but only for conversation, not general state
- **DashboardRelay** (`events.py`): HTTP relay from CLI process to dashboard server — one-way, fire-and-forget
- **AgentStatusTracker / WorkerStatusTracker** (`dashboard.py`): In-memory status tracking derived from events

## Key Insight

The current system has **two separate worlds**:
1. **CLI mode** — runs Orchestrator in-process, uses EventBus + DashboardRelay to forward events to dashboard
2. **Dashboard mode** — creates its OWN Orchestrator, has its own EventBus

Neither mode persists state to disk. The StateStore will be the shared persistent layer that both modes read/write to.

---

## Implementation Tasks

### Task 1: Create StateStore module (`harness/state.py`)

**Objective:** File-based persistent state store that serves as the single source of truth for harness runtime state.

**Files:**
- Create: `harness/state.py`

**State Structure:**
```python
state/
├── active_task.json       # Current task being processed
├── agents/                # Per-agent state files
│   └── {agent_name}.json  # status, model, team, last_output
├── stages/                # Per-stage/round state
│   └── {stage_id}.json    # team, round, workers, results
├── artifacts/             # Stage output artifacts
│   └── {stage_id}/
├── messages.jsonl         # Append-only event log (like session but for state changes)
└── meta.json              # session_id, created_at, last_updated, platform (who owns this session)
```

**Implementation:**
- `StateStore` class with async methods: `init()`, `get_state()`, `set_agent_status()`, `update_task()`, `append_event()`, `get_events()`, `snapshot()`
- All writes go through `aiofiles` for async I/O
- Auto-creates `state/` directory structure on `init()`
- JSON files with atomic writes (write to .tmp, rename)
- `snapshot()` returns the full state tree as a dict (for API responses)

**Key methods:**
```python
class StateStore:
    def __init__(self, state_dir: str = "state"): ...
    async def init(self) -> None: ...                    # Create dirs, load existing state
    async def snapshot(self) -> dict: ...                # Full state as dict
    async def get_agents(self) -> dict[str, AgentState]: ...
    async def get_agent(self, name: str) -> AgentState | None: ...
    async def set_agent_status(self, name: str, status: str, **kwargs) -> None: ...
    async def get_task(self) -> TaskState | None: ...
    async def set_task(self, task: str, platform: str = "") -> None: ...
    async def clear_task(self) -> None: ...
    async def get_stages(self) -> list[StageState]: ...
    async def add_stage(self, stage: StageState) -> None: ...
    async def update_stage(self, stage_id: str, data: dict) -> None: ...
    async def append_event(self, event: dict) -> None: ...  # Append to messages.jsonl
    async def get_events(self, since: float = 0.0) -> list[dict]: ...
    async def get_meta(self) -> dict: ...
    async def set_meta(self, **kwargs) -> None: ...
```

**Data models:**
```python
@dataclass
class AgentState:
    name: str
    status: str  # "idle", "running", "done", "error"
    model: str = ""
    team: str | None = None
    last_message: str = ""
    last_updated: float = 0.0

@dataclass
class TaskState:
    task: str
    platform: str  # "cli", "discord", "dashboard"
    started_at: float
    status: str  # "pending", "running", "completed", "failed"

@dataclass
class StageState:
    stage_id: str
    team: str
    round: int
    workers_used: list[str]
    status: str  # "running", "completed"
    result_summary: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0
```

**Step 1:** Create `harness/state.py` with all dataclasses and `StateStore` class
**Step 2:** Run `python -c "from harness.state import StateStore; print('OK')"` to verify imports
**Step 3:** Commit

### Task 2: Integrate StateStore into EventBus (bridge pattern)

**Objective:** Make EventBus automatically persist state-changing events to the StateStore, so any code that already emits events automatically gets state persistence.

**Files:**
- Modify: `harness/events.py` (add StateStore bridge)
- Modify: `harness/state.py` (add `process_event()` method)

**Implementation:**
- Add `process_event(event: HarnessEvent)` method to `StateStore` that translates events into state mutations:
  - `agent_start` → set agent status to "running"
  - `agent_end` → set agent status to "done"/"error"
  - `worker_status` → update agent last_message
  - `team_start` → add new stage
  - `team_done` → update stage status to "completed"
  - `session_start` → set active task
  - `session_end` → clear active task
  - `routing` → update task with selected teams
  - All events → append to messages.jsonl
- Add optional `state_store: StateStore | None` parameter to `EventBus.__init__`
- In `EventBus.emit()`, after putting to subscriber queues, also call `state_store.process_event(event)` if store is configured

**Step 1:** Add `process_event()` to `StateStore`
**Step 2:** Add `state_store` parameter to `EventBus` and call in `emit()`
**Step 3:** Run import check
**Step 4:** Commit

### Task 3: Wire StateStore into Orchestrator and CLI

**Objective:** Ensure the StateStore is created and initialized when the harness starts, and passed through the dependency chain.

**Files:**
- Modify: `harness/orchestrator.py` (accept and pass through StateStore)
- Modify: `harness/cli.py` (create and init StateStore)
- Modify: `harness/team.py` (pass through to EventBus usage — no changes needed if EventBus handles it)

**Implementation:**
- `Orchestrator.__init__` accepts optional `state_store: StateStore | None`
- Store it, pass to EventBus if state_store provided
- In `cli.py._load()`: create `StateStore`, init it, pass to `EventBus` which passes to `Orchestrator`
- `Orchestrator.process_message`: set task via state_store at start, clear at end

**Step 1:** Update orchestrator.py to accept StateStore
**Step 2:** Update cli.py to create and init StateStore
**Step 3:** Verify CLI loads without errors
**Step 4:** Commit

### Task 4: Add SSE endpoint and state REST API routes

**Objective:** Add REST endpoints for reading state and an SSE endpoint for real-time streaming to the dashboard.

**Files:**
- Modify: `harness/dashboard.py` (add new routes)

**New endpoints:**
```
GET  /api/state              → Full state snapshot
GET  /api/state/agents       → Agent states
GET  /api/state/agents/{name}→ Single agent state
GET  /api/state/task         → Current task
GET  /api/state/stages       → All stages
GET  /api/state/events       → Event log (with ?since= parameter)
GET  /api/state/events/stream → SSE endpoint for real-time streaming
POST /api/state/task         → Set/update active task
POST /api/state/agents/{name}→ Update agent state
```

**SSE Implementation:**
```python
from starlette.responses import StreamingResponse

@app.get("/api/state/events/stream")
async def state_event_stream():
    async def event_generator():
        queue = event_bus.subscribe()
        try:
            # Send initial snapshot
            snapshot = await state_store.snapshot()
            yield f"data: {json.dumps({'type': 'init', 'data': snapshot})}\n\n"
            # Stream events
            while True:
                event = await asyncio.wait_for(queue.get(), timeout=30)
                yield f"data: {event.to_json()}\n\n"
        except asyncio.TimeoutError:
            yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"
        except GeneratorExit:
            event_bus.unsubscribe(queue)
    return StreamingResponse(event_generator(), media_type="text/event-stream")
```

**Step 1:** Add SSE + state routes to dashboard.py
**Step 2:** Verify dashboard starts and endpoints respond
**Step 3:** Commit

### Task 5: Wire StateStore into Dashboard's create_app

**Objective:** Dashboard mode also uses StateStore, and creates its Orchestrator with it.

**Files:**
- Modify: `harness/dashboard.py` (use StateStore in create_app)

**Step 1:** Create StateStore in create_app, pass to EventBus → Orchestrator
**Step 2:** Verify dashboard starts
**Step 3:** Commit

### Task 6: Update requirements and add state/ to .gitignore

**Objective:** Ensure proper dependencies and git hygiene.

**Files:**
- Modify: `requirements.txt` (add `sse-starlette>=1.0` if needed for SSE helpers, or use built-in starlette)
- Modify: `.gitignore` (add `state/` directory)

**Note:** SSE can be done with plain `starlette.responses.StreamingResponse` (already available via FastAPI), so no new deps needed. Just need `.gitignore` update.

**Step 1:** Add `state/` to `.gitignore`
**Step 2:** Verify `.gitignore` is correct
**Step 3:** Commit

---

## File Change Summary

| File | Action | Description |
|------|--------|-------------|
| `harness/state.py` | CREATE | StateStore class, data models, persistence layer |
| `harness/events.py` | MODIFY | Add state_store bridge to EventBus.emit() |
| `harness/orchestrator.py` | MODIFY | Accept StateStore, wire into task lifecycle |
| `harness/cli.py` | MODIFY | Create/init StateStore on startup |
| `harness/dashboard.py` | MODIFY | State API routes, SSE endpoint, StateStore init |
| `.gitignore` | MODIFY | Add `state/` directory |

## Risks & Mitigations

1. **Race conditions on state files** — Mitigate with atomic writes (write .tmp, os.rename)
2. **Large state files slowing down** — Mitigate with bounded event log (max 10000 entries), truncate old stages
3. **EventBus emit becomes slow with disk I/O** — Mitigate by making process_event async and non-blocking (fire-and-forget with asyncio.create_task)
4. **Dashboard creating its own Orchestrator** — This is a known existing issue; the StateStore will at least ensure state is persisted and queryable regardless of which process owns the Orchestrator
