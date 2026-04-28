"""Per-model concurrency limiter to prevent API 429 rate limit errors.

Uses asyncio.Semaphore to queue agent executions when the model's concurrency
limit is reached. Models from different providers are tracked independently.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# z-ai concurrency limits from https://docs.z.ai/devpack/overview
# Format: normalized model name (lowercase, no prefix) → max concurrent requests
Z_AI_LIMITS: dict[str, int] = {
    "glm-4.6": 3,
    "glm-4.6v-flashx": 3,
    "glm-4.7": 2,
    "glm-4.5": 10,
    "glm-4.6v": 10,
    "glm-4.7v": 10,
    "glm-5-turbo": 1,
    "glm-5v-turbo": 1,
    "glm-5.1": 1,
    "glm-4.7-flash": 1,
    "glm-4.7-flashx": 3,
    "glm-ocr": 2,
    "glm-5": 2,
    "glm-4-plus": 20,
    "glm-4.5v": 10,
    "glm-4.6v-flash": 1,
    "glm-4.5-air": 5,
    "glm-4.5-airx": 5,
    "glm-4.5-flash": 2,
    "glm-4-32b-0414-128k": 15,
}

# Default concurrency for models not in the known limits (conservative)
DEFAULT_CONCURRENCY = 2

# Conservative defaults for non-z-ai providers
PROVIDER_DEFAULTS: dict[str, int] = {
    "opencode-go": 3,  # conservative estimate
}


def normalize_model_name(model: str) -> str:
    """Strip provider prefix and lowercase a model identifier.
    
    "z-ai/glm-5.1" → "glm-5.1"
    "opencode-go/kimi-k2.5" → "kimi-k2.5"
    "glm-4.7-flashx" → "glm-4.7-flashx"
    """
    if "/" in model:
        return model.split("/", 1)[1].lower()
    return model.lower()


def get_concurrency_limit(model: str) -> int:
    """Get the concurrency limit for a model string (with or without provider prefix).
    
    Looks up z-ai limits by normalized name, falls back to provider defaults,
    then to DEFAULT_CONCURRENCY.
    """
    normalized = normalize_model_name(model)
    
    # Direct lookup in z-ai limits
    if normalized in Z_AI_LIMITS:
        return Z_AI_LIMITS[normalized]
    
    # Provider-based default
    if "/" in model:
        provider = model.split("/", 1)[0].lower()
        if provider in PROVIDER_DEFAULTS:
            return PROVIDER_DEFAULTS[provider]
    
    return DEFAULT_CONCURRENCY


@dataclass
class Waiter:
    """Tracks a single agent waiting for a model slot."""
    agent_name: str
    model: str
    team: str | None = None
    enqueued_at: float = field(default_factory=time.time)
    started_at: float | None = None


class ConcurrencyLimiter:
    """Per-model concurrency limiter using asyncio.Semaphore.
    
    Thread-safe within a single asyncio event loop. Usage:
    
        limiter = ConcurrencyLimiter()
        async with limiter.acquire("z-ai/glm-5.1", agent_name="orchestrator"):
            result = await agent._execute_pi(cmd, prompt, timeout)
    
    Or use the lower-level acquire/release if you can't use context manager.
    """

    def __init__(self) -> None:
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._limits: dict[str, int] = {}
        self._active: dict[str, list[Waiter]] = {}  # model → list of currently running
        self._queue: dict[str, list[Waiter]] = {}    # model → list of waiting
        self._lock = asyncio.Lock()

    def _get_semaphore(self, model: str) -> asyncio.Semaphore:
        """Get or create a semaphore for the given model."""
        normalized = normalize_model_name(model)
        if normalized not in self._semaphores:
            limit = get_concurrency_limit(model)
            self._semaphores[normalized] = asyncio.Semaphore(limit)
            self._limits[normalized] = limit
            self._active[normalized] = []
            self._queue[normalized] = []
        return self._semaphores[normalized]

    async def acquire(self, model: str, agent_name: str = "", team: str | None = None) -> None:
        """Acquire a concurrency slot for the given model. Blocks if at limit.
        
        Logs when an agent has to wait, and when it starts.
        """
        sem = self._get_semaphore(model)
        normalized = normalize_model_name(model)
        
        # Check if we'd need to wait
        waiter = Waiter(agent_name=agent_name, model=model, team=team)
        
        if sem._value <= 0:  # type: ignore[attr-defined]
            # Will need to wait — log and track in queue
            self._queue.setdefault(normalized, []).append(waiter)
            logger.info(
                "⏳ %s queued for %s (limit=%d, active=%d, waiting=%d)",
                agent_name or "agent", normalized, 
                self._limits.get(normalized, DEFAULT_CONCURRENCY),
                len(self._active.get(normalized, [])),
                len(self._queue[normalized]),
            )
        
        await sem.acquire()
        waiter.started_at = time.time()
        self._active.setdefault(normalized, []).append(waiter)
        
        # Remove from queue if it was there
        if normalized in self._queue:
            self._queue[normalized] = [
                w for w in self._queue[normalized] 
                if w.agent_name != agent_name or w.enqueued_at != waiter.enqueued_at
            ]
        
        wait_time = waiter.started_at - waiter.enqueued_at
        if wait_time > 0.5:
            logger.info(
                "▶️ %s started on %s after waiting %.1fs",
                agent_name, normalized, wait_time,
            )

    def release(self, model: str, agent_name: str = "") -> None:
        """Release a concurrency slot for the given model."""
        normalized = normalize_model_name(model)
        sem = self._semaphores.get(normalized)
        if sem is None:
            return
        
        # Remove from active list
        if normalized in self._active:
            self._active[normalized] = [
                w for w in self._active[normalized]
                if w.agent_name != agent_name
            ]
        
        sem.release()
        
        remaining = len(self._queue.get(normalized, []))
        if remaining > 0:
            logger.info(
                "✅ %s released %s — %d still queued",
                agent_name, normalized, remaining,
            )

    def get_status(self) -> dict[str, Any]:
        """Return current concurrency status for all known models."""
        status = {}
        for normalized, limit in self._limits.items():
            active = self._active.get(normalized, [])
            queued = self._queue.get(normalized, [])
            status[normalized] = {
                "limit": limit,
                "active": len(active),
                "queued": len(queued),
                "available": limit - len(active),
                "active_agents": [
                    {"name": w.agent_name, "team": w.team, "started_at": w.started_at}
                    for w in active
                ],
                "queued_agents": [
                    {"name": w.agent_name, "team": w.team, "waiting_since": w.enqueued_at}
                    for w in queued
                ],
            }
        return status

    class _AcquireContext:
        """Context manager for acquire/release."""
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

    def slot(self, model: str, agent_name: str = "", team: str | None = None) -> _AcquireContext:
        """Context manager: acquire a slot, auto-release on exit.
        
        Usage:
            async with limiter.slot("z-ai/glm-5.1", "orchestrator"):
                result = await agent._execute_pi(cmd, prompt, timeout)
        """
        return self._AcquireContext(self, model, agent_name, team)
