"""Model definitions and cost tracking for PI coding agent invocations."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any


# Pricing per 1M tokens (USD) — approximate
MODEL_PRICING: dict[str, dict[str, float]] = {
    # Anthropic
    "claude-opus-4-6": {"input": 15.0, "output": 75.0},
    "claude-sonnet-4-6": {"input": 3.0, "output": 15.0},
    "claude-haiku-3-5": {"input": 0.80, "output": 4.0},
    # OpenAI
    "gpt-4o": {"input": 2.50, "output": 10.0},
    "gpt-4o-mini": {"input": 0.15, "output": 0.60},
    # Google
    "gemini-2.5-pro": {"input": 1.25, "output": 10.0},
    "gemini-2.5-flash": {"input": 0.15, "output": 0.60},
    # Z.ai / GLM
    "glm-5.1": {"input": 0.0, "output": 0.0},  # Free tier
    "glm-5": {"input": 0.0, "output": 0.0},
    "glm-5-turbo": {"input": 0.0, "output": 0.0},
    "glm-4.7-flashx": {"input": 0.0, "output": 0.0},
    "glm-4.7-flash": {"input": 0.0, "output": 0.0},
    "glm-4.5-flash": {"input": 0.0, "output": 0.0},  # FREE
    "glm-4.6v": {"input": 0.0, "output": 0.0},  # Vision
    "glm-4.6v-flash": {"input": 0.0, "output": 0.0},  # FREE vision
    "glm-4.7v": {"input": 0.0, "output": 0.0},  # Vision
    # OpenCode-go models
    "kimi-k2.5": {"input": 0.0, "output": 0.0},
    "minimax-m2.7": {"input": 0.0, "output": 0.0},
    "qwen3.6-plus": {"input": 0.0, "output": 0.0},
    "mimo-v2-pro": {"input": 0.0, "output": 0.0},
    # Ollama (local, free)
    "qwen3.5:latest": {"input": 0.0, "output": 0.0},
    # Default
    "default": {"input": 3.0, "output": 15.0},
}


@dataclass
class TokenUsage:
    """Token usage for a single agent invocation."""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0


@dataclass
class CostRecord:
    """A single cost record for an agent invocation."""
    agent_name: str
    team_name: str | None
    model: str
    usage: TokenUsage
    cost_usd: float
    timestamp: float = field(default_factory=time.time)


class CostTracker:
    """Tracks costs across all agent invocations."""

    def __init__(self) -> None:
        self.records: list[CostRecord] = []

    def record(
        self,
        agent_name: str,
        team_name: str | None,
        model: str,
        usage: TokenUsage,
    ) -> CostRecord:
        """Record a cost entry and return it."""
        cost = self._calculate_cost(model, usage)
        rec = CostRecord(
            agent_name=agent_name,
            team_name=team_name,
            model=model,
            usage=usage,
            cost_usd=cost,
        )
        self.records.append(rec)
        return rec

    def _calculate_cost(self, model: str, usage: TokenUsage) -> float:
        """Calculate USD cost for given model and usage."""
        # Strip provider prefix (e.g. "z-ai/glm-5.1" → "glm-5.1")
        bare_model = model.split("/")[-1] if "/" in model else model
        pricing = MODEL_PRICING.get(bare_model, MODEL_PRICING.get(model, MODEL_PRICING["default"]))
        input_cost = (usage.input_tokens / 1_000_000) * pricing["input"]
        output_cost = (usage.output_tokens / 1_000_000) * pricing["output"]
        # Cache tokens are cheaper (10% of input price)
        cache_create_cost = (usage.cache_creation_input_tokens / 1_000_000) * pricing["input"] * 1.25
        cache_read_cost = (usage.cache_read_input_tokens / 1_000_000) * pricing["input"] * 0.1
        return input_cost + output_cost + cache_create_cost + cache_read_cost

    @property
    def total_cost(self) -> float:
        """Total cost across all invocations."""
        return sum(r.cost_usd for r in self.records)

    @property
    def total_usage(self) -> TokenUsage:
        """Aggregate token usage."""
        total = TokenUsage()
        for r in self.records:
            total.input_tokens += r.usage.input_tokens
            total.output_tokens += r.usage.output_tokens
            total.cache_creation_input_tokens += r.usage.cache_creation_input_tokens
            total.cache_read_input_tokens += r.usage.cache_read_input_tokens
        return total

    def cost_by_team(self) -> dict[str | None, float]:
        """Cost aggregated by team."""
        by_team: dict[str | None, float] = {}
        for r in self.records:
            by_team[r.team_name] = by_team.get(r.team_name, 0.0) + r.cost_usd
        return by_team

    def cost_by_agent(self) -> dict[str, float]:
        """Cost aggregated by agent."""
        by_agent: dict[str, float] = {}
        for r in self.records:
            by_agent[r.agent_name] = by_agent.get(r.agent_name, 0.0) + r.cost_usd
        return by_agent

    def format_summary(self) -> str:
        """Format a human-readable cost summary."""
        lines = [
            f"[bold]Total Cost:[/bold] ${self.total_cost:.4f}",
            f"[bold]Total Tokens:[/bold] {self.total_usage.input_tokens:,} in / {self.total_usage.output_tokens:,} out",
            "",
            "[bold]By Agent:[/bold]",
        ]
        for name, cost in sorted(self.cost_by_agent().items(), key=lambda x: -x[1]):
            lines.append(f"  {name}: ${cost:.4f}")
        lines.append("")
        lines.append("[bold]By Team:[/bold]")
        for team, cost in sorted(self.cost_by_team().items(), key=lambda x: -x[1]):
            label = team or "orchestrator"
            lines.append(f"  {label}: ${cost:.4f}")
        return "\n".join(lines)


def parse_usage_from_pi_output(output: dict[str, Any]) -> TokenUsage:
    """Extract token usage from PI JSON output.

    PI turn_end events have usage like:
    {
        "usage": {
            "input": 20,
            "output": 74,
            "cacheRead": 11968,
            "cacheWrite": 0,
            "totalTokens": 12062,
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0, "total": 0}
        }
    }
    """
    usage = TokenUsage()
    raw_usage = output.get("usage", {})
    if isinstance(raw_usage, dict):
        usage.input_tokens = raw_usage.get("input", 0)
        usage.output_tokens = raw_usage.get("output", 0)
        usage.cache_creation_input_tokens = raw_usage.get("cacheWrite", 0)
        usage.cache_read_input_tokens = raw_usage.get("cacheRead", 0)
    return usage


# Backward compat alias
parse_usage_from_claude_output = parse_usage_from_pi_output
