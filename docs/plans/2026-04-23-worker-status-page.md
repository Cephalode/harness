# Worker Status Live Dashboard — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add a live-updating "Workers" tab to the Harness dashboard that shows real-time status of every worker, with each worker reporting what it's currently working on.

**Architecture:** Add a `worker_status` event type that agents emit when starting new subtasks. Backend tracks latest status per worker in an in-memory tracker. Frontend gets a new Zustand store slice, a responsive card-grid component, and a third tab alongside Activity and Diagram. Agent system prompts get injected with status-reporting instructions so workers know to emit updates.

**Tech Stack:** Python/FastAPI backend, React/Zustand/Tailwind frontend, WebSocket streaming (existing).

---

## Task 1: Add `worker_status` event support to backend

### Objective
Extend the event system so workers can report what they're currently doing. No new files — just add handling to existing files.

### Files
- Modify: `harness/events.py`
- Modify: `harness/dashboard.py`

### Changes

#### In `harness/events.py`
No changes needed — the existing `HarnessEvent` with `type="worker_status"` works as-is. The `type` field is a free-form string.

#### In `harness/dashboard.py`
Add a `WorkerStatusTracker` class that:
- Maintains a dict of `agent_name -> {message, timestamp, team, task}`
- Has a `process_event(event)` method that handles `worker_status` events
- Has a `get_all()` method that returns the current snapshot
- Also processes `agent_start` events to set status to "Starting..."
- Also processes `agent_end` events to set status to "Idle" (or "Completed: ...")

Wire it into `create_app()`:
- Instantiate alongside `AgentStatusTracker`
- Process events in `receive_event()` and `receive_events()` before emitting
- Add `GET /api/worker-statuses` endpoint returning tracker snapshot
- Include `worker_statuses` in the WebSocket `init` message

```python
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
            entry.task = event.data.get("message_length", entry.task) if isinstance(event.data.get("message_length"), str) else entry.task
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
```

### Verification
- `GET /api/worker-statuses` returns `[]` when no events
- Posting a `worker_status` event then calling GET returns the status
- WebSocket init includes `worker_statuses` key

---

## Task 2: Add `workerStatuses` to Zustand store + handle new event

### Objective
Add worker status state management to the frontend store.

### Files
- Modify: `dashboard/src/store.ts`

### Changes

Add a `WorkerStatusEntry` interface and a `workerStatuses` field to the store:

```typescript
export interface WorkerStatusEntry {
  agent: string
  message: string
  timestamp: number
  team: string | null
  task: string | null
}
```

Add to state interface:
```typescript
workerStatuses: Record<string, WorkerStatusEntry>
setWorkerStatuses: (statuses: Record<string, WorkerStatusEntry>) => void
updateWorkerStatus: (agent: string, status: WorkerStatusEntry) => void
```

Add to store implementation:
```typescript
workerStatuses: {},
setWorkerStatuses: (workerStatuses) => set({ workerStatuses }),
updateWorkerStatus: (agent, status) => set((state) => ({
  workerStatuses: { ...state.workerStatuses, [agent]: status },
})),
```

In the `addEvent` reducer, also handle `worker_status` events:
```typescript
if (event.type === 'worker_status' && event.agent) {
  statuses[event.agent] = 'running'  // keep existing agent status logic
  workerStatuses = { ...state.workerStatuses }
  workerStatuses[event.agent] = {
    agent: event.agent,
    message: (event.data.message as string) || 'Working...',
    timestamp: event.timestamp,
    team: event.team,
    task: (event.data.task as string) || null,
  }
}
```

### Verification
- TypeScript compiles without errors

---

## Task 3: Handle `worker_status` events in WebSocket hook

### Objective
Update the WebSocket hook to process `worker_status` events and restore worker statuses from init.

### Files
- Modify: `dashboard/src/hooks/useWebSocket.ts`

### Changes

In `onmessage` handler, after processing `init` message:
```typescript
if (data.worker_statuses && typeof data.worker_statuses === 'object') {
  const ws = data.worker_statuses as Record<string, WorkerStatusEntry>
  setWorkerStatuses(ws)
}
```

The `worker_status` regular events are already handled by `addEvent()` which dispatches to the store.

Import `setWorkerStatuses` from the store.

### Verification
- TypeScript compiles, init message correctly populates worker statuses

---

## Task 4: Create WorkerStatus component

### Objective
Build the live-updating worker status card grid component.

### Files
- Create: `dashboard/src/components/WorkerStatus.tsx`

### Design
A responsive grid of cards, one per worker. Each card shows:
- Agent name (bold)
- Team badge (colored pill)
- Current status message (the live text)
- Relative timestamp ("2s ago", "1m ago")
- Pulsing dot for active workers (status contains "Starting" or message doesn't contain "Completed"/"Idle"/"Finished")

```tsx
import { useEffect, useState } from 'react'
import { useDashboardStore, WorkerStatusEntry } from '../store'

function timeAgo(ts: number): string {
  if (!ts) return ''
  const diff = Math.floor(Date.now() / 1000 - ts)
  if (diff < 5) return 'just now'
  if (diff < 60) return `${diff}s ago`
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`
  return `${Math.floor(diff / 3600)}h ago`
}

function isWorking(message: string): boolean {
  const idle = ['idle', 'completed', 'finished']
  return !idle.some(k => message.toLowerCase().includes(k))
}

const teamColors: Record<string, string> = {
  planning: 'bg-blue-900/50 text-blue-300',
  engineering_A: 'bg-green-900/50 text-green-300',
  engineering_B: 'bg-emerald-900/50 text-emerald-300',
  engineering: 'bg-green-900/50 text-green-300',
  research: 'bg-cyan-900/50 text-cyan-300',
  validation: 'bg-red-900/50 text-red-300',
}

export default function WorkerStatus() {
  const workerStatuses = useDashboardStore((s) => s.workerStatuses)
  const [, setTick] = useState(0)

  // Re-render every 5s to update "time ago" labels
  useEffect(() => {
    const interval = setInterval(() => setTick(t => t + 1), 5000)
    return () => clearInterval(interval)
  }, [])

  const entries = Object.values(workerStatuses)

  if (entries.length === 0) {
    return (
      <div className="text-gray-600 text-sm text-center py-8">
        No worker status reports yet.
        <br />
        <span className="text-xs">Status updates appear when workers are active.</span>
      </div>
    )
  }

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
      {entries.map((ws) => {
        const working = isWorking(ws.message)
        return (
          <div
            key={ws.agent}
            className={`
              rounded-lg border p-3 transition-colors duration-300
              ${working
                ? 'border-green-500/30 bg-green-900/10'
                : 'border-white/5 bg-white/[0.02]'
              }
            `}
          >
            <div className="flex items-center gap-2 mb-2">
              <span
                className={`w-2 h-2 rounded-full flex-shrink-0 ${
                  working ? 'bg-green-400 animate-pulse' : 'bg-gray-600'
                }`}
              />
              <span className="font-medium text-sm text-white truncate">{ws.agent}</span>
              {ws.team && (
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full ${teamColors[ws.team] || 'bg-gray-800 text-gray-400'}`}>
                  {ws.team}
                </span>
              )}
            </div>
            <div className={`text-sm ${working ? 'text-gray-300' : 'text-gray-500'} mb-1`}>
              {ws.message}
            </div>
            {timeAgo(ws.timestamp) && (
              <div className="text-[10px] text-gray-600">
                {timeAgo(ws.timestamp)}
              </div>
            )}
          </div>
        )
      })}
    </div>
  )
}
```

### Verification
- Component renders with empty state
- TypeScript compiles

---

## Task 5: Add "Workers" tab to App.tsx

### Objective
Wire the new WorkerStatus component as a third tab in the dashboard.

### Files
- Modify: `dashboard/src/App.tsx`

### Changes

1. Import `WorkerStatus` component
2. Extend `ViewTab` type: `'activity' | 'diagram' | 'workers'`
3. Add tab button for "Workers" in both mobile and desktop headers
4. Render `<WorkerStatus />` in the main content area when `activeTab === 'workers'`

### Verification
- Three tabs visible: Activity, Diagram, Workers
- Clicking Workers shows the WorkerStatus component

---

## Task 6: Inject status reporting instruction into agent prompts

### Objective
Tell agents to emit status updates when they start working on something new.

### Files
- Modify: `harness/agent.py`

### Changes

In the `_build_system_prompt` method, after all other parts are assembled, append a status reporting instruction:

```python
# Inject status reporting instruction
parts.append(
    "## Status Reporting\n\n"
    "You are running inside a multi-agent orchestration harness with a live dashboard. "
    "When you begin working on a NEW subtask or phase of your work, output a status line "
    "in this exact format at the START of your response (before any other output):\n\n"
    "```status\n"
    "message: <brief description of what you're about to do>\n"
    "```\n\n"
    "For example:\n"
    "- ```status\\nmessage: Reading the main.py file to understand the codebase\\n```\n"
    "- ```status\\nmessage: Writing unit tests for the auth module\\n```\n"
    "- ```status\\nmessage: Analyzing the error log to find root cause\\n```\n\n"
    "This status is displayed on a live dashboard so your operator can see what you're doing. "
    "Always emit a status update when your focus shifts to a new activity."
)
```

Then in the `_build_prompt` method or `run` method, parse these status blocks from the agent's output and emit `worker_status` events.

Actually, the better approach is to parse status blocks from the agent's response text BEFORE returning the result. In `agent.py`, after getting the result from `_execute_pi`, scan for status blocks:

```python
# Parse status updates from agent output
STATUS_BLOCK_PATTERN = re.compile(r"```status\s*\nmessage:\s*(.+?)\n```", re.DOTALL)

# In the run() method, after getting result_text:
if self.event_bus and result.get("result"):
    status_matches = STATUS_BLOCK_PATTERN.findall(result["result"])
    for status_msg in status_matches:
        self.event_bus.emit(HarnessEvent(
            "worker_status",
            agent=self.name,
            team=self.team_name,
            data={"message": status_msg.strip()},
        ))
    # Clean status blocks from result
    result["result"] = STATUS_BLOCK_PATTERN.sub("", result["result"]).strip()
```

### Verification
- Agents that include status blocks in their output trigger `worker_status` events
- Status blocks are stripped from the final result text
- Events are visible via `/api/worker-statuses`

---

## Task 7: Build and verify

### Objective
Build the dashboard and verify everything works.

### Steps
1. `cd ~/devel/harness/dashboard && npm run build`
2. Start the dashboard server: `.venv/bin/python -m harness.cli --dashboard --port 5174`
3. Verify `/api/worker-statuses` responds
4. Verify WebSocket sends `worker_statuses` in init
5. Verify the Workers tab renders
