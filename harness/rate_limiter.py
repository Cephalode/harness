"""Per-model rate limiting for API provider concurrency and rate limits.

Two provider types:
- z-ai: hard concurrency limits (simultaneous requests) via asyncio.Semaphore
- opencode-go: rate limits (requests per time window) via sliding window counter
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
# From https://docs.z.ai/devpack/overview
# Coding plan models: GLM-5.1, GLM-5-Turbo, GLM-4.7, GLM-4.5-Air
# Other models listed for fallback compatibility
Z_AI_CONCURRENCY: dict[str, int] = {
    # Coding plan models
    "glm-5.1": 1,
    "glm-5-turbo": 1,
    "glm-4.7": 2,
    "glm-4.5-air": 5,
    # Other z-ai models (may not be on coding plan)
    "glm-5": 2,
    "glm-4.5-airx": 5,
    "glm-4.7-flash": 1,
    "glm-4.7-flashx": 3,
    "glm-4.6": 3,
    "glm-4.6v-flashx": 3,
    "glm-4.5": 10,
    "glm-4.6v": 10,
    "glm-4.7v": 10,
    "glm-5v-turbo": 1,
    "glm-ocr": 2,
    "glm-4-plus": 20,
    "glm-4.5v": 10,
    "glm-4.6v-flash": 1,
    "glm-4.5-flash": 2,
    "glm-4-32b-0414-128k": 15,
}


# ─── opencode-go rate limits (requests per time window) ─────────────
# Safety margin: only use 85% of the limit to avoid hitting the hard cap
_SAFETY = 0.85

# 5-hour window limits (tightest constraint = primary limit)
OPENCODE_GO_RATE_LIMITS: dict[str, int] = {
    "glm-5.1": int(880 * _SAFETY),      # 748
    "glm-5": int(1150 * _SAFETY),        # 977
    "kimi-k2.5": int(1850 * _SAFETY),    # 1572
    "kimi-k2.6": int(1150 * _SAFETY),    # 977
    "mimo-v2-pro": int(1290 * _SAFETY),  # 1096
    "mimo-v2-omni": int(2150 * _SAFETY), # 1827
    "mimo-v2.5-pro": int(1290 * _SAFETY),
    "mimo-v2.5": int(2150 * _SAFETY),
    "minimax-m2.7": int(3400 * _SAFETY), # 2890
    "minimax-m2.5": int(6300 * _SAFETY),
    "qwen3.6-plus": int(3300 * _SAFETY), # 2805
    "qwen3.5-plus": int(10200 * _SAFETY),
    "deepseek-v4-pro": int(3450 * _SAFETY),
    "deepseek-v4-flash": int(31650 * _SAFETY),
}

_FIVE_HOURS = 5 * 60 * 60  # seconds

DEFAULT_CONCURRENCY = 2
DEFAULT_RATE_LIMIT = 500  # conservative default for unknown opencode-go models


def normalize_model_name(model: str) -> str:
    """Strip provider prefix and lowercase.
    "z-ai/glm-5.1" → "glm-5.1"
    "opencode-go/kimi-k2.5" → "kimi-k2.5"
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


class SlidingWindowCounter:
    """Tracks request count in a sliding time window."""

    def __init__(self, window_seconds: float) -> None:
        self._window = window_seconds
        self._timestamps: list[float] = []

    def record(self) -> None:
        """Record a request at the current time."""
        now = time.time()
        self._timestamps.append(now)
        self._purge(now)

    def count(self) -> int:
        """Get count of requests in the current window."""
        self._purge(time.time())
        return len(self._timestamps)

    def remaining(self, limit: int) -> int:
        """How many more requests can be made within the limit."""
        return max(0, limit - self.count())

    def earliest_expiry(self) -> float | None:
        """When the oldest request in the window expires (for sleep calculation)."""
        now = time.time()
        self._purge(now)
        if not self._timestamps:
            return None
        return self._timestamps[0] + self._window

    def _purge(self, now: float) -> None:
        """Remove timestamps outside the window."""
        cutoff = now - self._window
        self._timestamps = [t for t in self._timestamps if t > cutoff]


class ConcurrencyLimiter:
    """Dual-mode rate limiter: semaphore for z-ai, sliding window for opencode-go.

    Usage:
        limiter = ConcurrencyLimiter()
        async with limiter.slot("z-ai/glm-5.1", agent_name="orchestrator"):
            result = await agent._execute_pi(cmd, prompt, timeout)
    """

    def __init__(self) -> None:
        # z-ai: concurrency semaphores
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._limits: dict[str, int] = {}

        # opencode-go: sliding window counters
        self._rate_counters: dict[str, SlidingWindowCounter] = {}
        self._rate_limits: dict[str, int] = {}

        # Tracking
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

    def _get_rate_counter(self, model: str) -> tuple[SlidingWindowCounter, int]:
        normalized = normalize_model_name(model)
        if normalized not in self._rate_counters:
            limit = OPENCODE_GO_RATE_LIMITS.get(normalized, DEFAULT_RATE_LIMIT)
            self._rate_counters[normalized] = SlidingWindowCounter(_FIVE_HOURS)
            self._rate_limits[normalized] = limit
        return self._rate_counters[normalized], self._rate_limits[normalized]

    async def acquire(self, model: str, agent_name: str = "", team: str | None = None) -> None:
        """Acquire a slot for the given model. Queues if at limit."""
        provider = get_provider(model)
        normalized = normalize_model_name(model)
        waiter = Waiter(agent_name=agent_name, model=model, team=team)

        if provider == "z-ai":
            await self._acquire_zai(model, waiter)
        else:
            await self._acquire_rate_limited(model, waiter)

    async def _acquire_zai(self, model: str, waiter: Waiter) -> None:
        """Acquire a z-ai concurrency slot."""
        sem = self._get_semaphore(model)
        normalized = normalize_model_name(model)

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

    async def _acquire_rate_limited(self, model: str, waiter: Waiter) -> None:
        """Acquire an opencode-go rate-limited slot. Wait if window is exhausted."""
        counter, limit = self._get_rate_counter(model)
        normalized = normalize_model_name(model)

        # Record and check
        while counter.remaining(limit) <= 0:
            # Need to wait for the window to slide
            expiry = counter.earliest_expiry()
            if expiry:
                wait_seconds = max(1.0, expiry - time.time() + 1.0)
                logger.warning(
                    "⏳ %s waiting %.0fs for %s rate limit reset (used %d/%d in 5hr window)",
                    waiter.agent_name or "agent", wait_seconds, normalized,
                    counter.count(), limit,
                )
                await asyncio.sleep(min(wait_seconds, 60))  # check every 60s max
            else:
                break

        counter.record()
        waiter.started_at = time.time()
        self._active.setdefault(normalized, []).append(waiter)

        remaining = counter.remaining(limit)
        if remaining < limit * 0.2:
            logger.warning(
                "⚠️ %s started on %s — only %d/%d requests remaining in 5hr window",
                waiter.agent_name, normalized, remaining, limit,
            )

    def release(self, model: str, agent_name: str = "") -> None:
        """Release a slot."""
        provider = get_provider(model)
        normalized = normalize_model_name(model)

        # Remove from active
        if normalized in self._active:
            self._active[normalized] = [
                w for w in self._active[normalized]
                if w.agent_name != agent_name
            ]

        # Release semaphore for z-ai
        if provider == "z-ai":
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

        # z-ai models
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

        # opencode-go models
        for normalized, limit in self._rate_limits.items():
            counter = self._rate_counters[normalized]
            active = self._active.get(normalized, [])
            status[f"opencode-go/{normalized}"] = {
                "provider": "opencode-go",
                "type": "rate_limit",
                "window": "5h",
                "limit": limit,
                "used": counter.count(),
                "remaining": counter.remaining(limit),
                "active": len(active),
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
