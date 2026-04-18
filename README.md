# Multi-Team Agentic Coding Harness

A multi-team agent orchestration system where specialized teams of AI agents collaborate on software engineering tasks through a three-tier delegation architecture: **Orchestrator → Team Leads → Workers**.

## Quick Start

```bash
# Install dependencies
pip install -r requirements.txt

# Run the harness
python -m harness.cli

# Or install and use the entry point
pip install -e .
harness
```

## Architecture

```
User → Orchestrator → Team Leads → Workers
```

| Layer | Role | Examples |
|-------|------|----------|
| Orchestrator | Routes messages, synthesizes results | orchestrator |
| Team Leads | Coordinate workers, never execute directly | planning_lead, engineering_lead, validation_lead |
| Workers | Execute actual work | frontend_dev, backend_dev, qa_engineer, security_reviewer |

## Teams

- **Planning** (blue) — Architecture, design, specifications
- **Engineering** (green) — Frontend + backend implementation
- **Validation** (red) — Testing, QA, security review

## Key Concepts

### Domain Locking
Each agent has scoped file permissions:
- **Read access**: What directories an agent can read
- **Write access**: What directories an agent can modify
- Enforced via system prompt injection and Claude Code tool restrictions

### Agent Expertise
Persistent per-agent memory files in `expertise/` directory:
- Grow across sessions as agents learn
- Loaded into system prompts at startup
- Capped at configurable line limits

### Skills System
Shared markdown skill files injected into system prompts:
- `active_listener.md` — Read conversation context before responding
- `zero_micromanagement.md` — Delegate, don't execute
- `conversational_response.md` — Concise, natural responses
- `delegate.md` — How to format delegation blocks
- `mental_model.md` — How to maintain expertise files

## CLI Commands

| Command | Description |
|---------|-------------|
| `/toggle workers` | Show/hide detailed worker activity |
| `/cost` | Show cost breakdown by agent and team |
| `/teams` | Show team structure |
| `/expertise [agent]` | Show agent's expertise/mental model |
| `/compact` | Compress conversation history |
| `/clear` | Clear conversation |
| `/help` | Show all commands |
| `/quit` | Exit the harness |

## Configuration

Edit `configs/multi_team.yaml` to:
- Add/remove teams
- Change agent models
- Modify domain permissions
- Adjust expertise limits
- Assign skills to agents

## Project Structure

```
harness/
├── harness/              # Python package
│   ├── orchestrator.py   # Main orchestrator
│   ├── team.py           # Team management
│   ├── agent.py          # Individual agent execution
│   ├── config.py         # YAML config loader
│   ├── domain.py         # File permission enforcement
│   ├── expertise.py      # Expertise management
│   ├── skills.py         # Skills loading
│   ├── session.py        # Session logging
│   ├── delegate.py       # Delegation tool
│   ├── cli.py            # Interactive CLI
│   └── models.py         # Cost tracking
├── configs/              # YAML configurations
├── agents/               # Agent system prompts
├── skills/               # Skill markdown files
├── sessions/             # Session logs (auto-created)
├── expertise/            # Agent expertise (auto-created)
└── requirements.txt
```

## Requirements

- Python 3.11+
- Claude Code CLI installed and authenticated (`claude` command available)
- PyYAML, Rich, aiofiles

## How It Works

1. User types a message in the CLI
2. Orchestrator agent receives it and decides which team(s) to involve
3. Team leads receive delegated tasks and may delegate to workers
4. Workers execute via `claude -p` print mode
5. Results bubble back up through the hierarchy
6. Orchestrator synthesizes a final response

All inter-agent communication goes through the framework (not direct agent-to-agent). Costs are tracked across all invocations and displayed in the CLI.
