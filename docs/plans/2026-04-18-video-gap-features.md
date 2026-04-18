# Harness Video Gap Features — Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Close the gap between the current harness codebase and the patterns demonstrated in IndyDev Dan's two videos (multi-team agent coding + infinite UI).

**Architecture:** Extend the existing 3-tier system (Orchestrator → Lead → Workers) with horizontal team scaling, reusable prompt commands, till-done orchestration, model rotation, and prompt piping via stdin.

**Tech Stack:** Python 3.11+, PyYAML, Rich, asyncio, PI coding agent CLI

---

## Phase 1: Horizontal Team Scaling (A/B/C Teams)

Multiple instances of the same team type running in parallel with different models. This is the core differentiator from the videos.

### Task 1: Add `instances` field to TeamConfig

**Objective:** Allow a team definition to be instantiated N times with different model overrides.

**Files:**
- Modify: `harness/config.py`

**Step 1: Update TeamConfig dataclass**

Add an `instances` field that defines parallel team instances with model overrides:

```python
@dataclass
class TeamInstanceConfig:
    """A single instance of a team with optional model overrides."""
    name: str  # e.g. "engineering_A"
    model_overrides: dict[str, str] = field(default_factory=dict)  # agent_name -> model

@dataclass
class TeamConfig:
    """Configuration for a team (lead + workers)."""
    name: str
    color: str = "white"
    lead: AgentConfig = field(default_factory=None)  # type: ignore[assignment]
    workers: list[AgentConfig] = field(default_factory=list)
    instances: list[TeamInstanceConfig] = field(default_factory=list)
```

**Step 2: Parse instances from YAML**

Add to `_parse_team()` helper (or inline in `load_config`):

```python
def _parse_team_instances(data: dict[str, Any]) -> list[TeamInstanceConfig]:
    instances = []
    for inst in data.get("instances", []):
        instances.append(TeamInstanceConfig(
            name=inst["name"],
            model_overrides=inst.get("models", {}),
        ))
    return instances
```

**Step 3: Update YAML config to support instances**

Example in `configs/multi_team.yaml`:

```yaml
  - name: engineering
    color: green
    instances:
      - name: engineering_A
        models:
          engineering_lead: "z-ai/glm-4.7"
          frontend_dev: "z-ai/glm-4.7-flashx"
          backend_dev: "z-ai/glm-4.7-flashx"
      - name: engineering_B
        models:
          engineering_lead: "opencode-go/qwen3.6-plus"
          frontend_dev: "opencode-go/minimax-m2.7"
          backend_dev: "opencode-go/mimo-v2-pro"
    lead:
      ...
```

**Step 4: Verify parsing**

Run: `python -c "from harness.config import load_config; c = load_config('configs/multi_team.yaml'); print(c.teams)"`

Expected: Config loads without error (instances list may be empty if YAML not yet updated)

**Step 5: Commit**

```bash
git add harness/config.py
git commit -m "feat: add instances field to TeamConfig for horizontal scaling"
```

---

### Task 2: Expand instances into real Team objects in Orchestrator

**Objective:** When instances are defined, create multiple Team objects per config entry.

**Files:**
- Modify: `harness/orchestrator.py`

**Step 1: Add `_create_team_instance()` helper**

When instances are defined, clone the TeamConfig with suffixed names and model overrides, then create a Team for each:

```python
import copy

def _create_team_instance(
    self, base_config: TeamConfig, instance: TeamInstanceConfig
) -> Team:
    """Create a Team from a base config with instance-specific overrides."""
    cfg = copy.deepcopy(base_config)
    cfg.name = instance.name
    # Apply model overrides
    overrides = instance.model_overrides
    if cfg.lead.name in overrides:
        cfg.lead.model = overrides[cfg.lead.name]
    for w in cfg.workers:
        if w.name in overrides:
            w.model = overrides[w.name]
    return Team(
        config=cfg,
        cost_tracker=self.cost_tracker,
        base_dir=self.base_dir,
        session=self.session,
    )
```

**Step 2: Update `__init__` to create teams from instances**

```python
# In Orchestrator.__init__, replace the team creation loop:
self.teams: dict[str, Team] = {}
for tcfg in config.teams:
    if tcfg.instances:
        for inst in tcfg.instances:
            team = self._create_team_instance(tcfg, inst)
            self.teams[inst.name] = team
    else:
        team = Team(
            config=tcfg,
            cost_tracker=self.cost_tracker,
            base_dir=self.base_dir,
            session=self.session,
        )
        self.teams[tcfg.name] = team
```

**Step 3: Update routing prompt to show instance teams**

The routing prompt in `process_message` already lists `self.teams.keys()`, so instance names like `engineering_A` will appear automatically. Update the display to show which base team they belong to.

**Step 4: Verify**

Run: `python -c "from harness.config import load_config; from harness.orchestrator import Orchestrator; c = load_config('configs/multi_team.yaml'); o = Orchestrator(config=c); print(list(o.teams.keys()))"`

Expected: Team names printed, no errors

**Step 5: Commit**

```bash
git add harness/orchestrator.py
git commit -m "feat: orchestrator expands team instances for horizontal scaling"
```

---

## Phase 2: Prompt Piping via Stdin

The current code passes prompts as CLI args (`pi -p "<prompt>"`), which can hit OS arg length limits with long conversations/expertise. PI supports piping prompts via stdin.

### Task 3: Switch agent.py to pipe prompts via stdin

**Objective:** Send the user prompt via stdin instead of as a CLI argument to avoid shell arg length limits.

**Files:**
- Modify: `harness/agent.py`

**Step 1: Change `_execute_pi` to use stdin**

Replace the `-p` flag approach with stdin piping. PI reads from stdin when no `-p` arg is given and input is piped:

```python
async def _execute_pi(self, cmd: list[str], timeout: int) -> dict[str, Any]:
    """Execute pi CLI command and parse JSONL output."""
    # Build command without -p flag — we'll pipe the prompt via stdin
    pi_cmd = ["pi", "--system-prompt", cmd[cmd.index("--system-prompt") + 1]]
    
    # Find and add model flag if present
    if "--model" in cmd:
        idx = cmd.index("--model")
        pi_cmd.extend(["--model", cmd[idx + 1]])
    
    pi_cmd.extend(["--mode", "json"])
    
    # Add tools restriction if present
    if "--tools" in cmd:
        idx = cmd.index("--tools")
        pi_cmd.extend(["--tools", cmd[idx + 1]])
    
    prompt_text = cmd[cmd.index("-p") + 1]  # Extract the prompt
    
    try:
        proc = await asyncio.create_subprocess_exec(
            *pi_cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=self.base_dir,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(input=prompt_text.encode("utf-8")),
            timeout=timeout,
        )
    except asyncio.TimeoutError:
        proc.kill()  # type: ignore
        return {
            "error": "timeout",
            "result": f"Agent {self.name} timed out after {timeout}s",
            "usage": {},
        }
    # ... rest of parsing stays the same
```

**Step 2: Clean up `run()` method**

Simplify cmd construction — no longer needs `-p`:

```python
async def run(self, message: str, context: str = "", timeout: int = 300) -> dict[str, Any]:
    system_prompt = self._build_system_prompt()
    prompt = self._build_prompt(message, context)
    
    cmd = ["pi", "--system-prompt", system_prompt, "--mode", "json"]
    if self.model:
        cmd.extend(["--model", self.model])
    if self.config.domain.update and "." not in self.config.domain.update:
        cmd.extend(["--tools", "read,bash"])
    
    try:
        return await self._execute_pi(cmd, prompt, timeout)
    except Exception as e:
        return {"error": str(e), "result": f"Agent {self.name} failed: {e}", "usage": {}}
```

**Step 3: Verify**

Run: `python -c "import asyncio; from harness.config import load_config; from harness.agent import Agent; c = load_config('configs/multi_team.yaml'); a = Agent(config=c.orchestrator, base_dir=c.base_dir); print(asyncio.run(a.run('ping')))" `

Expected: Agent runs, returns response (may be slow if PI is working)

**Step 4: Commit**

```bash
git add harness/agent.py
git commit -m "fix: pipe prompts via stdin to avoid shell arg length limits"
```

---

## Phase 3: Reusable Prompt Commands

Stored workflows (like `plan → engineer → validate`) that can be invoked by name. These are predefined prompt chains that the orchestrator executes in sequence.

### Task 4: Add command definitions to config and loader

**Objective:** Allow YAML to define named workflows that chain teams in sequence.

**Files:**
- Modify: `harness/config.py`
- Create: `harness/commands.py`

**Step 1: Add CommandConfig dataclass**

```python
@dataclass
class CommandStep:
    """A single step in a command workflow."""
    team: str  # team name to delegate to
    prompt_template: str  # template with {input} and {prev_result} variables

@dataclass
class CommandConfig:
    """A reusable command workflow."""
    name: str
    description: str
    steps: list[CommandStep]
```

**Step 2: Parse commands from YAML**

In `load_config()`:

```python
commands: dict[str, CommandConfig] = {}
for cmd_data in data.get("commands", []):
    steps = [
        CommandStep(
            team=s["team"],
            prompt_template=s.get("prompt", "{input}"),
        )
        for s in cmd_data.get("steps", [])
    ]
    cmd = CommandConfig(
        name=cmd_data["name"],
        description=cmd_data.get("description", ""),
        steps=steps,
    )
    commands[cmd.name] = cmd
```

Add `commands` field to `HarnessConfig`:

```python
@dataclass
class HarnessConfig:
    orchestrator: AgentConfig
    teams: list[TeamConfig] = field(default_factory=list)
    commands: dict[str, CommandConfig] = field(default_factory=dict)
    base_dir: str = "."
```

**Step 3: Create `harness/commands.py` — command executor**

```python
"""Reusable prompt commands — sequential team workflows."""
from __future__ import annotations
from typing import Any
from .config import CommandConfig


async def execute_command(
    command: CommandConfig,
    user_input: str,
    teams: dict,
) -> list[dict[str, Any]]:
    """Execute a command workflow: run each step's team in sequence."""
    results = []
    prev_result = ""
    
    for step in command.steps:
        # Template substitution
        prompt = step.prompt_template.replace("{input}", user_input)
        prompt = prompt.replace("{prev_result}", prev_result)
        
        team = teams.get(step.team)
        if not team:
            results.append({"error": f"Team '{step.team}' not found"})
            continue
        
        result = await team.execute(
            task=prompt,
            context=f"Step in workflow '{command.name}'",
        )
        results.append(result)
        prev_result = result.get("final_response", "")
    
    return results
```

**Step 4: Add example commands to YAML config**

```yaml
commands:
  - name: plan-build-validate
    description: "Plan, implement, then validate a feature"
    steps:
      - team: planning
        prompt: "Create a detailed implementation plan for: {input}"
      - team: engineering
        prompt: "Implement the following plan:\n\n{prev_result}\n\nOriginal request: {input}"
      - team: validation
        prompt: "Review and test the implementation of: {input}\n\nImplementation summary:\n{prev_result}"
```

**Step 5: Verify**

Run: `python -c "from harness.config import load_config; c = load_config('configs/multi_team.yaml'); print(list(c.commands.keys()))"` 

Expected: `['plan-build-validate']` (or empty if YAML not updated yet)

**Step 6: Commit**

```bash
git add harness/config.py harness/commands.py
git commit -m "feat: add reusable command workflows to config"
```

---

### Task 5: Wire commands into orchestrator and CLI

**Objective:** Detect command invocations in user messages and execute the workflow.

**Files:**
- Modify: `harness/orchestrator.py`
- Modify: `harness/cli.py`

**Step 1: Add command detection to orchestrator**

In `process_message()`, before the routing step, check if the message matches a command:

```python
# Check if message matches a command
words = user_message.split()
command_name = None
command_input = user_message

# Pattern: "plan-build-validate: add user auth"
if ":" in words[0]:
    candidate = words[0].rstrip(":")
    if candidate in self.config.commands:
        command_name = candidate
        command_input = " ".join(words[1:])

if command_name:
    from .commands import execute_command
    cmd = self.config.commands[command_name]
    results = await execute_command(cmd, command_input, self.teams)
    # Synthesize results
    ...
```

**Step 2: Add `/commands` slash command to CLI**

```python
elif cmd == "/commands":
    if self.orchestrator:
        for name, cmd_cfg in self.orchestrator.config.commands.items():
            console.print(f"  [cyan]{name}[/cyan]: {cmd_cfg.description}")
    return True
```

**Step 3: Commit**

```bash
git add harness/orchestrator.py harness/cli.py
git commit -m "feat: wire command workflows into orchestrator and CLI"
```

---

## Phase 4: Till-Done Orchestration

Agents work until all tasks in a list are complete, not just one-shot. The orchestrator or lead maintains a task list and re-delegates until done.

### Task 6: Add till-done loop to Team.execute()

**Objective:** After a team lead delegates and gets results, check if all tasks are complete. If not, re-prompt the lead to continue.

**Files:**
- Modify: `harness/team.py`

**Step 1: Add max_iterations and till_done parameters**

```python
async def execute(
    self,
    task: str,
    context: str = "",
    till_done: bool = True,
    max_rounds: int = 5,
) -> dict[str, Any]:
```

**Step 2: Implement the till-done loop**

Wrap the existing lead → delegate → workers flow in a loop:

```python
all_worker_results = []
round_num = 0
lead_text = ""

while round_num < max_rounds:
    round_num += 1
    
    if round_num == 1:
        lead_result = await self.lead.run(message=task, context=context)
    else:
        # Follow-up: ask lead to continue or wrap up
        followup = (
            f"Previous round completed. Results so far:\n"
            f"{self._compile_result(lead_text, all_worker_results[-1] if all_worker_results else [])}\n\n"
            f"If all tasks from the original request are complete, respond with:\n"
            f"DONE: <summary>\n\n"
            f"If not, delegate the remaining work to your workers."
        )
        lead_result = await self.lead.run(message=followup, context=task)
    
    lead_text = lead_result.get("result", "")
    if isinstance(lead_text, dict):
        lead_text = str(lead_text)
    
    # Check if lead says done
    if till_done and lead_text.strip().upper().startswith("DONE:"):
        break
    
    # Parse delegations and execute workers (existing logic)
    delegations = parse_delegation_blocks(lead_text)
    if not delegations:
        break  # No more delegation = lead is done
    
    worker_results = []
    worker_tasks = []
    for dep in delegations:
        target_name = dep["to"]
        if target_name in self.workers:
            worker_tasks.append(
                self.workers[target_name].run(
                    message=dep["task"],
                    context=dep.get("context", ""),
                )
            )
    if worker_tasks:
        worker_results = await asyncio.gather(*worker_tasks)
        all_worker_results.extend(worker_results)
    
    if not till_done:
        break  # Single-shot mode
```

**Step 3: Commit**

```bash
git add harness/team.py
git commit -m "feat: add till-done orchestration loop to team execution"
```

---

## Phase 5: Model Rotation on Failure

When a model fails (timeout, empty response, error), automatically retry with a fallback model from a different provider.

### Task 7: Add retry-with-fallback to Agent.run()

**Objective:** On failure, retry the agent with an alternative model.

**Files:**
- Modify: `harness/agent.py`
- Modify: `harness/config.py`

**Step 1: Add fallback_models to AgentConfig**

```python
@dataclass
class AgentConfig:
    name: str
    model: str
    system_prompt: str
    expertise: list[ExpertiseConfig] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domain: DomainConfig = field(default_factory=DomainConfig)
    max_turns: int = 30
    fallback_models: list[str] = field(default_factory=list)
```

Parse from YAML:

```python
fallback_models=data.get("fallback_models", []),
```

**Step 2: Add retry logic to Agent.run()**

```python
async def run(self, message: str, context: str = "", timeout: int = 300) -> dict[str, Any]:
    system_prompt = self._build_system_prompt()
    prompt = self._build_prompt(message, context)
    
    models_to_try = [self.model] + self.config.fallback_models
    
    for i, model in enumerate(models_to_try):
        cmd = ["pi", "--system-prompt", system_prompt, "--mode", "json"]
        if model:
            cmd.extend(["--model", model])
        if self.config.domain.update and "." not in self.config.domain.update:
            cmd.extend(["--tools", "read,bash"])
        
        result = await self._execute_pi(cmd, prompt, timeout)
        
        # Check if result is a failure
        if result.get("error") or not result.get("result", "").strip():
            if i < len(models_to_try) - 1:
                # Try next model
                continue
            return result
        
        return result
    
    return {"error": "all models failed", "result": "All model attempts failed", "usage": {}}
```

**Step 3: Add example fallback config**

```yaml
workers:
  - name: backend_dev
    model: "z-ai/glm-4.7"
    fallback_models: ["opencode-go/qwen3.6-plus", "z-ai/glm-4.7-flashx"]
```

**Step 4: Commit**

```bash
git add harness/agent.py harness/config.py
git commit -m "feat: add model rotation with fallback on failure"
```

---

## Phase 6: Assign delegate.md Skill to Agents

Quick config fix — the `delegate.md` skill exists but isn't assigned to any agent in the YAML.

### Task 8: Assign delegate skill to leads and orchestrator

**Objective:** All delegating agents should have the delegation format instructions.

**Files:**
- Modify: `configs/multi_team.yaml`

**Step 1: Add delegate skill to orchestrator and all leads**

```yaml
orchestrator:
  skills:
    - skills/active_listener.md
    - skills/zero_micromanagement.md
    - skills/conversational_response.md
    - skills/mental_model.md
    - skills/delegate.md          # ADD THIS

# Repeat for planning_lead, engineering_lead, validation_lead
```

**Step 2: Verify config loads**

Run: `python -c "from harness.config import load_config, validate_config; c = load_config('configs/multi_team.yaml'); print(validate_config(c))"`

Expected: `[]` (no warnings)

**Step 3: Commit**

```bash
git add configs/multi_team.yaml
git commit -m "fix: assign delegate skill to orchestrator and team leads"
```

---

## Phase 7: Read-Only Expertise

Support non-updatable expertise files that inject domain-specific knowledge (e.g., billing workflows, DevOps procedures) that agents can read but never modify.

### Task 9: Verify read-only expertise works end-to-end

**Objective:** The `updatable: false` field already exists in ExpertiseConfig and is respected in `expertise.py` (append_insight returns early). Verify and add a usage example.

**Files:**
- Modify: `configs/multi_team.yaml` (add example read-only expertise)

**Step 1: Add read-only expertise example**

```yaml
  - name: engineering
    lead:
      name: engineering_lead
      expertise:
        - path: expertise/engineering_lead.md
          updatable: true
          max_lines: 10000
        - path: expertise/coding_standards.md    # NEW: read-only domain knowledge
          updatable: false
          max_lines: 500
```

**Step 2: Create a sample read-only expertise file**

Create `expertise/coding_standards.md` with placeholder content.

**Step 3: Verify**

Run: `python -c "from harness.expertise import ExpertiseManager; from harness.config import ExpertiseConfig; em = ExpertiseManager('.'); cfg = ExpertiseConfig(path='expertise/coding_standards.md', updatable=False); em.append_insight(cfg, 'test'); print('OK')"`

Expected: File is NOT modified (append does nothing).

**Step 4: Commit**

```bash
git add configs/multi_team.yaml expertise/coding_standards.md
git commit -m "docs: add read-only expertise example to config"
```

---

## Summary of All Tasks

| # | Feature | Files Changed | Complexity |
|---|---------|---------------|------------|
| 1 | TeamConfig instances field | config.py | Low |
| 2 | Orchestrator instance expansion | orchestrator.py | Medium |
| 3 | Prompt piping via stdin | agent.py | Medium |
| 4 | Command config + loader | config.py, commands.py | Medium |
| 5 | Wire commands to orchestrator + CLI | orchestrator.py, cli.py | Medium |
| 6 | Till-done orchestration loop | team.py | Medium |
| 7 | Model rotation fallback | agent.py, config.py | Medium |
| 8 | Assign delegate skill | multi_team.yaml | Trivial |
| 9 | Read-only expertise example | multi_team.yaml, expertise/ | Trivial |

**Execution order:** 8 → 9 → 3 → 1 → 2 → 7 → 6 → 4 → 5
(Start with trivial fixes, then infrastructure, then features)
