"""Tests for harness.agent — agent prompt building and construction."""

import pytest

from harness.agent import Agent, STATUS_BLOCK_PATTERN
from harness.config import AgentConfig, DomainConfig, ExpertiseConfig


def _make_config(**overrides):
    defaults = {
        "name": "test_agent",
        "model": "glm-5.1",
        "system_prompt": "nonexistent.md",
        "domain": DomainConfig(read=["."], update=[]),
    }
    defaults.update(overrides)
    return AgentConfig(**defaults)


# ─── STATUS_BLOCK_PATTERN ─────────────────────────────────────

class TestStatusBlockPattern:
    def test_matches_status_block(self):
        text = "```status\nmessage: Working on tests\n```"
        matches = STATUS_BLOCK_PATTERN.findall(text)
        assert len(matches) == 1
        assert matches[0] == "Working on tests"

    def test_no_match_regular_code(self):
        text = "```python\nprint('hello')\n```"
        matches = STATUS_BLOCK_PATTERN.findall(text)
        assert len(matches) == 0

    def test_multiple_status_blocks(self):
        text = (
            "```status\nmessage: Step 1\n```\n"
            "some output\n"
            "```status\nmessage: Step 2\n```"
        )
        matches = STATUS_BLOCK_PATTERN.findall(text)
        assert len(matches) == 2

    def test_status_with_extra_whitespace(self):
        text = "```status  \nmessage:  Doing stuff  \n```"
        matches = STATUS_BLOCK_PATTERN.findall(text)
        assert len(matches) == 1


# ─── Agent construction ──────────────────────────────────────

class TestAgentConstruction:
    def test_basic_construction(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        assert agent.name == "test_agent"
        assert agent.model == "glm-5.1"
        assert agent.team_name is None

    def test_name_property(self, tmp_path):
        config = _make_config(name="my_agent")
        agent = Agent(config=config, base_dir=str(tmp_path))
        assert agent.name == "my_agent"

    def test_model_property(self, tmp_path):
        config = _make_config(model="gpt-4o")
        agent = Agent(config=config, base_dir=str(tmp_path))
        assert agent.model == "gpt-4o"

    def test_custom_cost_tracker(self, tmp_path):
        from harness.models import CostTracker
        tracker = CostTracker()
        config = _make_config()
        agent = Agent(config=config, cost_tracker=tracker, base_dir=str(tmp_path))
        assert agent.cost_tracker is tracker

    def test_default_cost_tracker(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        from harness.models import CostTracker
        assert isinstance(agent.cost_tracker, CostTracker)


# ─── set_available_workers ───────────────────────────────────

class TestAgentSetWorkers:
    def test_set_available_workers(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        agent.set_available_workers(["worker1", "worker2"])
        assert agent._worker_names == ["worker1", "worker2"]


# ─── _build_system_prompt ─────────────────────────────────────

class TestAgentBuildSystemPrompt:
    def test_missing_prompt_file(self, tmp_path):
        config = _make_config(system_prompt="missing.md")
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "not found" in prompt

    def test_existing_prompt_file(self, tmp_path):
        (tmp_path / "system.md").write_text("You are a helpful assistant.")
        config = _make_config(system_prompt="system.md")
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "helpful assistant" in prompt

    def test_domain_rules_injected(self, tmp_path):
        config = _make_config(
            domain=DomainConfig(read=["src"], update=["src/tests"])
        )
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Domain Permissions" in prompt
        assert "src" in prompt

    def test_vision_mode_adds_vision_instructions(self, tmp_path):
        config = _make_config(vision=True)
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Vision Mode" in prompt
        assert "VISION agent" in prompt

    def test_non_vision_gets_status_reporting(self, tmp_path):
        config = _make_config(vision=False)
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Status Reporting" in prompt

    def test_vision_skips_status_reporting(self, tmp_path):
        config = _make_config(vision=True)
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Status Reporting" not in prompt

    def test_delegation_protocol_injected(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        agent.set_available_workers(["worker_a", "worker_b"])
        prompt = agent._build_system_prompt()
        assert "Delegation Protocol" in prompt
        assert "worker_a" in prompt
        assert "worker_b" in prompt

    def test_no_delegation_without_workers(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Delegation Protocol" not in prompt

    def test_expertise_injected(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "test.md").write_text("Expert knowledge here")
        config = _make_config(
            expertise=[ExpertiseConfig(path="expertise/test.md")]
        )
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Expert knowledge here" in prompt
        assert "Expertise" in prompt

    def test_skills_injected(self, tmp_path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        (skills_dir / "coding.md").write_text("# Coding Skill\nWrite tests.")
        config = _make_config(skills=["skills/coding.md"])
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_system_prompt()
        assert "Coding Skill" in prompt
        assert "Skills" in prompt


# ─── _build_prompt ────────────────────────────────────────────

class TestAgentBuildPrompt:
    def test_basic_prompt(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_prompt("Do the task")
        assert "Your Task" in prompt
        assert "Do the task" in prompt

    def test_prompt_with_context(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_prompt("Do the task", context="See file X")
        assert "Context from Delegation" in prompt
        assert "See file X" in prompt

    def test_prompt_with_session(self, tmp_path):
        from harness.session import Session
        session = Session(sessions_dir=str(tmp_path / "sessions"))
        session.add_message(role="user", content="Previous question")

        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path), session=session)
        prompt = agent._build_prompt("New task")
        assert "Conversation So Far" in prompt
        assert "Previous question" in prompt

    def test_prompt_no_session(self, tmp_path):
        config = _make_config()
        agent = Agent(config=config, base_dir=str(tmp_path))
        prompt = agent._build_prompt("Task")
        assert "Conversation So Far" not in prompt


# ─── update_expertise ─────────────────────────────────────────

class TestAgentUpdateExpertise:
    def test_update_expertise_updatable(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "agent.md").write_text("Initial knowledge")

        config = _make_config(
            expertise=[ExpertiseConfig(path="expertise/agent.md", updatable=True)]
        )
        agent = Agent(config=config, base_dir=str(tmp_path))
        agent.update_expertise("New insight learned")

        content = (exp_dir / "agent.md").read_text()
        assert "New insight learned" in content

    def test_update_expertise_not_updatable(self, tmp_path):
        exp_dir = tmp_path / "expertise"
        exp_dir.mkdir()
        (exp_dir / "frozen.md").write_text("Static knowledge")

        config = _make_config(
            expertise=[ExpertiseConfig(path="expertise/frozen.md", updatable=False)]
        )
        agent = Agent(config=config, base_dir=str(tmp_path))
        agent.update_expertise("Should not be added")

        content = (exp_dir / "frozen.md").read_text()
        assert "Should not be added" not in content
