# Agent Reporting Audit — Verification & Fix Plan

**Branch:** `fix/3-bugs-worker-delegation-error-events-state-cleanup`  
**Date:** 2026-05-07  
**Author:** Planning Team Lead (Hermes)

---

## 1. Current State Assessment

### What's Working ✅

1. **Delegation instructions ARE injected into team lead prompts** — `Agent._build_system_prompt()` (agent.py:106-121) checks `self._worker_names` and appends a full `## CRITICAL: Delegation Protocol` section with the `delegate` code-block format and available worker list. This is populated by `Team.__init__()` at team.py:93-94 via `set_available_workers()`.

2. **Agent system prompt files include delegation format examples** — `engineering_lead.md` (line 36-40), `research_lead.md` (line 36-41), `validation_lead.md` (line 34-39) all contain `delegate` code-block examples. `planning_lead.md` does NOT have a delegation example (minor gap, see below).

3. **The `delegate.md` skill** is loaded for all team leads and describes the format well.

4. **State cleanup on failure in task_queue** — The `finally` block at task_queue.py:213-221 correctly calls `state_store.clear_task()` regardless of success/failure. **Bug #3 is already fixed on this branch.**

5. **AgentStatusTracker is hooked into EventBus** — dashboard.py:164-165 adds both trackers as EventBus listeners, so internal events (from direct dashboard process_message calls) update status correctly.

6. **Frontend WebSocket handler** correctly processes `init` message with `agent_statuses` and `worker_statuses`, and streams subsequent events to the Zustand store.

7. **Zustand store** (store.ts) derives agent status from events (`agent_start` → running, `agent_end` → done, `agent_error` → error) and syncs persisted agent states without overwriting `running`.

8. **ActivityFeed** renders all relevant event types with appropriate labels and colors.

### What's Broken ❌

#### Bug #2 (PARTIALLY FIXED): `agent_end` never emitted with `status: "error"` on crash

**Status:** The outer try/except in `Agent.run()` (agent.py:183) catches exceptions from `_execute_pi` and sets `result["error"]`, but then the code at line 187 checks `if not result.get("error")` — when there IS an error, it falls through to the model fallback loop. The `agent_end` event at line 195 emits with `status: "all_models_failed"`, NOT `status: "error"`.

The real problem: **StateStore._handle_event** (state.py:362-369) maps `agent_end` status:
```python
status = "error" if event_data.get("status") == "error" else "done"
```
So `all_models_failed` maps to `"done"` in the StateStore — the agent appears "done" even when all models failed. The `AgentStatusTracker` (dashboard.py:53-54) also maps `agent_end` → `"done"` unconditionally.

**Root cause chain:**
1. `_execute_pi()` can throw (e.g., spawn failure, timeout) — these are caught by the outer try/except at line 183, which produces `result = {"error": ...}`.
2. The model retry loop at line 187 sees `result.get("error")` as truthy, so it continues to the next model.
3. After all models fail, the `agent_end` event at line 195 uses `status: "all_models_failed"` — the StateStore and StatusTracker don't recognize this as an error.
4. **However**, `_execute_pi()` itself is wrapped in try/except internally (agent.py:211, 256, 318) and returns error dicts rather than throwing, so the outer catch at line 183 is rarely hit.
5. The more impactful case: when `_execute_pi` returns successfully with `error` in the result (e.g., exit code != 0), the `agent_end` event emits `status: "all_models_failed"` which maps to `done` in the UI — **agent appears green/done when it actually failed**.

#### Bug #2b: `AgentStatusTracker` never gets `status: "error"` from `agent_end`

`AgentStatusTracker.process_event` (dashboard.py:47-56) only checks `event.type == "agent_error"` (line 55) for setting status to "error". But the backend **never emits** `type: "agent_error"` events — it only emits `agent_end` with varying status data. There's a mismatch between the event types the tracker handles and what the backend produces.

#### Bug #1 Analysis: Workers DO get delegated to (on this branch)

After thorough review, **Bug #1 is already fixed on this branch**. The delegation instructions are injected in `Agent._build_system_prompt()` (agent.py:106-121), which is called every time `Agent.run()` is invoked. The `Team.__init__()` correctly calls `set_available_workers()`. The commit `531656f fix: worker delegation, error event gap, and state cleanup on failure` appears to have addressed this.

**Remaining concern:** `planning_lead.md` lacks a delegation example in its output format section (unlike the other three team leads). This is cosmetic — the system prompt injection provides the format — but adds inconsistency.

---

## 2. Exact Files and Lines That Need Changes

### File: `harness/agent.py`

| Line(s) | Issue | Fix |
|---------|-------|-----|
| 189, 195, 202 | `agent_end` emits `status: "all_models_failed"` which StateStore maps to `done` | Change `status: "all_models_failed"` → `status: "error"` at all three locations |
| 183-184 | Exception catch produces `result["error"]` but no `agent_end` event with `status: "error"` — the error result falls through to model retry, which is correct, but the final `agent_end` status is wrong | Ensure the terminal emit uses `"error"` status |

**Specific changes:**

```python
# Line 195: Change from
self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "all_models_failed"}))
# To:
self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "error", "reason": "all_models_failed"}))

# Line 202: Same change
self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "all_models_failed"}))
# To:
self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "error", "reason": "all_models_failed"}))
```

### File: `harness/dashboard.py`

| Line(s) | Issue | Fix |
|---------|-------|-----|
| 53-54 | `AgentStatusTracker.process_event` maps `agent_end` unconditionally to `"done"` | Check `event.data.get("status")` — if `"error"`, set status to `"error"` |

**Specific changes:**

```python
# Lines 53-54: Change from
elif event.type == "agent_end":
    self._statuses[event.agent] = "done"
# To:
elif event.type == "agent_end":
    end_status = event.data.get("status", "")
    self._statuses[event.agent] = "error" if end_status == "error" else "done"
```

### File: `harness/state.py`

| Line(s) | Issue | Fix |
|---------|-------|-----|
| 363 | Already handles `"error"` status correctly | No change needed — already does `status = "error" if event_data.get("status") == "error" else "done"` |

### File: `harness/task_queue.py`

| Line(s) | Issue | Fix |
|---------|-------|-----|
| 195-209 | Already fixed on this branch — `finally` block at 213-219 calls `state_store.clear_task()` | No further change needed |

### File: `agents/planning_lead.md`

| Line(s) | Issue | Fix |
|---------|-------|-----|
| 25-29 | Missing delegation example in "Output Format" section (other 3 team leads have it) | Add delegation block example for consistency |

**Specific change:**

```markdown
## Output Format

When delegating, use delegation blocks:
\`\`\`delegate
to: <worker_name>
task: <clear task description>
context: <relevant context>
\`\`\`
```

---

## 3. Specific Fixes Summary

### Fix A: Error status in `agent_end` events (`harness/agent.py`)

**Lines 195 and 202:** Change `"all_models_failed"` to `"error"` in the status field of the `agent_end` event data. Keep `"all_models_failed"` as a `reason` sub-field for logging/debugging.

### Fix B: `AgentStatusTracker` error detection (`harness/dashboard.py`)

**Lines 53-54:** Inspect `event.data.get("status")` within `agent_end` events to distinguish success from error, rather than unconditionally setting `"done"`.

### Fix C (Cosmetic): `planning_lead.md` delegation example

**After line 29:** Add delegation block example matching the pattern in other team lead prompts.

---

## 4. Additional Issues Discovered

### Issue D: Duplicate log line in `task_queue.py`

**Line 200 and 211:** `logger.error("Task %s failed: %s", task.task_id, exc)` appears twice in the except block. The first one (line 200) should be removed since the second (line 211) provides the same information after the event is emitted.

### Issue E: `AgentStatusTracker` only handles `agent_error` event type, but nothing emits it

The tracker at dashboard.py:55 checks for `event.type == "agent_error"` but the backend never emits this event type. After Fix A and Fix B, error status will flow through `agent_end` with `data.status == "error"`, making the `agent_error` handler dead code. Consider either:
- Removing the `agent_error` handler (it's dead code), or
- Adding `agent_error` event emission in `Agent.run()` when exceptions occur

**Recommendation:** Keep the `agent_error` handler as a safety net and emit an `agent_error` event in `Agent.run()` catch block for extra visibility.

### Issue F: `agent_end` status inconsistency

The success path (line 189) emits `status: "success"`, the failure path emits `status: "all_models_failed"`, and the final fallback (line 202) also emits `"all_models_failed"`. These are not consistent with what `StateStore._handle_event` expects (`"error"`). After Fix A, all failure cases will use `"error"`.

### Issue G: `state.py` `_handle_event` `agent_end` checks wrong field

At state.py:363:
```python
status = "error" if event_data.get("status") == "error" else "done"
```
This is correct for the fixed agent.py (which will emit `status: "error"`). But the `last_message` field at line 368 reads from `event_data.get("summary", "")` — the backend never sets a `summary` field, it sets `status` and `reason`. The `last_message` will always be empty.

**Fix:** Change `event_data.get("summary", "")` to `event_data.get("reason", "")` at state.py:368 to capture the error reason.

---

## 5. Verification Steps

### Step 1: Verify Bug #1 is fixed (delegation instructions)

```bash
# Run a test delegation and check the system prompt
cd ~/devel/harness
python -c "
from harness.config import load_config
from harness.team import Team
from harness.models import CostTracker
config = load_config('configs/multi_team.yaml')
for tcfg in config.teams:
    if not tcfg.instances:
        team = Team(config=tcfg, cost_tracker=CostTracker())
        prompt = team.lead._build_system_prompt()
        has_delegate = '## CRITICAL: Delegation Protocol' in prompt
        has_workers = 'Your available workers:' in prompt
        print(f'{team.name}: delegation={has_delegate}, workers={has_workers}')
        if has_workers:
            for w in team.workers:
                assert w in prompt, f'Worker {w} not in prompt!'
    else:
        for inst in tcfg.instances:
            from orchestrator import Orchestrator
            # instances need orchestrator to expand
"
```

### Step 2: Verify Bug #2 fix (agent_end error status)

After applying fixes to `agent.py` and `dashboard.py`:

```bash
# Unit test: simulate all_models_failed and check agent_end status
python -c "
from harness.events import HarnessEvent
from harness.dashboard import AgentStatusTracker

tracker = AgentStatusTracker()

# Simulate agent_start then agent_end with error
tracker.process_event(HarnessEvent('agent_start', agent='test_agent'))
assert tracker.get_status('test_agent') == 'running'

# Before fix: agent_end with 'all_models_failed' → 'done'
tracker.process_event(HarnessEvent('agent_end', agent='test_agent', data={'status': 'all_models_failed'}))
print(f'Status after all_models_failed: {tracker.get_status(\"test_agent\")}')
# Should be 'done' before fix, should remain incorrect

# After fix: agent_end with 'error' → 'error'
tracker2 = AgentStatusTracker()
tracker2.process_event(HarnessEvent('agent_start', agent='test_agent2'))
tracker2.process_event(HarnessEvent('agent_end', agent='test_agent2', data={'status': 'error'}))
assert tracker2.get_status('test_agent2') == 'error'
print('✅ Error status correctly tracked after fix')
"
```

### Step 3: Verify Bug #3 is fixed (state cleanup)

```bash
# Check the finally block exists in task_queue.py
grep -n 'finally' harness/task_queue.py
grep -n 'clear_task' harness/task_queue.py
# Should show lines 213 (finally) and 217 (clear_task)
```

### Step 4: End-to-end dashboard test

1. Start the dashboard: `python -m harness.dashboard --config configs/multi_team.yaml`
2. Open browser to `http://localhost:5173`
3. Send a message via the dashboard
4. Verify:
   - Agent status dots change to green (running) then blue (done) or red (error)
   - Activity feed shows `⚡ Agent Started` and `✓ Agent Finished` events
   - Worker delegations appear as `agent_start` events for workers
   - On error, agent status shows red with "error" label
5. Check WebSocket init message contains `agent_statuses` and `worker_statuses`

### Step 5: Frontend state verification

```bash
# Check that the Zustand store correctly handles error states
cd dashboard
npx vitest run --reporter=verbose 2>/dev/null || echo "No tests configured"
```

---

## 6. Implementation Priority

| Priority | Fix | Files | Risk | Effort |
|----------|-----|-------|------|--------|
| P0 | A: Error status in agent_end | `agent.py` | Low — string change | 5 min |
| P0 | B: StatusTracker error detection | `dashboard.py` | Low — conditional change | 5 min |
| P1 | G: StateStore last_message field | `state.py` | Low — field name change | 2 min |
| P2 | D: Duplicate log line | `task_queue.py` | None — cosmetic | 1 min |
| P2 | C: planning_lead.md example | `agents/planning_lead.md` | None — cosmetic | 2 min |
| P3 | E: agent_error dead code | `dashboard.py` | Low — optional | 3 min |

**Total estimated effort:** ~18 minutes for all fixes.

---

## 7. Files Modified Summary

| File | Changes |
|------|---------|
| `harness/agent.py` | Lines 195, 202: `"all_models_failed"` → `"error"` with reason field |
| `harness/dashboard.py` | Lines 53-54: Check event.data.status for error in agent_end |
| `harness/state.py` | Line 368: `"summary"` → `"reason"` in last_message |
| `harness/task_queue.py` | Line 200: Remove duplicate log line |
| `agents/planning_lead.md` | After line 29: Add delegation block example |
