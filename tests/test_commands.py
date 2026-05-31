"""Tests for harness.commands — reusable prompt command workflows."""

import pytest

from unittest.mock import AsyncMock, MagicMock

from harness.commands import execute_command, format_command_summary
from harness.config import CommandConfig, CommandStep


# ─── format_command_summary ───────────────────────────────────

class TestFormatCommandSummary:
    def test_success_results(self):
        results = [
            {
                "team": "engineering",
                "final_response": "Built the feature",
                "workers_used": 2,
            }
        ]
        summary = format_command_summary("build", results)
        assert "Command: build" in summary
        assert "Step 1" in summary
        assert "engineering" in summary
        assert "Built the feature" in summary

    def test_error_results(self):
        results = [
            {
                "team": "nonexistent",
                "error": "Team not found",
            }
        ]
        summary = format_command_summary("test", results)
        assert "Error" in summary
        assert "Team not found" in summary

    def test_long_response_truncated(self):
        long_resp = "x" * 600
        results = [
            {
                "team": "eng",
                "final_response": long_resp,
            }
        ]
        summary = format_command_summary("cmd", results)
        assert "truncated" in summary

    def test_multiple_steps(self):
        results = [
            {"team": "planning", "final_response": "Plan done"},
            {"team": "engineering", "final_response": "Code done"},
        ]
        summary = format_command_summary("pipeline", results)
        assert "Step 1" in summary
        assert "Step 2" in summary
        assert "planning" in summary
        assert "engineering" in summary

    def test_empty_results(self):
        summary = format_command_summary("empty", [])
        assert "Command: empty" in summary


# ─── execute_command ──────────────────────────────────────────

class TestExecuteCommand:
    @pytest.mark.asyncio
    async def test_single_step_success(self):
        mock_team = MagicMock()
        mock_team.execute = AsyncMock(return_value={
            "team": "engineering",
            "final_response": "Built it",
            "workers_used": 1,
        })
        teams = {"engineering": mock_team}

        cmd = CommandConfig(
            name="build",
            steps=[CommandStep(team="engineering", prompt_template="Build: {input}")],
        )
        results = await execute_command(cmd, "the auth system", teams)
        assert len(results) == 1
        assert results[0]["final_response"] == "Built it"
        # Verify template substitution
        call_args = mock_team.execute.call_args
        assert "the auth system" in call_args.kwargs.get("task", call_args[1].get("task", ""))

    @pytest.mark.asyncio
    async def test_multi_step_pipeline(self):
        step1_result = {
            "team": "planning",
            "final_response": "Design doc ready",
        }
        step2_result = {
            "team": "engineering",
            "final_response": "Code written",
        }

        team1 = MagicMock()
        team1.execute = AsyncMock(return_value=step1_result)
        team2 = MagicMock()
        team2.execute = AsyncMock(return_value=step2_result)
        teams = {"planning": team1, "engineering": team2}

        cmd = CommandConfig(
            name="full",
            steps=[
                CommandStep(team="planning", prompt_template="Plan: {input}"),
                CommandStep(team="engineering", prompt_template="Implement based on: {prev_result}"),
            ],
        )
        results = await execute_command(cmd, "new feature", teams)
        assert len(results) == 2

        # Verify second step got prev_result substituted
        call_args = team2.execute.call_args
        task_arg = call_args.kwargs.get("task", call_args[1].get("task", ""))
        assert "Design doc ready" in task_arg

    @pytest.mark.asyncio
    async def test_unknown_team_error(self):
        teams = {}
        cmd = CommandConfig(
            name="bad",
            steps=[CommandStep(team="nonexistent")],
        )
        results = await execute_command(cmd, "input", teams)
        assert len(results) == 1
        assert "error" in results[0]
        assert "not found" in results[0]["error"]

    @pytest.mark.asyncio
    async def test_template_substitution(self):
        mock_team = MagicMock()
        mock_team.execute = AsyncMock(return_value={"team": "t", "final_response": "ok"})
        teams = {"t": mock_team}

        cmd = CommandConfig(
            name="test",
            steps=[CommandStep(team="t", prompt_template="Do {input} and then {prev_result}")],
        )
        results = await execute_command(cmd, "TASK", teams)
        call_args = mock_team.execute.call_args
        task_arg = call_args.kwargs.get("task", call_args[1].get("task", ""))
        assert "TASK" in task_arg
