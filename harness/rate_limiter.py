"""Per-model rate limiting for Z.AI API concurrency.

Single provider (z-ai) with hard concurrency limits via asyncio.Semaphore.
SlotAllocator implements rationing: if the preferred model is full, degrades
to a weaker model with available capacity, queuing only as last resort.

Models:
  glm-5.1      — flagship (10 concurrent)
  glm-4.7      — workhorse (2 concurrent)
  glm-4.5-air  — budget/overflow (5 concurrent)
  glm-5-turbo  — reserved for Ocythoe only, NOT used by harness agents
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ─── z-ai concurrency limits (simultaneous requests) ────────────────
# Coding Plan Pro subscription — single provider
Z_AI_CONCURRENCY: dict[str, int] = {
    # Coding plan models — primary pool
    "glm-5.1": 10,
    "glm-4.7": 2,
    "glm-4.5-air": 5,
    # glm-5-turbo: reserved for Ocythoe (not in harness config)
    "glm-5-turbo": 2,
    # Other z-ai models (vision, legacy — lower priority)
    "glm-5": 2,
    "glm-4.7-flashx": 3,
    "glm-4.7-flash": 3,
    "glm-4.7v": 10,       # Vision — free, generous
    "glm-4.6v": 10,
    "glm-4.6v-flashx": 3,
    "glm-4.6v-flash": 3,
    "glm-5v-turbo": 2,
    "glm-4.6": 3,
    "glm-4.5": 5,
    "glm-4.5-airx": 5,
    "glm-4.5-flash": 5,
    "glm-4.5v": 5,
    "glm-ocr": 2,
    "glm-4-plus": 20,
    "glm-4-32b-0414-128k": 15,
}

DEFAULT_CONCURRENCY = 2


def normalize_model_name(model: str) -> str:
    """Strip provider prefix and lowercase.
    "z-ai/glm-5.1" → "glm-5.1"
    """
    if "/" in model:
        return model.split("/", 1)[1].lower()
    return model.lower()


def get_provider(model: str) -> str:
    """Extract provider from model string. "z-ai/glm-5.1" → "z-ai" """
    if "/" in model:
        return model.split("/", 1)[0].lower()
    return ""


@dataclass
class Waiter:
    """Tracks a single agent waiting for a slot."""
    agent_name: str
    model: str
    team: str | None = None
    enqueued_at: float = field(default_factory=time.time)
    started_at: float | None = None


class ConcurrencyLimiter:
    """Per-model concurrency limiter using asyncio.Semaphore.

    Usage:
        limiter = ConcurrencyLimiter()
        async with limiter.slot("z-ai/glm-5.1", agent_name="orchestrator"):
            result = await agent._execute_pi(cmd, prompt, timeout)
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._limits: dict[str, int] = {}
        self._active: dict[str, list[Waiter]] = {}
        self._queue: dict[str, list[Waiter]] = {}

    def _get_semaphore(self, model: str) -> asyncio.Semaphore:
        normalized = normalize_model_name(model)
        if normalized not in self._semaphores:
            limit = Z_AI_CONCURRENCY.get(normalized, DEFAULT_CONCURRENCY)
            self._semaphores[normalized] = asyncio.Semaphore(limit)
            self._limits[normalized] = limit
            self._active.setdefault(normalized, [])
            self._queue.setdefault(normalized, [])
        return self._semaphores[normalized]

    async def acquire(self, model: str, agent_name: str = "", team: str | None = None) -> None:
        """Acquire a slot for the given model. Queues if at limit."""
        normalized = normalize_model_name(model)
        waiter = Waiter(agent_name=agent_name, model=model, team=team)
        sem = self._get_semaphore(model)

        if sem._value <= 0:  # type: ignore[attr-defined]
            self._queue.setdefault(normalized, []).append(waiter)
            logger.info(
                "⏳ %s queued for %s (concurrency limit=%d)",
                waiter.agent_name or "agent", normalized,
                self._limits.get(normalized, DEFAULT_CONCURRENCY),
            )

        await sem.acquire()
        waiter.started_at = time.time()
        self._active.setdefault(normalized, []).append(waiter)

        # Remove from queue
        self._queue[normalized] = [
            w for w in self._queue.get(normalized, [])
            if w.agent_name != waiter.agent_name or w.enqueued_at != waiter.enqueued_at
        ]

        wait_time = waiter.started_at - waiter.enqueued_at
        if wait_time > 0.5:
            logger.info(
                "▶️ %s started on %s after waiting %.1fs",
                waiter.agent_name, normalized, wait_time,
            )

    def release(self, model: str, agent_name: str = "") -> None:
        """Release a slot."""
        normalized = normalize_model_name(model)

        # Remove from active
        if normalized in self._active:
            self._active[normalized] = [
                w for w in self._active[normalized]
                if w.agent_name != agent_name
            ]

        # Release semaphore
        sem = self._semaphores.get(normalized)
        if sem:
            sem.release()
            remaining = len(self._queue.get(normalized, []))
            if remaining > 0:
                logger.info(
                    "✅ %s released %s — %d still queued",
                    agent_name, normalized, remaining,
                )

    def get_status(self) -> dict[str, Any]:
        """Return current rate limit status for all tracked models."""
        status = {}
        for normalized, limit in self._limits.items():
            active = self._active.get(normalized, [])
            queued = self._queue.get(normalized, [])
            status[f"z-ai/{normalized}"] = {
                "provider": "z-ai",
                "type": "concurrency",
                "limit": limit,
                "active": len(active),
                "queued": len(queued),
                "available": limit - len(active),
                "active_agents": [
                    {"name": w.agent_name, "team": w.team}
                    for w in active
                ],
            }
        return status

    class _SlotContext:
        """Async context manager for acquire/release."""
        def __init__(self, limiter: ConcurrencyLimiter, model: str, agent_name: str, team: str | None):
            self._limiter = limiter
            self._model = model
            self._agent_name = agent_name
            self._team = team

        async def __aenter__(self):
            await self._limiter.acquire(self._model, self._agent_name, self._team)
            return self

        async def __aexit__(self, *args):
            self._limiter.release(self._model, self._agent_name)

    def slot(self, model: str, agent_name: str = "", team: str | None = None) -> _SlotContext:
        """Context manager: acquire a slot, auto-release on exit."""
        return self._SlotContext(self, model, agent_name, team)

    # ─── Slot availability queries ──────────────────────────────────

    def available_slots(self, model: str) -> int:
        """Return the number of currently available slots for a model."""
        normalized = normalize_model_name(model)
        sem = self._semaphores.get(normalized)
        if sem:
            return sem._value  # type: ignore[attr-defined]
        # Not yet tracked — return the configured limit
        return Z_AI_CONCURRENCY.get(normalized, DEFAULT_CONCURRENCY)

    def is_available(self, model: str) -> bool:
        """Check if at least one slot is available for the given model."""
        return self.available_slots(model) > 0


# ─── Model tier ranking (for degradation cascade) ─────────────────────
# Higher tier number = stronger model. When rationing kicks in, the
# allocator tries the next tier down until it finds a model with free slots.
MODEL_TIERS: dict[str, int] = {
    # Primary coding plan models
    "glm-5.1": 10,
    "glm-4.7": 6,
    "glm-4.5-air": 2,
    # Other z-ai models
    "glm-5": 9,
    "glm-5-turbo": 8,
    "glm-5v-turbo": 8,
    "glm-4.7v": 6,
    "glm-4.7-flashx": 5,
    "glm-4.7-flash": 4,
    "glm-4.6": 3,
    "glm-4.6v": 3,
    "glm-4.6v-flashx": 3,
    "glm-4.5-airx": 2,
    "glm-4.6v-flash": 2,
    "glm-4.5-flash": 1,
    "glm-4.5v": 1,
    "glm-4-32b-0414-128k": 1,
    "glm-ocr": 1,
}

# Degradation cascade for z-ai: ordered strongest to weakest
_ZAI_CASCADE: list[str] = [
    "glm-5.1", "glm-4.7", "glm-4.5-air",
]


@dataclass
class AllocationResult:
    """Result of a slot allocation attempt."""
    model: str                  # The model that was actually allocated
    original_model: str         # The model that was originally requested
    degraded: bool              # True if a weaker model was substituted
    queued: bool                # True if had to wait (no alternative had slots)
    wait_seconds: float = 0.0


class SlotAllocator:
    """Rationing system: allocates LLM slots with automatic degradation.

    Before a subagent can run, it must call ``allocate()`` to get a slot.
    If the preferred model has no available slots, the allocator walks down
    the tier list, and only queues as a last resort.

    Usage::

        allocator = SlotAllocator(limiter)
        result = await allocator.allocate(
            preferred="z-ai/glm-5.1",
            fallback_models=["z-ai/glm-4.7", "z-ai/glm-4.5-air"],
            agent_name="engineering_lead",
            team="engineering",
        )
        # result.model might be "z-ai/glm-4.7" if glm-5.1 was full
        # ... run agent with result.model ...
        allocator.release(result.model, "engineering_lead")
    """

    def __init__(
        self,
        limiter: ConcurrencyLimiter,
        max_queue_wait: float = 120.0,
        queue_poll_interval: float = 2.0,
    ) -> None:
        self._limiter = limiter
        self._max_queue_wait = max_queue_wait
        self._queue_poll_interval = queue_poll_interval
        self._allocations: dict[str, list[dict[str, Any]]] = {}

    async def allocate(
        self,
        preferred: str,
        fallback_models: list[str] | None = None,
        agent_name: str = "",
        team: str | None = None,
    ) -> AllocationResult:
        """Allocate a slot, degrading to weaker models if necessary.

        Strategy:
        1. Try the preferred model — if a slot is free, take it immediately.
        2. Walk the degradation cascade: preferred → config fallback_models →
           same-provider weaker models.
        3. Take the first model with an available slot.
        4. If nothing is free, queue on the preferred model (respects max wait).

        Args:
            preferred: The model the agent ideally wants to use.
            fallback_models: Agent-specific fallback list from config.
            agent_name: Name of the requesting agent (for logging/tracking).
            team: Team name (for logging/tracking).

        Returns:
            AllocationResult with the allocated model and degradation info.
        """
        preferred_norm = normalize_model_name(preferred)
        preferred_tier = MODEL_TIERS.get(preferred_norm, 5)

        # Build degradation cascade
        cascade = self._build_cascade(
            preferred=preferred,
            preferred_norm=preferred_norm,
            preferred_tier=preferred_tier,
            fallback_models=fallback_models or [],
        )

        # Step 1 & 2: Try each model in the cascade for an available slot
        for candidate in cascade:
            if self._limiter.is_available(candidate):
                await self._limiter.acquire(candidate, agent_name, team)
                self._track_allocation(candidate, agent_name, team)
                degraded = normalize_model_name(candidate) != preferred_norm
                if degraded:
                    logger.info(
                        "📉 %s degraded from %s → %s (slots available)",
                        agent_name, preferred, candidate,
                    )
                return AllocationResult(
                    model=candidate,
                    original_model=preferred,
                    degraded=degraded,
                    queued=False,
                )

        # Step 3: All alternatives full — queue on preferred model
        logger.warning(
            "🚫 %s: all models in cascade full, queuing on %s (max wait %.0fs)",
            agent_name, preferred, self._max_queue_wait,
        )
        start = time.time()
        await asyncio.wait_for(
            self._limiter.acquire(preferred, agent_name, team),
            timeout=self._max_queue_wait,
        )
        wait_seconds = time.time() - start
        self._track_allocation(preferred, agent_name, team)

        logger.info(
            "✅ %s acquired %s after queuing %.1fs",
            agent_name, preferred, wait_seconds,
        )
        return AllocationResult(
            model=preferred,
            original_model=preferred,
            degraded=False,
            queued=True,
            wait_seconds=wait_seconds,
        )

    def release(self, model: str, agent_name: str = "") -> None:
        """Release an allocated slot."""
        self._limiter.release(model, agent_name)
        self._remove_allocation(model, agent_name)

    def _build_cascade(
        self,
        preferred: str,
        preferred_norm: str,
        preferred_tier: int,
        fallback_models: list[str],
    ) -> list[str]:
        """Build ordered list of models to try, strongest first."""
        seen: set[str] = {preferred_norm}
        cascade: list[str] = [preferred]

        # 1. Config fallback models (in order — these are from multi_team.yaml)
        for fb in fallback_models:
            fb_norm = normalize_model_name(fb)
            if fb_norm not in seen:
                seen.add(fb_norm)
                cascade.append(fb)

        # 2. Same-provider models weaker than preferred, sorted by tier desc
        weaker_same = [
            (MODEL_TIERS.get(m, 0), m) for m in _ZAI_CASCADE
            if m not in seen and MODEL_TIERS.get(m, 0) < preferred_tier
        ]
        for _, model_name in sorted(weaker_same, reverse=True):
            if model_name not in seen:
                seen.add(model_name)
                cascade.append(f"z-ai/{model_name}")

        return cascade

    def _track_allocation(self, model: str, agent_name: str, team: str | None) -> None:
        """Track current allocations for the /slots command."""
        normalized = normalize_model_name(model)
        entry = {"agent": agent_name, "team": team, "model": model, "allocated_at": time.time()}
        self._allocations.setdefault(normalized, []).append(entry)

    def _remove_allocation(self, model: str, agent_name: str) -> None:
        """Remove a tracked allocation."""
        normalized = normalize_model_name(model)
        if normalized in self._allocations:
            self._allocations[normalized] = [
                a for a in self._allocations[normalized] if a["agent"] != agent_name
            ]

    def get_status(self) -> dict[str, Any]:
        """Return allocation status for dashboard / CLI display."""
        limiter_status = self._limiter.get_status()
        return {
            "limiter": limiter_status,
            "allocations": self._allocations,
        }

    def format_slots(self) -> str:
        """Format a human-readable slot allocation table."""
        from rich.table import Table
        from rich.text import Text

        table = Table(title="LLM Slot Allocation", show_lines=True)
        table.add_column("Model", style="bold")
        table.add_column("Provider")
        table.add_column("Type")
        table.add_column("Slots", justify="right")
        table.add_column("Active", justify="right", style="green")
        table.add_column("Allocated To")

        limiter_status = self._limiter.get_status()
        for model_key, info in sorted(limiter_status.items()):
            provider = info["provider"]
            slots_str = f"{info['available']}/{info['limit']}"

            active = info["active"]
            active_agents = ", ".join(
                a["name"] for a in info["active_agents"]
            ) or "—"

            table.add_row(
                model_key,
                provider,
                info["type"],
                slots_str,
                str(active),
                active_agents,
            )

        return str(table)
