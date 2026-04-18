# Mental Model Management

How to maintain and grow your expertise across sessions.

## Purpose

Your expertise file is your persistent memory. It grows over time as you learn more about the project, codebase, and team dynamics. This makes you more effective with each session.

## What to Store

### Project Knowledge
- Key architectural decisions and their rationale
- Important file locations and module structure
- Frequently used patterns and conventions
- Known gotchas and pitfalls

### Session Learnings
- What worked well and what didn't
- Surprising discoveries about the codebase
- Feedback from other agents or the user
- Performance insights

### Working Preferences
- How the user likes things done
- Preferred coding style and patterns
- Communication preferences
- Priority areas of focus

## What NOT to Store

- Temporary or session-specific context
- Verbose code snippets (keep references, not copies)
- Information that changes frequently
- Personal opinions unrelated to the work

## Format

Use structured markdown with clear headers:

```markdown
## Architecture
- The project uses X pattern for Y

## Key Files
- src/api/auth.ts — Authentication middleware

## Conventions
- Always use async/await, never raw promises
- Tests go in tests/unit/ and tests/integration/

## Session Log
- 2024-01-15: Discovered that the cache module needs manual invalidation
```

## Growth Guidelines

- Add new insights after each significant task
- Remove outdated information when you discover it
- Keep the file under the configured line limit (older entries get trimmed)
- Focus on actionable knowledge that helps you be more effective
