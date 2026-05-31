"""Tests for harness.delegate — delegation tool for inter-agent communication."""

import pytest

from unittest.mock import AsyncMock, MagicMock

from harness.config import AgentConfig, DomainConfig
from harness.delegate import DelegationTool


def _make_agent(name="test_agent", model="glm-5.1"):
    """Create a mock agent for testing."""
    agent = MagicMock()
    agent.name = name
    agent.config = AgentConfig(
        name=name, model=model, system_prompt="test.md"
    )
    agent.run = AsyncMock(return_value={
        "result": f"Result from {name}",
        "usage": {},
        "model": model,
    })
    agent.update_expertise = MagicMock()
    return agent


# ─── DelegationTool init ──────────────────────────────────────

class TestDelegationToolInit:
    def test_get_agent_found(self):
        agent = _make_agent("worker1")
        tool = DelegationTool({"worker1": agent})
        assert tool.get_agent("worker1") is agent

    def test_get_agent_not_found(self):
        tool = DelegationTool({})
        assert tool.get_agent("nonexistent") is None


# ─── delegate ─────────────────────────────────────────────────

class TestDelegationToolDelegate:
    @pytest.mark.asyncio
    async def test_delegate_success(self):
        agent = _make_agent("worker1")
        tool = DelegationTool({"worker1": agent})

        result = await tool.delegate(
            from_agent="lead",
            to_agent="worker1",
            task="Fix the login bug",
            context="See auth.py",
        )
        assert result["result"] == "Result from worker1"
        agent.run.assert_called_once()
        # Check delegation context was added
        call_args = agent.run.call_args
        assert "Delegated by: lead" in call_args.kwargs.get("context", call_args[1].get("context", ""))

    @pytest.mark.asyncio
    async def test_delegate_unknown_agent(self):
        tool = DelegationTool({})
        result = await tool.delegate(
            from_agent="lead",
            to_agent="nonexistent",
            task="Do something",
        )
        assert "error" in result
        assert "not found" in result["error"]

    @pytest.mark.asyncio
    async def test_delegate_updates_expertise_on_long_result(self):
        agent = _make_agent("worker1")
        agent.run = AsyncMock(return_value={
            "result": "x" * 100,  # > 50 chars
            "usage": {},
        })
        tool = DelegationTool({"worker1": agent})
        await tool.delegate("lead", "worker1", "Task")
        agent.update_expertise.assert_called_once()

    @pytest.mark.asyncio
    async def test_delegate_no_expertise_on_short_result(self):
        agent = _make_agent("worker1")
        agent.run = AsyncMock(return_value={
            "result": "short",  # < 50 chars
            "usage": {},
        })
        tool = DelegationTool({"worker1": agent})
        await tool.delegate("lead", "worker1", "Task")
        agent.update_expertise.assert_not_called()

    @pytest.mark.asyncio
    async def test_delegate_no_expertise_on_error(self):
        agent = _make_agent("worker1")
        agent.run = AsyncMock(return_value={
            "result": "x" * 100,
            "error": "timeout",
            "usage": {},
        })
        tool = DelegationTool({"worker1": agent})
        await tool.delegate("lead", "worker1", "Task")
        agent.update_expertise.assert_not_called()


# ─── delegate_parallel ────────────────────────────────────────

class TestDelegationToolParallel:
    @pytest.mark.asyncio
    async def test_parallel_delegation(self):
        w1 = _make_agent("worker1")
        w2 = _make_agent("worker2")
        tool = DelegationTool({"worker1": w1, "worker2": w2})

        delegations = [
            {"to_agent": "worker1", "task": "Task A", "context": "ctx A"},
            {"to_agent": "worker2", "task": "Task B"},
        ]
        results = await tool.delegate_parallel("lead", delegations)
        assert len(results) == 2
        w1.run.assert_called_once()
        w2.run.assert_called_once()

    @pytest.mark.asyncio
    async def test_parallel_with_unknown_agent(self):
        w1 = _make_agent("worker1")
        tool = DelegationTool({"worker1": w1})

        delegations = [
            {"to_agent": "worker1", "task": "Task A"},
            {"to_agent": "unknown", "task": "Task B"},
        ]
        results = await tool.delegate_parallel("lead", delegations)
        assert len(results) == 2
        assert "error" in results[1]


# ─── format_delegation_instructions ───────────────────────────

class TestFormatDelegationInstructions:
    def test_format_with_agents(self):
        tool = DelegationTool({})
        instructions = tool.format_delegation_instructions(["worker1", "worker2"])
        assert "worker1" in instructions
        assert "worker2" in instructions
        assert "delegate" in instructions
        assert "```delegate" in instructions

    def test_format_empty_list(self):
        tool = DelegationTool({})
        instructions = tool.format_delegation_instructions([])
        assert "delegate" in instructions
