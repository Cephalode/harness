"""Tests for harness.team — delegation block parsing and result compilation."""

import pytest

from harness.config import AgentConfig, DomainConfig, TeamConfig
from harness.team import Team, parse_delegation_blocks, DELEGATE_BLOCK_PATTERN


# ─── parse_delegation_blocks ─────────────────────────────────

class TestParseDelegationBlocks:
    def test_single_block(self):
        text = (
            "Some text\n"
            "```delegate\n"
            "to: worker1\n"
            "task: Fix the bug\n"
            "context: See file X\n"
            "```\n"
            "More text"
        )
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 1
        assert blocks[0]["to"] == "worker1"
        assert blocks[0]["task"] == "Fix the bug"
        assert blocks[0]["context"] == "See file X"

    def test_multiple_blocks(self):
        text = (
            "```delegate\n"
            "to: worker1\n"
            "task: Task A\n"
            "```\n"
            "Some prose\n"
            "```delegate\n"
            "to: worker2\n"
            "task: Task B\n"
            "context: Extra info\n"
            "```"
        )
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 2
        assert blocks[0]["to"] == "worker1"
        assert blocks[1]["to"] == "worker2"

    def test_missing_to_skipped(self):
        text = (
            "```delegate\n"
            "task: Some task\n"
            "```"
        )
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 0

    def test_missing_task_skipped(self):
        text = (
            "```delegate\n"
            "to: worker1\n"
            "```"
        )
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 0

    def test_no_delegate_blocks(self):
        text = "Just regular text without any delegation."
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 0

    def test_block_without_context(self):
        text = (
            "```delegate\n"
            "to: worker3\n"
            "task: Do something\n"
            "```"
        )
        blocks = parse_delegation_blocks(text)
        assert len(blocks) == 1
        assert "context" not in blocks[0]

    def test_whitespace_in_fields(self):
        text = (
            "```delegate\n"
            "to:   worker1  \n"
            "task:   Fix the bug  \n"
            "```"
        )
        blocks = parse_delegation_blocks(text)
        assert blocks[0]["to"] == "worker1"
        assert blocks[0]["task"] == "Fix the bug"


# ─── DELEGATE_BLOCK_PATTERN regex ────────────────────────────

class TestDelegateBlockPattern:
    def test_matches_delegate_block(self):
        text = "```delegate\nto: w1\ntask: do stuff\n```"
        match = DELEGATE_BLOCK_PATTERN.search(text)
        assert match is not None

    def test_no_match_regular_code(self):
        text = "```python\nprint('hello')\n```"
        match = DELEGATE_BLOCK_PATTERN.search(text)
        assert match is None


# ─── Team construction ───────────────────────────────────────

class TestTeamConstruction:
    def _make_team_config(self):
        return TeamConfig(
            name="engineering",
            color="blue",
            lead=AgentConfig(
                name="lead",
                model="glm-5.1",
                system_prompt="lead.md",
            ),
            workers=[
                AgentConfig(
                    name="frontend",
                    model="glm-5.1",
                    system_prompt="frontend.md",
                ),
                AgentConfig(
                    name="backend",
                    model="glm-4.7",
                    system_prompt="backend.md",
                ),
            ],
        )

    def test_team_name(self, tmp_path):
        from harness.models import CostTracker
        config = self._make_team_config()
        team = Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))
        assert team.name == "engineering"
        assert team.color == "blue"

    def test_team_agents_created(self, tmp_path):
        from harness.models import CostTracker
        config = self._make_team_config()
        team = Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))
        assert team.lead.name == "lead"
        assert len(team.workers) == 2
        assert "frontend" in team.workers
        assert "backend" in team.workers

    def test_worker_names(self, tmp_path):
        from harness.models import CostTracker
        config = self._make_team_config()
        team = Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))
        names = team.worker_names
        assert "frontend" in names
        assert "backend" in names

    def test_lead_has_workers_injected(self, tmp_path):
        from harness.models import CostTracker
        config = self._make_team_config()
        team = Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))
        assert team.lead._worker_names == ["frontend", "backend"]

    def test_team_no_workers(self, tmp_path):
        from harness.models import CostTracker
        config = TeamConfig(
            name="solo",
            lead=AgentConfig(name="solo_agent", model="glm-5.1", system_prompt="solo.md"),
        )
        team = Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))
        assert team.workers == {}
        assert team.worker_names == []


# ─── Team._compile_result ────────────────────────────────────

class TestTeamCompileResult:
    def _make_team(self, tmp_path):
        from harness.models import CostTracker
        config = TeamConfig(
            name="test",
            lead=AgentConfig(name="lead", model="glm-5.1", system_prompt="lead.md"),
            workers=[
                AgentConfig(name="w1", model="glm-5.1", system_prompt="w1.md"),
            ],
        )
        return Team(config=config, cost_tracker=CostTracker(), base_dir=str(tmp_path))

    def test_lead_text_only(self, tmp_path):
        team = self._make_team(tmp_path)
        result = team._compile_result("Lead says hello", [])
        assert "[lead]: Lead says hello" in result

    def test_lead_and_worker_results(self, tmp_path):
        team = self._make_team(tmp_path)
        worker_results = [{"result": "Worker did the thing"}]
        result = team._compile_result("Lead says hello", worker_results)
        assert "[lead]:" in result
        assert "[Worker 1]: Worker did the thing" in result

    def test_delegation_blocks_stripped_from_display(self, tmp_path):
        team = self._make_team(tmp_path)
        lead_text = (
            "I will delegate\n"
            "```delegate\n"
            "to: w1\n"
            "task: Do it\n"
            "```\n"
            "Done delegating"
        )
        result = team._compile_result(lead_text, [])
        assert "```delegate" not in result
        assert "Done delegating" in result

    def test_long_worker_result_truncated(self, tmp_path):
        team = self._make_team(tmp_path)
        long_text = "x" * 3000
        worker_results = [{"result": long_text}]
        result = team._compile_result("Lead", worker_results)
        assert "truncated" in result
        assert len(result) < len(long_text)

    def test_string_worker_result(self, tmp_path):
        team = self._make_team(tmp_path)
        worker_results = ["plain string result"]
        result = team._compile_result("Lead", worker_results)
        assert "plain string result" in result
