"""Main orchestrator — receives user messages and delegates to team leads."""

from __future__ import annotations

import asyncio
from typing import Any

from .agent import Agent
from .config import HarnessConfig, TeamConfig, TeamInstanceConfig
from .delegate import DelegationTool
from .models import CostTracker
from .session import Session
from .team import Team


class Orchestrator:
    """Central orchestrator that routes user messages to appropriate teams."""

    def __init__(
        self,
        config: HarnessConfig,
        cost_tracker: CostTracker | None = None,
        session: Session | None = None,
    ) -> None:
        self.config = config
        self.base_dir = config.base_dir
        self.cost_tracker = cost_tracker or CostTracker()
        self.session = session or Session(sessions_dir=str(self._resolve_path("sessions")))

        # Create orchestrator agent
        self.agent = Agent(
            config=config.orchestrator,
            team_name=None,
            cost_tracker=self.cost_tracker,
            base_dir=self.base_dir,
            session=self.session,
        )

        # Create teams (expand instances into separate Team objects)
        self.teams: dict[str, Team] = {}
        for tcfg in config.teams:
            if tcfg.instances:
                for inst in tcfg.instances:
                    team = self._create_team_instance(tcfg, inst)
                    self.teams[inst.name] = team
            else:
                team = Team(
                    config=tcfg,
                    cost_tracker=self.cost_tracker,
                    base_dir=self.base_dir,
                    session=self.session,
                )
                self.teams[tcfg.name] = team

    def _resolve_path(self, relative: str) -> str:
        return f"{self.base_dir}/{relative}"

    def _create_team_instance(
        self, base_config: TeamConfig, instance: TeamInstanceConfig
    ) -> Team:
        """Create a Team from a base config with instance-specific overrides."""
        import copy

        cfg = copy.deepcopy(base_config)
        cfg.name = instance.name
        cfg.instances = []  # instances don't carry over to expanded teams
        # Apply model overrides
        overrides = instance.model_overrides
        if cfg.lead and cfg.lead.name in overrides:
            cfg.lead.model = overrides[cfg.lead.name]
        for w in cfg.workers:
            if w.name in overrides:
                w.model = overrides[w.name]
        return Team(
            config=cfg,
            cost_tracker=self.cost_tracker,
            base_dir=self.base_dir,
            session=self.session,
        )

    async def process_message(self, user_message: str) -> str:
        """Process a user message through the orchestration pipeline.

        1. Send to orchestrator agent to decide which teams to involve
        2. Execute team(s) in parallel if multiple
        3. Send results back to orchestrator for final synthesis
        """
        # Log user message
        self.session.add_message(
            role="user",
            content=user_message,
        )

        # Check if message matches a command workflow
        command_name = None
        command_input = user_message
        words = user_message.split()
        if words and ":" in words[0]:
            candidate = words[0].rstrip(":")
            if candidate in self.config.commands:
                command_name = candidate
                command_input = " ".join(words[1:])

        if command_name:
            from .commands import execute_command, format_command_summary
            cmd = self.config.commands[command_name]
            results = await execute_command(cmd, command_input, self.teams)
            summary = format_command_summary(command_name, results)

            self.session.add_message(
                role="assistant",
                content=summary,
                agent="orchestrator",
            )
            return summary

        # Step 1: Orchestrator decides routing
        team_names = list(self.teams.keys())
        routing_prompt = (
            f"{user_message}\n\n"
            f"## Available Teams\n"
            + "\n".join(f"- {name}: {team.config.lead.name}" for name, team in self.teams.items())
            + "\n\nDecide which team(s) should handle this request. "
            "Respond with ONLY a JSON object: {\"teams\": [\"team_name\", ...], \"rationale\": \"...\"}"
        )

        routing_result = await self.agent.run(
            message=routing_prompt,
        )

        routing_text = routing_result.get("result", "")
        if isinstance(routing_text, dict):
            routing_text = str(routing_text)

        # Parse routing decision
        selected_teams = self._parse_team_selection(routing_text)

        if not selected_teams:
            # If no teams selected, use the orchestrator's direct response
            self.session.add_message(
                role="assistant",
                content=routing_text,
                agent="orchestrator",
            )
            return routing_text

        # Step 2: Execute selected teams in parallel
        team_tasks = []
        for team_name in selected_teams:
            team = self.teams.get(team_name)
            if team:
                team_tasks.append(team.execute(
                    task=user_message,
                    context=f"Orchestrator routed this task to the {team_name} team.",
                ))

        team_results = await asyncio.gather(*team_tasks)

        # Step 3: Synthesize results through orchestrator
        synthesis_context = self._format_team_results(team_results)

        synthesis_prompt = (
            f"The following teams have completed their work on the user's request: "
            f"'{user_message[:200]}'\n\n"
            f"## Team Results\n\n{synthesis_context}\n\n"
            f"Please synthesize these results into a clear, concise response for the user."
        )

        synthesis_result = await self.agent.run(
            message=synthesis_prompt,
        )

        final_response = synthesis_result.get("result", "")
        if isinstance(final_response, dict):
            final_response = str(final_response)

        # Log assistant response
        self.session.add_message(
            role="assistant",
            content=final_response,
            agent="orchestrator",
        )

        # Log team results
        for tr in team_results:
            team_name = tr.get("team", "unknown")
            self.session.add_message(
                role="agent",
                content=tr.get("final_response", ""),
                agent=team_name,
                team=team_name,
            )

        # Update orchestrator expertise
        self.agent.update_expertise(
            f"## Orchestration Insight\n"
            f"Handled request via teams: {', '.join(selected_teams)}"
        )

        return final_response

    def _parse_team_selection(self, routing_text: str) -> list[str]:
        """Parse team selection from orchestrator's routing response."""
        import json
        import re

        # Try to extract JSON from the response
        json_match = re.search(r'\{[^}]+\}', routing_text, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group())
                teams = data.get("teams", [])
                # Validate team names
                return [t for t in teams if t in self.teams]
            except json.JSONDecodeError:
                pass

        # Fallback: look for team names in text
        found = []
        for team_name in self.teams:
            if team_name.lower() in routing_text.lower():
                found.append(team_name)
        return found

    def _format_team_results(self, results: list[dict[str, Any]]) -> str:
        """Format team results for synthesis."""
        parts: list[str] = []
        for r in results:
            team_name = r.get("team", "unknown")
            final = r.get("final_response", "No response")
            workers_used = r.get("workers_used", 0)
            parts.append(
                f"### {team_name.title()} Team ({workers_used} workers used)\n\n{final}"
            )
        return "\n\n".join(parts)

    def get_cost_summary(self) -> str:
        """Get a formatted cost summary."""
        return self.cost_tracker.format_summary()

    def get_team_info(self) -> str:
        """Get formatted information about all teams."""
        parts: list[str] = []
        for team in self.teams.values():
            parts.append(team.format_team_info())
        return "\n\n".join(parts)
