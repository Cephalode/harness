"""Tests for harness.config — YAML config loading and validation."""

import pytest
import yaml
from pathlib import Path

from harness.config import (
    AgentConfig,
    DomainConfig,
    ExpertiseConfig,
    HarnessConfig,
    TeamConfig,
    TeamInstanceConfig,
    CommandConfig,
    CommandStep,
    _parse_agent,
    _parse_domain,
    _parse_expertise,
    load_config,
    validate_config,
)


# ─── _parse_domain ─────────────────────────────────────────────

class TestParseDomain:
    def test_none_returns_defaults(self):
        d = _parse_domain(None)
        assert d.read == ["."]
        assert d.update == []

    def test_full_config(self):
        d = _parse_domain({"read": ["src/"], "update": ["src/tests/"]})
        assert d.read == ["src/"]
        assert d.update == ["src/tests/"]

    def test_partial_uses_defaults(self):
        d = _parse_domain({"update": ["dist/"]})
        assert d.read == ["."]
        assert d.update == ["dist/"]


# ─── _parse_expertise ──────────────────────────────────────────

class TestParseExpertise:
    def test_none_returns_empty(self):
        assert _parse_expertise(None) == []

    def test_full_config(self):
        data = [{"path": "expertise.md", "updatable": False, "max_lines": 5000}]
        result = _parse_expertise(data)
        assert len(result) == 1
        assert result[0].path == "expertise.md"
        assert result[0].updatable is False
        assert result[0].max_lines == 5000

    def test_defaults(self):
        data = [{"path": "notes.md"}]
        result = _parse_expertise(data)
        assert result[0].updatable is True
        assert result[0].max_lines == 10000


# ─── _parse_agent ──────────────────────────────────────────────

class TestParseAgent:
    def test_minimal(self):
        agent = _parse_agent({"name": "test", "system_prompt": "You are helpful."})
        assert agent.name == "test"
        assert agent.model == ""
        assert agent.system_prompt == "You are helpful."
        assert agent.max_turns == 30
        assert agent.vision is False
        assert agent.expertise == []
        assert agent.skills == []

    def test_full(self):
        agent = _parse_agent({
            "name": "dev",
            "model": "gpt-4o",
            "system_prompt": "Dev agent.",
            "max_turns": 50,
            "vision": True,
            "fallback_models": ["gpt-4o-mini"],
            "only_instances": ["instance-1"],
            "skills": ["skill1.md"],
            "expertise": [{"path": "exp.md"}],
            "domain": {"read": ["src/"], "update": ["src/"]},
        })
        assert agent.model == "gpt-4o"
        assert agent.max_turns == 50
        assert agent.vision is True
        assert agent.fallback_models == ["gpt-4o-mini"]
        assert agent.only_instances == ["instance-1"]
        assert len(agent.expertise) == 1


# ─── load_config ───────────────────────────────────────────────

class TestLoadConfig:
    def _write_yaml(self, tmp_path, data, filename="config.yaml"):
        cfg_path = tmp_path / filename
        cfg_path.write_text(yaml.dump(data), encoding="utf-8")
        # Create parent dirs for config inside a nested structure
        (tmp_path / "prompts").mkdir(exist_ok=True)
        (tmp_path / "prompts" / "system.md").write_text("system prompt")
        return cfg_path

    def test_minimal_config(self, tmp_path):
        cfg_path = self._write_yaml(tmp_path, {
            "orchestrator": {
                "name": "orch",
                "system_prompt": "prompts/system.md",
            }
        })
        config = load_config(cfg_path)
        assert isinstance(config, HarnessConfig)
        assert config.orchestrator.name == "orch"
        assert config.teams == []
        assert config.commands == {}

    def test_full_config(self, tmp_path):
        cfg_path = self._write_yaml(tmp_path, {
            "orchestrator": {
                "name": "orch",
                "system_prompt": "prompts/system.md",
            },
            "teams": [
                {
                    "name": "eng",
                    "color": "blue",
                    "lead": {"name": "lead", "system_prompt": "prompts/system.md"},
                    "workers": [
                        {"name": "w1", "system_prompt": "prompts/system.md"},
                    ],
                    "instances": [
                        {"name": "eng-1", "models": {"lead": "glm-4.7"}},
                    ],
                }
            ],
            "commands": [
                {
                    "name": "build",
                    "description": "Build project",
                    "steps": [{"team": "eng", "prompt": "Build it: {input}"}],
                }
            ],
        })
        config = load_config(cfg_path)
        assert len(config.teams) == 1
        assert config.teams[0].name == "eng"
        assert config.teams[0].color == "blue"
        assert config.teams[0].lead.name == "lead"
        assert len(config.teams[0].workers) == 1
        assert len(config.teams[0].instances) == 1
        assert "build" in config.commands
        assert config.commands["build"].steps[0].prompt_template == "Build it: {input}"

    def test_file_not_found(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            load_config(tmp_path / "nonexistent.yaml")

    def test_non_mapping_yaml(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text("just a string", encoding="utf-8")
        with pytest.raises(ValueError, match="YAML mapping"):
            load_config(cfg_path)

    def test_missing_orchestrator(self, tmp_path):
        cfg_path = tmp_path / "config.yaml"
        cfg_path.write_text(yaml.dump({"teams": []}), encoding="utf-8")
        with pytest.raises(ValueError, match="orchestrator"):
            load_config(cfg_path)


# ─── validate_config ──────────────────────────────────────────

class TestValidateConfig:
    def _make_config(self, tmp_path, **overrides):
        orch = AgentConfig(name="orch", model="gpt-4o", system_prompt="missing.md")
        cfg = HarnessConfig(orchestrator=orch, base_dir=str(tmp_path))
        for k, v in overrides.items():
            setattr(cfg, k, v)
        return cfg

    def test_empty_teams_no_warnings(self, tmp_path):
        cfg = self._make_config(tmp_path)
        # Create the prompt file so no warning
        (tmp_path / "missing.md").write_text("prompt")
        warnings = validate_config(cfg)
        assert len(warnings) == 0

    def test_missing_prompt_warns(self, tmp_path):
        cfg = self._make_config(tmp_path)
        warnings = validate_config(cfg)
        assert any("System prompt not found" in w for w in warnings)

    def test_duplicate_agent_names(self, tmp_path):
        orch = AgentConfig(name="dup", model="", system_prompt="p.md")
        lead = AgentConfig(name="dup", model="", system_prompt="p.md")
        cfg = HarnessConfig(
            orchestrator=orch,
            teams=[TeamConfig(name="t", lead=lead)],
            base_dir=str(tmp_path),
        )
        warnings = validate_config(cfg)
        assert any("Duplicate agent" in w for w in warnings)

    def test_command_references_unknown_team(self, tmp_path):
        (tmp_path / "p.md").write_text("prompt")
        orch = AgentConfig(name="orch", model="", system_prompt="p.md")
        cmd = CommandConfig(
            name="test-cmd",
            steps=[CommandStep(team="nonexistent")],
        )
        cfg = HarnessConfig(
            orchestrator=orch,
            commands={"test-cmd": cmd},
            base_dir=str(tmp_path),
        )
        warnings = validate_config(cfg)
        assert any("unknown team" in w for w in warnings)

    def test_command_references_instance_name(self, tmp_path):
        (tmp_path / "p.md").write_text("prompt")
        orch = AgentConfig(name="orch", model="", system_prompt="p.md")
        lead = AgentConfig(name="lead", model="", system_prompt="p.md")
        inst = TeamInstanceConfig(name="team-a-inst")
        team = TeamConfig(name="team-a", lead=lead, instances=[inst])
        cmd = CommandConfig(
            name="run",
            steps=[CommandStep(team="team-a-inst")],
        )
        cfg = HarnessConfig(
            orchestrator=orch,
            teams=[team],
            commands={"run": cmd},
            base_dir=str(tmp_path),
        )
        warnings = validate_config(cfg)
        team_warnings = [w for w in warnings if "unknown team" in w]
        assert len(team_warnings) == 0
