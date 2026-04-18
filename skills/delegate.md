# Delegation Skill

How to effectively delegate tasks to other agents in the system.

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

### Context
- Provide relevant background information
- Include any dependencies or prerequisites
- Mention related work that's already been done
- Specify any non-obvious conventions to follow

### Multi-Agent Delegation

You can include multiple delegation blocks to trigger parallel execution:

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

## Agent Selection

Choose the right agent for the task:
- **planner** — For research, planning, and documentation
- **frontend_dev** — For UI/components/styles
- **backend_dev** — For APIs/models/services
- **qa_engineer** — For testing and quality assurance
- **security_reviewer** — For security analysis
