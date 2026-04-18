"""Delegation tool — agents use this to call other agents within the system."""

from __future__ import annotations

from typing import Any

from .agent import Agent
from .config import AgentConfig


class DelegationTool:
    """Provides delegation capability so agents can invoke other agents.

    This is used by team leads to delegate work to their workers,
    and by the orchestrator to delegate to team leads.
    """

    def __init__(self, agents: dict[str, Agent]) -> None:
        self.agents = agents

    def get_agent(self, name: str) -> Agent | None:
        """Look up an agent by name."""
        return self.agents.get(name)

    async def delegate(
        self,
        from_agent: str,
        to_agent: str,
        task: str,
        context: str = "",
    ) -> dict[str, Any]:
        """Delegate a task from one agent to another.

        Args:
            from_agent: Name of the delegating agent.
            to_agent: Name of the target agent.
            task: The task description.
            context: Additional context from the delegating agent.

        Returns:
            The result from the target agent.
        """
        target = self.agents.get(to_agent)
        if target is None:
            return {
                "error": f"Agent '{to_agent}' not found",
                "result": f"Cannot delegate to unknown agent: {to_agent}",
            }

        # Add delegation context
        delegation_context = (
            f"Delegated by: {from_agent}\n"
            f"{context}"
        )

        result = await target.run(
            message=task,
            context=delegation_context,
        )

        # If there's useful output, let the target agent update its expertise
        if "result" in result and result["result"] and not result.get("error"):
            output_text = result["result"]
            if isinstance(output_text, str) and len(output_text) > 50:
                target.update_expertise(
                    f"## Session Insight\nCompleted delegated task: {task[:100]}"
                )

        return result

    async def delegate_parallel(
        self,
        from_agent: str,
        delegations: list[dict[str, str]],
    ) -> list[dict[str, Any]]:
        """Delegate to multiple agents in parallel.

        Args:
            from_agent: Name of the delegating agent.
            delegations: List of dicts with 'to_agent', 'task', and optional 'context'.

        Returns:
            List of results from all agents.
        """
        import asyncio

        tasks = []
        for dep in delegations:
            tasks.append(
                self.delegate(
                    from_agent=from_agent,
                    to_agent=dep["to_agent"],
                    task=dep["task"],
                    context=dep.get("context", ""),
                )
            )
        return await asyncio.gather(*tasks)

    def format_delegation_instructions(self, available_agents: list[str]) -> str:
        """Format instructions for how an agent should delegate."""
        agents_list = "\n".join(f"  - {name}" for name in available_agents)
        return (
            "## Delegation Instructions\n\n"
            "You have the ability to delegate tasks to other agents. "
            "To delegate, include a delegation block in your response:\n\n"
            "```delegate\n"
            "to: <agent_name>\n"
            "task: <task description>\n"
            "context: <additional context>\n"
            "```\n\n"
            "Available agents:\n"
            f"{agents_list}\n\n"
            "You can delegate to multiple agents by including multiple delegation blocks. "
            "Workers will execute in parallel when possible.\n"
        )
