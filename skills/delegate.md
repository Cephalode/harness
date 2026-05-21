# Delegation Skill

How to effectively delegate tasks to other agents in the system.

## Slot Rationing

The harness uses a **slot rationing system** — every agent must acquire an LLM slot before it can run. Slots are limited per model:

- **Strong models** (e.g., `glm-5.1`, `kimi-k2.5`) have very few concurrent slots (often just 1)
- **Weaker models** (e.g., `glm-4.7-flashx`, `glm-4.5-flash`) have more slots available

If no slot is available on the requested model, the system automatically **degrades** the agent to a weaker model that has capacity. This means:

- **Be intentional about parallel delegation.** Each parallel worker consumes a slot. If you delegate 3 workers at once and the strong models only have 1 slot each, some workers will run on degraded (weaker) models.
- **Prioritize your delegation.** For tasks where quality matters most, delegate sequentially so the best model is available. For independent tasks where speed matters more, parallel delegation is fine — some workers may run on slightly weaker models.
- **Fewer, better delegations beat many parallel ones.** A single well-scoped task to one worker on a strong model will produce better results than splitting it across 3 workers where 2 get degraded.

## Delegation Format

Use fenced code blocks with the `delegate` language tag:

```delegate
to: <agent_name>
task: <clear, specific task description>
context: <additional context the agent needs>
```

## Best Practices

### Task Description
- Be specific about what needs to be done
- Include acceptance criteria when possible
- Reference specific files or components by name
- State any constraints or requirements
- **Scope tasks tightly** — a focused task on a strong model beats a broad task on a degraded one

### Context
- Provide relevant background information
- Include any dependencies or prerequisites
- Mention related work that's already been done
- Specify any non-obvious conventions to follow

### Multi-Agent Delegation

You can include multiple delegation blocks to trigger parallel execution, but remember each one consumes an LLM slot:

```delegate
to: frontend_dev
task: Implement the login form component
context: Should integrate with the auth API. See API docs at docs/auth.md.
```

```delegate
to: backend_dev
task: Create the POST /api/auth/login endpoint
context: Must return JWT token. Follow existing auth patterns in src/api/auth.ts.
```

**Tip:** If these tasks are independent, parallel is fine. But if the backend task is more critical, consider delegating it first and waiting for the result before delegating the frontend task — this ensures the backend gets a strong model slot.

## Agent Selection

Choose the right agent for the task:
- **research_lead** — For coordinating research and investigation tasks
- **deep_researcher** — For technology research, library evaluation, documentation synthesis
- **code_investigator** — For codebase analysis, call chain tracing, dependency mapping
- **planner** — For research, planning, and documentation
- **frontend_dev** — For UI/components/styles
- **backend_dev** — For APIs/models/services
- **browser_harness_agent** — For browser automation, E2E testing, visual verification
- **qa_engineer** — For testing and quality assurance
- **security_reviewer** — For security analysis
- **visual_reviewer** — For visual analysis, screenshot review, UI verification
