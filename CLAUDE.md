# Multi-Team Agentic Coding Harness

A multi-team agent orchestration system where specialized teams of AI agents collaborate on software engineering tasks through a three-tier delegation architecture.

## Architecture

```
User → Orchestrator → Team Leads → Workers
```

- **Orchestrator**: Single entry point, receives all user messages, delegates to team leads
- **Team Leads** (Planning, Engineering, Validation): Coordinate workers, never execute directly
- **Workers** (Frontend Dev, Backend Dev, QA Engineer, Security Reviewer, etc.): Execute actual work

## Runtime

Agents run via the **PI coding agent** CLI in print mode:

```bash
pi -p "<prompt>" --system-prompt "<system>" --model <model> --mode json
```

PI supports multiple providers (z-ai, anthropic, openai, google, ollama, etc.) — configure via `~/.pi/agent/models.json`.

## Key Concepts

1. **Domain Locking**: Each agent has read/write permissions scoped to specific directories
2. **Agent Expertise**: Persistent per-agent memory files that grow over sessions
3. **Skills System**: Shared and per-agent skills loaded into system prompts
4. **Configuration-Driven**: Teams and agents defined in YAML, easy to modify

## Project Structure

```
harness/
├── harness/
│   ├── __init__.py
│   ├── orchestrator.py      # Main orchestrator - routes user messages to teams
│   ├── team.py              # Team management (lead + workers)
│   ├── agent.py             # Individual agent execution via PI CLI
│   ├── config.py            # YAML config loader & validation
│   ├── domain.py            # File permission enforcement per agent
│   ├── expertise.py         # Per-agent expertise/mental model management
│   ├── skills.py            # Skills loading and template injection
│   ├── session.py           # Session management, conversation logging
│   ├── delegate.py          # Delegation tool for inter-agent communication
│   ├── cli.py               # Interactive chat interface
│   └── models.py            # Model definitions and cost tracking
├── configs/
│   └── multi_team.yaml      # Default multi-team configuration
├── agents/                  # Agent system prompts
├── skills/                  # Shared skill files
├── sessions/                # Session storage (auto-created)
├── expertise/               # Agent expertise files (auto-created)
├── requirements.txt
└── README.md
```

## Quick Start

```bash
cd ~/devel/harness
pip install pyyaml rich aiofiles
python -m harness.cli --config configs/multi_team.yaml
```

Requires `pi` CLI installed and configured. Run `pi --help` for setup.

## Configuration

Models are set to `glm-5.1` by default (z-ai provider, free tier). Change in `configs/multi_team.yaml`:

```yaml
orchestrator:
  model: glm-5.1     # or anthropic/claude-opus-4, openai/gpt-4o, etc.
```

## Commands (in chat)

- `/toggle workers` — Show/hide detailed worker activity
- `/cost` — Show cost breakdown
- `/teams` — Show team structure
- `/expertise [agent]` — Show an agent's expertise/mental model
- `/compact` — Compress conversation history
- `/clear` — Clear conversation
- `/help` — Show commands

## Implementation Details

### Agent Execution
Each agent invocation:
1. Assembles system prompt (base prompt + skills + expertise + domain rules)
2. Builds user prompt (task + context + conversation history)
3. Runs `pi -p <prompt> --system-prompt <system> --model <model> --mode json`
4. Parses PI's JSONL output for response text and usage stats

### PI JSON Output Format
PI emits newline-delimited JSON events:
- `{"type": "session", ...}` — session metadata
- `{"type": "turn_end", "message": {"usage": {...}, ...}}` — usage stats
- `{"type": "agent_end", "messages": [...]}` — final messages with text

Usage format: `{"input": N, "output": N, "cacheRead": N, "cacheWrite": N, "totalTokens": N}`

### Delegation Flow
1. User sends message to orchestrator
2. Orchestrator decides which team lead(s) to involve
3. Each team lead runs via PI, may delegate to workers
4. Workers execute and return results
5. Results bubble back up to orchestrator
6. Orchestrator composes final response to user
