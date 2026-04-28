"""Team management — lead + workers with parallel execution support."""

from __future__ import annotations

import asyncio
import re
from typing import Any

from .agent import Agent
from .config import TeamConfig
from .delegate import DelegationTool
from .events import EventBus, HarnessEvent
from .models import CostTracker
from .rate_limiter import ConcurrencyLimiter
from .session import Session


# Pattern to match delegation blocks in agent responses
DELEGATE_BLOCK_PATTERN = re.compile(
    r"```delegate\s*\n(.*?)```",
    re.DOTALL,
)

DELEGATE_FIELD_PATTERN = {
    "to": re.compile(r"^to:\s*(.+)$", re.MULTILINE),
    "task": re.compile(r"^task:\s*(.+)$", re.MULTILINE),
    "context": re.compile(r"^context:\s*(.+)$", re.MULTILINE),
}


def parse_delegation_blocks(text: str) -> list[dict[str, str]]:
    """Parse delegation blocks from an agent's response text."""
    blocks = []
    for match in DELEGATE_BLOCK_PATTERN.finditer(text):
        block_text = match.group(1)
        dep: dict[str, str] = {}
        for field_name, pattern in DELEGATE_FIELD_PATTERN.items():
            m = pattern.search(block_text)
            if m:
                dep[field_name] = m.group(1).strip()
        if "to" in dep and "task" in dep:
            blocks.append(dep)
    return blocks


class Team:
    """Manages a team of agents (one lead + multiple workers)."""

    def __init__(
        self,
        config: TeamConfig,
        cost_tracker: CostTracker,
        base_dir: str = ".",
        session: Session | None = None,
        event_bus: EventBus | None = None,
        rate_limiter: ConcurrencyLimiter | None = None,
    ) -> None:
        self.config = config
        self.name = config.name
        self.color = config.color
        self.cost_tracker = cost_tracker
        self.base_dir = base_dir
        self.session = session
        self.event_bus = event_bus
        self.rate_limiter = rate_limiter

        # Create lead agent
        self.lead = Agent(
            config=config.lead,
            team_name=config.name,
            cost_tracker=cost_tracker,
            base_dir=base_dir,
            session=session,
            event_bus=event_bus,
            rate_limiter=rate_limiter,
        )

        # Create worker agents
        self.workers: dict[str, Agent] = {}
        for wcfg in config.workers:
            worker = Agent(
                config=wcfg,
                team_name=config.name,
                cost_tracker=cost_tracker,
                base_dir=base_dir,
                session=session,
                event_bus=event_bus,
                rate_limiter=rate_limiter,
            )
            self.workers[wcfg.name] = worker

        # Build delegation tool with all team members
        all_agents: dict[str, Agent] = {config.lead.name: self.lead}
        all_agents.update(self.workers)
        self.delegation_tool = DelegationTool(all_agents)

    @property
    def worker_names(self) -> list[str]:
        return list(self.workers.keys())

    async def execute(
        self,
        task: str,
        context: str = "",
        till_done: bool = True,
        max_rounds: int = 5,
    ) -> dict[str, Any]:
        """Execute a task through this team with till-done orchestration.

        1. Lead receives the task
        2. Lead may delegate to workers
        3. Workers execute in parallel
        4. Results go back to lead for review
        5. Loop until lead says DONE or max_rounds reached
        """
        all_worker_results: list[dict[str, Any]] = []
        round_num = 0
        lead_text = ""

        if self.event_bus:
            self.event_bus.emit(HarnessEvent("team_start", team=self.name, data={"task": task[:200], "till_done": till_done, "max_rounds": max_rounds}))

        while round_num < max_rounds:
            round_num += 1

            if round_num == 1:
                lead_result = await self.lead.run(
                    message=task,
                    context=context,
                )
            else:
                # Follow-up: ask lead to continue or wrap up
                prev_workers = all_worker_results[-1] if all_worker_results else []
                followup = (
                    f"Previous round completed. Results so far:\n"
                    f"{self._compile_result(lead_text, prev_workers)}\n\n"
                    f"If all tasks from the original request are complete, respond with:\n"
                    f"DONE: <summary>\n\n"
                    f"If not, delegate the remaining work to your workers."
                )
                lead_result = await self.lead.run(
                    message=followup,
                    context=task,
                )

            lead_text = lead_result.get("result", "")
            if isinstance(lead_text, dict):
                lead_text = str(lead_text)

            # Check if lead says done
            if till_done and lead_text.strip().upper().startswith("DONE:"):
                break

            # Parse delegation blocks from lead's response
            delegations = parse_delegation_blocks(lead_text)
            if not delegations and round_num > 1:
                # No delegation on follow-up = lead is done
                break
            if not delegations:
                break  # No delegation on first round = lead handled it directly

            # Emit delegation events
            if self.event_bus:
                for dep in delegations:
                    self.event_bus.emit(HarnessEvent("agent_start", agent=dep["to"], team=self.name, data={"task": dep["task"][:100], "delegated_by": self.lead.name}))

            # Execute worker delegations in parallel
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

        # Compile final result
        final_text = self._compile_result(lead_text, all_worker_results)

        # Update lead expertise
        self.lead.update_expertise(
            f"## Session Insight\nCoordinated team '{self.name}' on task: {task[:100]}"
        )

        if self.event_bus:
            self.event_bus.emit(HarnessEvent("team_done", team=self.name, data={"rounds": round_num, "workers_used": len(all_worker_results), "final_length": len(final_text)}))

        return {
            "team": self.name,
            "lead_response": lead_text,
            "worker_results": all_worker_results,
            "final_response": final_text,
            "workers_used": len(all_worker_results),
            "rounds": round_num,
        }

    def _compile_result(
        self,
        lead_text: str,
        worker_results: list[dict[str, Any]],
    ) -> str:
        """Compile lead + worker results into a final response."""
        parts: list[str] = []

        # Strip delegation blocks from lead text for display
        display_text = DELEGATE_BLOCK_PATTERN.sub("", lead_text).strip()
        if display_text:
            parts.append(f"[{self.lead.name}]: {display_text}")

        for i, wr in enumerate(worker_results):
            worker_text = wr.get("result", "")
            if worker_text:
                # Truncate very long worker responses
                if isinstance(worker_text, str) and len(worker_text) > 2000:
                    worker_text = worker_text[:2000] + "\n... (truncated)"
                parts.append(f"[Worker {i+1}]: {worker_text}")

        return "\n\n".join(parts)

    def format_team_info(self) -> str:
        """Format team information for display."""
        from rich.text import Text

        lines = [
            f"Team: {self.name} (color: {self.color})",
            f"  Lead: {self.lead.name} ({self.lead.model})",
        ]
        for wname, worker in self.workers.items():
            domain = worker.config.domain
            write_dirs = ", ".join(domain.update) if domain.update else "none"
            lines.append(f"  Worker: {wname} ({worker.model}) — write: {write_dirs}")
        return "\n".join(lines)
