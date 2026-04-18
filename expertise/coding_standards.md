# Coding Standards (Read-Only Reference)

This file contains domain-specific coding standards that agents can read but never modify.

## General Guidelines
- Follow PEP 8 for Python code
- Use type hints for all function signatures
- Write docstrings for all public modules, classes, and functions
- Keep functions under 50 lines; refactor longer ones into helpers

## Testing Standards
- Every feature must have at least one test
- Use pytest fixtures for common setup
- Mock external services; never hit real APIs in tests
- Aim for >80% code coverage on new code

## Git Standards
- Commit messages follow Conventional Commits format
- One logical change per commit
- Rebase feature branches before merge
