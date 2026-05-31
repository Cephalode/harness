"""Tests for harness.rate_limiter — concurrency limiting and model degradation."""

import asyncio
import pytest

from harness.rate_limiter import (
    ConcurrencyLimiter,
    SlotAllocator,
    AllocationResult,
    Waiter,
    normalize_model_name,
    get_provider,
    MODEL_TIERS,
    Z_AI_CONCURRENCY,
    DEFAULT_CONCURRENCY,
)


# ─── normalize_model_name ──────────────────────────────────────

class TestNormalizeModelName:
    @pytest.mark.parametrize("input_name,expected", [
        ("z-ai/glm-5.1", "glm-5.1"),
        ("Z-AI/GLM-5.1", "glm-5.1"),
        ("glm-4.7", "glm-4.7"),
        ("GLM-4.7", "glm-4.7"),
        ("z-ai/glm-5-turbo", "glm-5-turbo"),
    ])
    def test_normalization(self, input_name, expected):
        assert normalize_model_name(input_name) == expected


# ─── get_provider ──────────────────────────────────────────────

class TestGetProvider:
    def test_with_prefix(self):
        assert get_provider("z-ai/glm-5.1") == "z-ai"

    def test_without_prefix(self):
        assert get_provider("glm-5.1") == ""

    def test_case_insensitive(self):
        assert get_provider("Z-AI/glm-5.1") == "z-ai"


# ─── ConcurrencyLimiter ───────────────────────────────────────

class TestConcurrencyLimiter:
    def test_available_slots_untracked(self):
        limiter = ConcurrencyLimiter()
        # Untracked model should return configured limit
        assert limiter.available_slots("z-ai/glm-5.1") == Z_AI_CONCURRENCY["glm-5.1"]

    def test_is_available_untracked(self):
        limiter = ConcurrencyLimiter()
        assert limiter.is_available("z-ai/glm-5.1") is True

    @pytest.mark.asyncio
    async def test_acquire_release(self):
        limiter = ConcurrencyLimiter()
        await limiter.acquire("z-ai/glm-5.1", "agent1", "team1")
        assert limiter.available_slots("z-ai/glm-5.1") == Z_AI_CONCURRENCY["glm-5.1"] - 1
        limiter.release("z-ai/glm-5.1", "agent1")
        assert limiter.available_slots("z-ai/glm-5.1") == Z_AI_CONCURRENCY["glm-5.1"]

    @pytest.mark.asyncio
    async def test_slot_context_manager(self):
        limiter = ConcurrencyLimiter()
        async with limiter.slot("z-ai/glm-4.7", "agent1", "team1"):
            assert limiter.available_slots("z-ai/glm-4.7") == Z_AI_CONCURRENCY["glm-4.7"] - 1
        assert limiter.available_slots("z-ai/glm-4.7") == Z_AI_CONCURRENCY["glm-4.7"]

    @pytest.mark.asyncio
    async def test_get_status(self):
        limiter = ConcurrencyLimiter()
        await limiter.acquire("z-ai/glm-5.1", "test_agent", "test_team")
        status = limiter.get_status()
        assert "z-ai/glm-5.1" in status
        assert status["z-ai/glm-5.1"]["active"] == 1
        assert status["z-ai/glm-5.1"]["limit"] == Z_AI_CONCURRENCY["glm-5.1"]

    @pytest.mark.asyncio
    async def test_unknown_model_uses_default(self):
        limiter = ConcurrencyLimiter()
        await limiter.acquire("z-ai/unknown-model", "agent1")
        assert limiter.available_slots("z-ai/unknown-model") == DEFAULT_CONCURRENCY - 1
        limiter.release("z-ai/unknown-model", "agent1")


# ─── SlotAllocator ─────────────────────────────────────────────

class TestSlotAllocator:
    def _make_allocator(self, max_queue_wait=5.0):
        limiter = ConcurrencyLimiter()
        return SlotAllocator(limiter, max_queue_wait=max_queue_wait)

    @pytest.mark.asyncio
    async def test_preferred_model_available(self):
        alloc = self._make_allocator()
        result = await alloc.allocate(
            preferred="z-ai/glm-5.1",
            agent_name="agent1",
            team="team1",
        )
        assert result.model == "z-ai/glm-5.1"
        assert result.original_model == "z-ai/glm-5.1"
        assert result.degraded is False
        assert result.queued is False

    @pytest.mark.asyncio
    async def test_degradation_to_fallback(self):
        alloc = self._make_allocator()
        limiter = alloc._limiter
        # Fill up glm-5.1 slots
        for i in range(Z_AI_CONCURRENCY["glm-5.1"]):
            await limiter.acquire("z-ai/glm-5.1", f"filler-{i}")

        result = await alloc.allocate(
            preferred="z-ai/glm-5.1",
            fallback_models=["z-ai/glm-4.7"],
            agent_name="agent1",
        )
        assert result.degraded is True
        assert "glm-4.7" in result.model

    @pytest.mark.asyncio
    async def test_release_and_status(self):
        alloc = self._make_allocator()
        result = await alloc.allocate("z-ai/glm-5.1", agent_name="agent1", team="t1")
        alloc.release(result.model, "agent1")
        status = alloc.get_status()
        assert "limiter" in status
        assert "allocations" in status

    @pytest.mark.asyncio
    async def test_build_cascade(self):
        alloc = self._make_allocator()
        cascade = alloc._build_cascade(
            preferred="z-ai/glm-5.1",
            preferred_norm="glm-5.1",
            preferred_tier=MODEL_TIERS["glm-5.1"],
            fallback_models=["z-ai/glm-4.7"],
        )
        # Should start with preferred
        assert cascade[0] == "z-ai/glm-5.1"
        # Should include fallback
        assert "z-ai/glm-4.7" in cascade
        # Should not duplicate
        assert len(cascade) == len(set(cascade))

    @pytest.mark.asyncio
    async def test_cascade_no_duplicates(self):
        alloc = self._make_allocator()
        cascade = alloc._build_cascade(
            preferred="z-ai/glm-5.1",
            preferred_norm="glm-5.1",
            preferred_tier=MODEL_TIERS["glm-5.1"],
            fallback_models=["z-ai/glm-5.1", "z-ai/glm-4.7"],  # duplicate preferred
        )
        # Should not contain duplicates even if fallback repeats preferred
        assert len(cascade) == len(set(cascade))
