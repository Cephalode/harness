"""Reusable prompt commands — sequential team workflows."""
from __future__ import annotations
from typing import Any
from .config import CommandConfig


async def execute_command(
    command: CommandConfig,
    user_input: str,
    teams: dict,
) -> list[dict[str, Any]]:
    """Execute a command workflow: run each step's team in sequence.

    Args:
        command: The command configuration with steps.
        user_input: The original user message.
        teams: Dict of team_name -> Team objects.

    Returns:
        List of results from each step.
    """
    results: list[dict[str, Any]] = []
    prev_result = ""

    for step in command.steps:
        # Template substitution
        prompt = step.prompt_template.replace("{input}", user_input)
        prompt = prompt.replace("{prev_result}", prev_result)

        team = teams.get(step.team)
        if not team:
            results.append({
                "error": f"Team '{step.team}' not found",
                "step": step.team,
            })
            continue

        result = await team.execute(
            task=prompt,
            context=f"Step in workflow '{command.name}'",
        )
        results.append(result)
        prev_result = result.get("final_response", "")

    return results


def format_command_summary(command_name: str, results: list[dict[str, Any]]) -> str:
    """Format command results into a readable summary."""
    parts = [f"## Command: {command_name}"]
    for i, r in enumerate(results):
        team = r.get("team", "unknown")
        if r.get("error"):
            parts.append(f"### Step {i+1} ({team}) — Error\n{r['error']}")
        else:
            response = r.get("final_response", "No response")
            if len(response) > 500:
                response = response[:500] + "\n... (truncated)"
            parts.append(f"### Step {i+1} ({team})\n{response}")
    return "\n\n".join(parts)
