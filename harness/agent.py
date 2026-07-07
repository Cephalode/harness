"""Run individual agent via pi -p print mode, parse JSON output, enforce domain permissions."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shlex
from typing import Any

from .config import AgentConfig
from .domain import DomainEnforcer
from .expertise import ExpertiseManager
from .events import EventBus, HarnessEvent
from .models import CostTracker, TokenUsage, parse_usage_from_pi_output
from .rate_limiter import ConcurrencyLimiter, SlotAllocator, normalize_model_name
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
        rate_limiter: ConcurrencyLimiter | None = None,
        slot_allocator: SlotAllocator | None = None,
    ) -> None:
        self.config = config
        self.team_name = team_name
        self.cost_tracker = cost_tracker or CostTracker()
        self.base_dir = base_dir
        self.session = session
        self.event_bus = event_bus
        self.rate_limiter = rate_limiter
        self.slot_allocator = slot_allocator

        self._worker_names: list[str] = []

        self.domain_enforcer = DomainEnforcer(config.domain, base_dir)
        self.expertise_manager = ExpertiseManager(base_dir)
        self.skill_loader = SkillLoader(base_dir)

    def set_available_workers(self, names: list[str]) -> None:
        """Set the list of available worker names for delegation injection."""
        self._worker_names = names

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

        # Inject vision-specific instructions for image analysis agents
        if self.config.vision:
            parts.append(
                "## CRITICAL: Vision Mode\n\n"
                "You are a VISION agent. Images are attached DIRECTLY to your input as visual content.\n"
                "You must ANALYZE the images visually — do NOT use the `read` tool or any other tool to open them.\n"
                "The images are already rendered in your conversation. Just look at them and describe what you see.\n"
                "NEVER attempt to read image files with tools. NEVER use bash to inspect images.\n"
                "Simply respond with your visual analysis as text."
            )

        # Inject status reporting instruction (skip for vision agents — they
        # do single-pass analysis and the status instruction causes weaker
        # vision models to stop after emitting just the status block)
        if not self.config.vision:
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

        # Inject delegation instructions if workers are configured
        if self._worker_names:
            workers_list = "\n".join(f"  - {name}" for name in self._worker_names)
            parts.append(
                "## CRITICAL: Delegation Protocol\n\n"
                "You MUST delegate work to your workers. Do NOT do the work yourself.\n"
                "To delegate, include fenced code blocks with the `delegate` language tag in your response:\n\n"
                "```delegate\n"
                "to: <worker_name>\n"
                "task: <clear, specific task description>\n"
                "context: <additional context the agent needs>\n"
                "```\n\n"
                f"Your available workers:\n{workers_list}\n\n"
                "### Slot Rationing\n\n"
                "**Each worker you delegate to consumes an LLM slot.** Slots are limited — "
                "the flagship pool (glm-5.1) is ~10 slots shared across all teams. "
                "If you delegate too many workers in parallel, some will be degraded to weaker models automatically.\n\n"
                "**Guidelines:**\n"
                "- Prefer fewer, well-scoped delegations over many parallel ones\n"
                "- For critical tasks, delegate sequentially so the best model is available\n"
                "- For independent low-priority tasks, parallel delegation is fine\n"
                "- You can include multiple delegation blocks for parallel execution\n\n"
                "ALWAYS use the delegate code block format. Do not describe delegation in prose.\n"
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
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Run this agent with the given message, return parsed output.

        If a SlotAllocator is configured, the agent must acquire a slot
        before running. If the preferred model is full, the allocator will
        degrade to a weaker model with available capacity.

        Args:
            message: The task/message for the agent.
            context: Additional context from delegation.
            timeout: Max seconds to wait for the executor response.
            image_paths: Local file paths to images. Only passed to PI
                when this agent has vision=true.
        """
        system_prompt = self._build_system_prompt()
        prompt = self._build_prompt(message, context)

        # ── Claude Code executor ────────────────────────────────────
        if self.config.executor == "claude-code":
            if self.event_bus:
                self.event_bus.emit(HarnessEvent(
                    "agent_start",
                    agent=self.name,
                    team=self.team_name,
                    data={"model": self.model, "executor": "claude-code", "message_length": len(message)},
                ))
            result = await self._execute_claude_code(system_prompt, prompt, timeout, image_paths=image_paths)
            if self.event_bus:
                status = "error" if result.get("error") else "success"
                self.event_bus.emit(HarnessEvent(
                    "agent_end",
                    agent=self.name,
                    team=self.team_name,
                    data={"model": result.get("model", self.model), "executor": "claude-code", "status": status, "result_length": len(result.get("result", ""))},
                ))
            return result

        # ── PI executor (default) ────────────────────────────────────

        # ── Slot allocation (rationing) ──────────────────────────────
        # If we have a slot allocator, use it to get the best available
        # model *before* we even try to run. This is the rationing gate.
        allocated_model: str | None = None
        allocation_result = None

        if self.slot_allocator:
            allocation_result = await self.slot_allocator.allocate(
                preferred=self.model,
                fallback_models=self.config.fallback_models,
                agent_name=self.name,
                team=self.team_name,
            )
            allocated_model = allocation_result.model

            # Emit degradation event so the dashboard can show it
            if allocation_result.degraded and self.event_bus:
                self.event_bus.emit(HarnessEvent(
                    "model_degradation",
                    agent=self.name,
                    team=self.team_name,
                    data={
                        "original_model": allocation_result.original_model,
                        "allocated_model": allocated_model,
                        "reason": "no_slots_available",
                    },
                ))
            elif allocation_result.queued and self.event_bus:
                self.event_bus.emit(HarnessEvent(
                    "model_queued",
                    agent=self.name,
                    team=self.team_name,
                    data={
                        "model": allocated_model,
                        "wait_seconds": allocation_result.wait_seconds,
                    },
                ))

            # Use the allocated model as the primary; keep fallback_models
            # for error-based fallback (API failure, timeout, etc.)
            models_to_try = [allocated_model]
            # Add config fallbacks that aren't the allocated model
            for fb in self.config.fallback_models:
                if normalize_model_name(fb) != normalize_model_name(allocated_model):
                    models_to_try.append(fb)
        else:
            # No allocator — original behavior: try preferred then fallbacks
            models_to_try = [self.model] + self.config.fallback_models

        if self.event_bus:
            self.event_bus.emit(HarnessEvent("agent_start", agent=self.name, team=self.team_name, data={"model": models_to_try[0], "message_length": len(message)}))

        result = None
        try:
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
                # Vision agents: disable ALL tools. They analyze attached images directly
                # and should never try to read/write files or run bash commands.
                # (--no-tools also prevents the coding agent from treating images as files to read)
                if self.config.vision:
                    cmd.extend(["--no-tools", "--no-skills", "--no-extensions"])
                elif self.config.domain.update and "." not in self.config.domain.update:
                    cmd.extend(["--tools", "read,bash"])

                # ── Vision: attach image files for vision-capable agents ──
                if image_paths and self.config.vision:
                    for img_path in image_paths:
                        if os.path.isfile(img_path):
                            cmd.extend([f"@{img_path}"])

                try:
                    # If we already have a slot from the allocator, skip the
                    # rate_limiter.slot() context (the allocator handles it).
                    # Otherwise, fall back to the old rate_limiter path.
                    if self.slot_allocator and i == 0:
                        result = await self._execute_pi(cmd, prompt, timeout)
                    elif self.rate_limiter:
                        async with self.rate_limiter.slot(model, agent_name=self.name, team=self.team_name):
                            result = await self._execute_pi(cmd, prompt, timeout)
                    else:
                        result = await self._execute_pi(cmd, prompt, timeout)
                except Exception as exc:
                    if self.event_bus:
                        self.event_bus.emit(HarnessEvent("agent_error", agent=self.name, team=self.team_name, data={"error": str(exc), "model": model}))
                    result = {"error": str(exc), "result": f"Agent {self.name} crashed: {exc}", "usage": {}}

                # Success = no error and non-empty result
                if not result.get("error") and result.get("result", "").strip():
                    if self.event_bus:
                        self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"model": result.get("model", model), "status": "success", "result_length": len(result.get("result", ""))}))
                    return result

                # Failure but no more models to try
                if i >= len(models_to_try) - 1:
                    if self.event_bus:
                        self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "error", "reason": "all_models_failed"}))
                    return result

                # Try next model
                continue

            if self.event_bus:
                self.event_bus.emit(HarnessEvent("agent_end", agent=self.name, team=self.team_name, data={"status": "error", "reason": "all_models_failed"}))
            return {"error": "all models failed", "result": "All model attempts failed", "usage": {}}
        finally:
            # Always release the allocated slot when done (success or failure)
            if self.slot_allocator and allocated_model:
                self.slot_allocator.release(allocated_model, self.name)

    async def _execute_pi(
        self, cmd: list[str], prompt_text: str, timeout: int,
    ) -> dict[str, Any]:
        """Execute pi CLI command with prompt piped via stdin, parse JSONL
        output in real-time, emitting worker_status events as status blocks
        appear during execution."""
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.base_dir,
            )
        except Exception as exc:
            return {
                "error": f"spawn failed: {exc}",
                "result": f"Agent {self.name} failed to start: {exc}",
                "usage": {},
            }

        # Write prompt to stdin and close it
        try:
            proc.stdin.write(prompt_text.encode("utf-8"))  # type: ignore[union-attr]
            await proc.stdin.drain()  # type: ignore[union-attr]
            proc.stdin.close()  # type: ignore[union-attr]
        except Exception as exc:
            proc.kill()
            return {
                "error": f"stdin write failed: {exc}",
                "result": f"Agent {self.name} stdin error: {exc}",
                "usage": {},
            }

        # Stream stdout line-by-line with overall timeout
        result_text = ""
        usage_data: dict[str, Any] = {}
        model_used = self.model
        provider = ""
        streaming_text = ""
        emitted_statuses: set[str] = set()
        stderr_chunks: list[str] = []

        async def _drain_stderr() -> None:
            if proc.stderr:
                while True:
                    chunk = await proc.stderr.read(4096)
                    if not chunk:
                        break
                    stderr_chunks.append(chunk.decode("utf-8", errors="replace"))

        try:
            stderr_task = asyncio.create_task(_drain_stderr())

            async def _stream_stdout() -> None:
                nonlocal result_text, usage_data, model_used, provider, streaming_text
                if proc.stdout is None:
                    return
                async for raw_line in proc.stdout:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                        event_type = event.get("type", "")

                        if event_type == "message_update":
                            ame = event.get("assistantMessageEvent", {})
                            if ame.get("type") == "text_delta":
                                delta = ame.get("text", "")
                                streaming_text += delta
                                # Real-time status block detection
                                if self.event_bus and "```status" in streaming_text:
                                    matches = STATUS_BLOCK_PATTERN.findall(streaming_text)
                                    for status_msg in matches:
                                        status_key = status_msg.strip()
                                        if status_key not in emitted_statuses:
                                            emitted_statuses.add(status_key)
                                            self.event_bus.emit(HarnessEvent(
                                                "worker_status",
                                                agent=self.name,
                                                team=self.team_name,
                                                data={"message": status_key},
                                            ))

                        elif event_type == "agent_end":
                            messages = event.get("messages", [])
                            for msg in messages:
                                if msg.get("role") == "assistant":
                                    for content in msg.get("content", []):
                                        if content.get("type") == "text":
                                            result_text = content.get("text", "")

                        elif event_type == "turn_end":
                            msg = event.get("message", {})
                            usage_data = msg.get("usage", {})
                            model_used = msg.get("model", model_used)
                            provider = msg.get("provider", "")

                    except json.JSONDecodeError:
                        if not result_text:
                            result_text = line

            await asyncio.wait_for(_stream_stdout(), timeout=timeout)

            # Wait for process exit (short extra wait)
            try:
                await asyncio.wait_for(proc.wait(), timeout=30)
            except asyncio.TimeoutError:
                proc.kill()

            await stderr_task

        except asyncio.TimeoutError:
            proc.kill()
            return {
                "error": "timeout",
                "result": f"Agent {self.name} timed out after {timeout}s",
                "usage": {},
            }

        stderr_text = "".join(stderr_chunks).strip()

        if proc.returncode != 0:
            return {
                "error": f"exit code {proc.returncode}",
                "result": stderr_text or streaming_text,
                "usage": {},
            }

        # Strip status blocks from final result
        if result_text:
            result_text = STATUS_BLOCK_PATTERN.sub("", result_text).strip()

        if not result_text:
            result_text = streaming_text or ""

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

    async def _execute_claude_code(
        self, system_prompt: str, prompt: str, timeout: int,
        image_paths: list[str] | None = None,
    ) -> dict[str, Any]:
        """Execute Claude Code CLI (`claude -p`) and parse JSON output.

        Claude Code manages its own API credentials and rate limiting,
        so no slot allocation or rate limiter integration is needed.

        Vision agents (self.config.vision=True) receive image file paths
        and use a restricted tool set (Read only) with an explicit
        vision-capable model.
        """
        # If images were provided, append their paths so Claude Code can
        # view them via the Read tool (which handles images natively).
        if image_paths:
            existing_paths = [p for p in image_paths if os.path.isfile(p)]
            if existing_paths:
                prompt += "\n\nAttached image files: " + ", ".join(existing_paths)

        # Build the claude command — prompt passed via -p flag, system
        # prompt appended to preserve Claude Code's built-in capabilities.
        if getattr(self.config, "vision", False):
            allowed_tools = "Read"
            cmd = [
                "claude",
                "-p", shlex.quote(prompt),
                "--append-system-prompt", shlex.quote(system_prompt),
                "--output-format", "json",
                "--max-turns", "10",
                "--model", "claude-sonnet-4-6",
                "--allowedTools", allowed_tools,
                "--dangerously-skip-permissions",
            ]
        else:
            allowed_tools = "Read,Edit,Write,Bash"
            cmd = [
                "claude",
                "-p", shlex.quote(prompt),
                "--append-system-prompt", shlex.quote(system_prompt),
                "--output-format", "json",
                "--max-turns", "20",
                "--allowedTools", allowed_tools,
                "--dangerously-skip-permissions",
            ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdin=asyncio.subprocess.DEVNULL,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=self.base_dir,
            )
        except Exception as exc:
            return {
                "error": f"spawn failed: {exc}",
                "result": f"Agent {self.name} failed to start: {exc}",
                "usage": {},
            }

        try:
            stdout_bytes, stderr_bytes = await asyncio.wait_for(
                proc.communicate(), timeout=timeout,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            return {
                "error": "timeout",
                "result": f"Agent {self.name} timed out after {timeout}s",
                "usage": {},
            }

        stderr_text = stderr_bytes.decode("utf-8", errors="replace").strip()
        stdout_text = stdout_bytes.decode("utf-8", errors="replace").strip()

        if proc.returncode != 0:
            return {
                "error": f"exit code {proc.returncode}",
                "result": stderr_text or stdout_text or f"Agent {self.name} exited with code {proc.returncode}",
                "usage": {},
            }

        # Parse Claude Code's JSON output (single JSON object)
        try:
            result_data = json.loads(stdout_text)
        except json.JSONDecodeError:
            return {
                "error": "json_parse_error",
                "result": stdout_text or stderr_text,
                "usage": {},
            }

        result_text = result_data.get("result", "")

        # Strip status blocks from result
        if result_text:
            result_text = STATUS_BLOCK_PATTERN.sub("", result_text).strip()

        # Convert Claude Code usage to PI-compatible TokenUsage format
        raw_usage = result_data.get("usage", {})
        usage_dict = {
            "input": raw_usage.get("input_tokens", 0),
            "output": raw_usage.get("output_tokens", 0),
            "cacheWrite": raw_usage.get("cache_creation_input_tokens", 0),
            "cacheRead": raw_usage.get("cache_read_input_tokens", 0),
        }

        # Determine the model name from output (Claude Code may report
        # the actual model it used, e.g. "claude-sonnet-4-6").
        model_used = self.model
        model_usage = result_data.get("modelUsage", {})
        if model_usage:
            # Pick the first key as the actual model used
            model_used = next(iter(model_usage.keys()), self.model)

        output = {
            "result": result_text,
            "usage": usage_dict,
            "model": model_used,
            "provider": "claude-code",
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
