"""Run individual agent via pi -p print mode, parse JSON output, enforce domain permissions."""

from __future__ import annotations

import asyncio
import json
import re
import shlex
from typing import Any

from .config import AgentConfig
from .domain import DomainEnforcer
from .expertise import ExpertiseManager
from .events import EventBus, HarnessEvent
from .models import CostTracker, TokenUsage, parse_usage_from_pi_output
from .session import Session
from .skills import SkillLoader

STATUS_BLOCK_PATTERN = re.compile(r"```status\s*\nmessage:\s*(.+?)\n```", re.DOTALL)


class Agent:
    """Represents a single PI coding agent that runs via `pi -p`."""

    def __init__(
        self,
        config: AgentConfig,
        team_name: str | None = None,
        cost_tracker: CostTracker | None = None,
        base_dir: str = ".",
        session: Session | None = None,
        event_bus: EventBus | None = None,
    ) -> None:
        self.config = config
        self.team_name = team_name
        self.cost_tracker = cost_tracker or CostTracker()
        self.base_dir = base_dir
        self.session = session
        self.event_bus = event_bus

        self.domain_enforcer = DomainEnforcer(config.domain, base_dir)
        self.expertise_manager = ExpertiseManager(base_dir)
        self.skill_loader = SkillLoader(base_dir)

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def model(self) -> str:
        return self.config.model

    def _build_system_prompt(self) -> str:
        """Build the full system prompt including skills, expertise, and domain rules."""
        parts: list[str] = []

        # Load base system prompt
        from pathlib import Path
        prompt_path = Path(self.base_dir) / self.config.system_prompt
        if prompt_path.exists():
            parts.append(prompt_path.read_text(encoding="utf-8").strip())
        else:
            parts.append(f"[System prompt not found: {self.config.system_prompt}]")

        # Load and inject skills
        if self.config.skills:
            skills_text = self.skill_loader.load_many(self.config.skills)
            if skills_text:
                parts.append(skills_text)

        # Load and inject expertise
        if self.config.expertise:
            expertise_text = self.expertise_manager.format_expertise_section(self.config.expertise)
            if expertise_text:
                parts.append(expertise_text)

        # Inject domain rules
        parts.append(self.domain_enforcer.format_domain_rules())

        # Inject status reporting instruction
        parts.append(
            "## Status Reporting\n\n"
            "You are running inside a multi-agent orchestration harness with a live dashboard. "
            "When you begin working on a NEW subtask or phase of your work, output a status line "
            "in this exact format at the START of your response (before any other output):\n\n"
            "```status\n"
            "message: <brief description of what you're about to do>\n"
            "```\n\n"
            "For example:\n"
            "- ```status\nmessage: Reading the main.py file to understand the codebase\n```\n"
            "- ```status\nmessage: Writing unit tests for the auth module\n```\n"
            "- ```status\nmessage: Analyzing the error log to find root cause\n```\n\n"
            "This status is displayed on a live dashboard so your operator can see what you're doing. "
            "Always emit a status update when your focus shifts to a new activity."
        )

        return "\n\n---\n\n".join(parts)

    def _build_prompt(self, user_message: str, context: str = "") -> str:
        """Build the full prompt to send to pi."""
        # Include conversation context if available
        conversation_context = ""
        if self.session:
            conv_text = self.session.get_conversation_text(max_messages=20)
            if conv_text:
                conversation_context = f"\n\n## Conversation So Far\n\n{conv_text}"

        if context:
            context_section = f"\n\n## Context from Delegation\n\n{context}"
        else:
            context_section = ""

        return (
            f"## Your Task\n\n"
            f"{user_message}"
            f"{context_section}"
            f"{conversation_context}"
        )

    async def run(
        self,
        message: str,
        context: str = "",
        timeout: int = 300,
    ) -> dict[str, Any]:
        """Run this agent with the given message, return parsed output."""
        system_prompt = self._build_system_prompt()
        prompt = self._build_prompt(message, context)

        models_to_try = [self.model] + self.config.fallback_models

        if self.event_bus:
            self.event_bus.emit(HarnessEvent("agent_start", agent=self.name, team=self.team_name, data={"model": models_to_try[0], "message_length": len(message)}))

        for i, model in enumerate(models_to_try):
            # Build the pi CLI command (prompt piped via stdin, not -p flag)
            cmd = [
                "pi",
                "--system-prompt", system_prompt,
                "--mode", "json",
            ]

            # Only add --model if specified (otherwise PI uses its default provider/model)
            if model:
                cmd.extend(["--model", model])

            # Restrict tools based on domain - workers that shouldn't write get read-only
            if self.config.domain.update and "." not in self.config.domain.update:
                cmd.extend(["--tools", "read,bash"])

            result = await self._execute_pi(cmd, prompt, timeout)

            # Success = no error and non-empty result
            if not result.get("error") and result.get("result", "").strip():
                if self.event_bus:
                    self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"model": result.get("model", model), "status": "success", "result_length": len(result.get("result", ""))}))
                # Parse and emit worker status updates
                if self.event_bus and result.get("result"):
                    result_text = result["result"]
                    if isinstance(result_text, str):
                        status_matches = STATUS_BLOCK_PATTERN.findall(result_text)
                        for status_msg in status_matches:
                            self.event_bus.emit(HarnessEvent(
                                "worker_status",
                                agent=self.name,
                                team=self.team_name,
                                data={"message": status_msg.strip()},
                            ))
                        # Clean status blocks from result
                        result["result"] = STATUS_BLOCK_PATTERN.sub("", result_text).strip()
                return result

            # Failure but no more models to try
            if i >= len(models_to_try) - 1:
                if self.event_bus:
                    self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "all_models_failed"}))
                return result

            # Try next model
            continue

        if self.event_bus:
            self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "all_models_failed"}))
        return {"error": "all models failed", "result": "All model attempts failed", "usage": {}}

    async def _execute_pi(
        self, cmd: list[str], prompt_text: str, timeout: int,
    ) -> dict[str, Any]:
        """Execute pi CLI command with prompt piped via stdin, parse JSONL output."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.base_dir,
            )
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(input=prompt_text.encode("utf-8")),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()  # type: ignore
            return {
                "error": "timeout",
                "result": f"Agent {self.name} timed out after {timeout}s",
                "usage": {},
            }

        stdout_text = stdout.decode("utf-8", errors="replace").strip()
        stderr_text = stderr.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "error": f"exit code {proc.returncode}",
                "result": stderr_text or stdout_text,
                "usage": {},
            }

        # Parse PI's JSONL output (newline-delimited JSON events)
        result_text = ""
        usage_data = {}
        model_used = self.model
        provider = ""

        for line in stdout_text.split("\n"):
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
                event_type = event.get("type", "")

                if event_type == "agent_end":
                    # Extract final assistant message text
                    messages = event.get("messages", [])
                    for msg in messages:
                        if msg.get("role") == "assistant":
                            for content in msg.get("content", []):
                                if content.get("type") == "text":
                                    result_text = content.get("text", "")

                elif event_type == "turn_end":
                    # Extract usage/cost from the final message
                    msg = event.get("message", {})
                    usage_data = msg.get("usage", {})
                    model_used = msg.get("model", model_used)
                    provider = msg.get("provider", "")

            except json.JSONDecodeError:
                # If we can't parse JSON, the text mode output is the result
                if not result_text:
                    result_text = line

        if not result_text:
            result_text = stdout_text

        # Build output dict (similar to claude format for compatibility)
        output = {
            "result": result_text,
            "usage": usage_data,
            "model": model_used,
            "provider": provider,
        }

        # Track cost
        usage = parse_usage_from_pi_output(output)
        self.cost_tracker.record(
            agent_name=self.name,
            team_name=self.team_name,
            model=model_used,
            usage=usage,
        )

        return output

    def update_expertise(self, insights: str) -> None:
        """Update the agent's expertise file with new insights."""
        for exp_cfg in self.config.expertise:
            if exp_cfg.updatable:
                self.expertise_manager.append_insight(exp_cfg, insights)
