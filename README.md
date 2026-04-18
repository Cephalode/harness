# Multi-Team Agentic Coding Harness

A multi-team agent orchestration system where specialized teams of AI agents collaborate on software engineering tasks through a three-tier delegation architecture: **Orchestrator → Team Leads → Workers**.

Agents run via the [PI coding agent](https://github.com/mariozechner/pi) CLI.

## Quick Start

```bash
# Clone
git clone https://github.com/Cephalode/harness.git
cd harness

# Install dependencies
pip install pyyaml rich aiofiles

# Make sure PI is installed and configured
pi --version

# Run the harness
python -m harness.cli
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

## How It Works

1. You type a message in the CLI
2. Orchestrator agent decides which team(s) to involve
3. Team leads receive delegated tasks and may further delegate to workers
4. Workers execute via `pi -p` (PI print mode)
5. Results bubble back up through the hierarchy
6. Orchestrator synthesizes a final response

All inter-agent communication goes through the framework. Costs are tracked across all invocations and displayed after each response.

## Usage Examples

```
# Simple ping
You: ping
→ Orchestrator responds: Pong!

# Ask a specific team
You: @engineering present a tree structure of the most important files
→ Orchestrator routes to engineering team
→ Engineering lead delegates to backend_dev or frontend_dev
→ Worker reads files and returns tree
→ Orchestrator synthesizes and responds

# Ask all teams for perspectives
You: ask all teams what are two additional classifiers we should test
→ Orchestrator delegates to planning, engineering, and validation
→ All three teams work in parallel
→ Each team lead may delegate to their workers
→ Orchestrator collects all results and gives unified response

# Plan, build, validate workflow
You: plan, engineer, then validate: add user authentication
→ Planning team creates the plan
→ Engineering team implements it
→ Validation team tests and reviews
→ Orchestrator gives final summary
```

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
- Add/remove teams and workers
- Change agent models (use PI's `provider/model` format, or leave empty for default)
- Modify domain permissions (which dirs each agent can read/write)
- Adjust expertise limits
- Assign skills to agents

### Changing Models

```yaml
# Use PI's default (from ~/.pi/agent/settings.json)
model: ""

# Specific provider/model
model: "anthropic/claude-opus-4-6"
model: "openai/gpt-4o"
model: "google/gemini-2.5-pro"
model: "z-ai/glm-5.1"
model: "ollama/qwen3.5:latest"
```

### Adding a Team

```yaml
teams:
  - name: devops
    color: yellow
    lead:
      name: devops_lead
      model: ""
      system_prompt: agents/devops_lead.md
      expertise:
        - path: expertise/devops_lead.md
          updatable: true
          max_lines: 5000
      skills:
        - skills/active_listener.md
        - skills/zero_micromanagement.md
        - skills/mental_model.md
      domain:
        read: ["."]
        update: ["expertise/", "deploy/", ".github/workflows/"]
    workers:
      - name: infra_engineer
        model: ""
        system_prompt: agents/infra_engineer.md
        domain:
          read: ["."]
          update: ["deploy/", "terraform/", ".github/"]
```

Then create the agent prompt file (`agents/devops_lead.md`, `agents/infra_engineer.md`) and you're done.

## Key Concepts

### Domain Locking
Each agent has scoped file permissions:
- **Read access**: What directories an agent can read
- **Write access**: What directories an agent can modify
- Enforced via system prompt injection and PI tool restrictions

### Agent Expertise
Persistent per-agent memory files in `expertise/` directory:
- Grow across sessions as agents learn
- Loaded into system prompts at startup
- Capped at configurable line limits

### Skills System
Shared markdown skill files injected into system prompts:
- `active_listener.md` — Read conversation context before responding
- `zero_micromanagement.md` — Delegate, don't execute (for leads)
- `conversational_response.md` — Concise, natural responses
- `delegate.md` — How to format delegation blocks
- `mental_model.md` — How to maintain expertise files

## Project Structure

```
harness/
├── harness/              # Python package
│   ├── orchestrator.py   # Main orchestrator
│   ├── team.py           # Team management
│   ├── agent.py          # Individual agent execution via PI
│   ├── config.py         # YAML config loader
│   ├── domain.py         # File permission enforcement
│   ├── expertise.py      # Expertise management
│   ├── skills.py         # Skills loading
│   ├── session.py        # Session logging (JSONL)
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
- [PI coding agent](https://github.com/mariozechner/pi) installed and configured (`pi` command available)
- PyYAML, Rich, aiofiles
