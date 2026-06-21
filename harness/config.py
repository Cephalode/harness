"""YAML configuration loader and team structure validation."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


@dataclass
class DomainConfig:
    """File permission domain for an agent."""
    read: list[str] = field(default_factory=lambda: ["."])
    update: list[str] = field(default_factory=list)


@dataclass
class ExpertiseConfig:
    """Expertise file configuration for an agent."""
    path: str
    updatable: bool = True
    max_lines: int = 10000


@dataclass
class AgentConfig:
    """Configuration for a single agent."""
    name: str
    model: str
    system_prompt: str
    expertise: list[ExpertiseConfig] = field(default_factory=list)
    skills: list[str] = field(default_factory=list)
    domain: DomainConfig = field(default_factory=DomainConfig)
    max_turns: int = 30
    fallback_models: list[str] = field(default_factory=list)
    vision: bool = False
    only_instances: list[str] = field(default_factory=list)  # empty = all instances
    executor: str = "pi"  # "pi" (default) or "claude-code"


@dataclass
class TeamInstanceConfig:
    """A single instance of a team with optional model overrides."""
    name: str
    model_overrides: dict[str, str] = field(default_factory=dict)


@dataclass
class TeamConfig:
    """Configuration for a team (lead + workers)."""
    name: str
    color: str = "white"
    lead: AgentConfig | None = field(default=None)
    workers: list[AgentConfig] = field(default_factory=list)
    instances: list[TeamInstanceConfig] = field(default_factory=list)


@dataclass
class CommandStep:
    """A single step in a command workflow."""
    team: str
    prompt_template: str = "{input}"


@dataclass
class CommandConfig:
    """A reusable command workflow."""
    name: str
    description: str = ""
    steps: list[CommandStep] = field(default_factory=list)


@dataclass
class HarnessConfig:
    """Top-level harness configuration."""
    orchestrator: AgentConfig
    teams: list[TeamConfig] = field(default_factory=list)
    base_dir: str = "."
    commands: dict[str, CommandConfig] = field(default_factory=dict)


def _parse_domain(data: dict[str, Any] | None) -> DomainConfig:
    if data is None:
        return DomainConfig()
    return DomainConfig(
        read=data.get("read", ["."]),
        update=data.get("update", []),
    )


def _parse_expertise(data: list[dict[str, Any]] | None) -> list[ExpertiseConfig]:
    if data is None:
        return []
    return [
        ExpertiseConfig(
            path=e["path"],
            updatable=e.get("updatable", True),
            max_lines=e.get("max_lines", 10000),
        )
        for e in data
    ]


def _parse_agent(data: dict[str, Any]) -> AgentConfig:
    return AgentConfig(
        name=data["name"],
        model=data.get("model", ""),  # Empty = use PI's default provider/model
        system_prompt=data["system_prompt"],
        expertise=_parse_expertise(data.get("expertise")),
        skills=data.get("skills", []),
        domain=_parse_domain(data.get("domain")),
        max_turns=data.get("max_turns", 30),
        fallback_models=data.get("fallback_models", []),
        vision=data.get("vision", False),
        only_instances=data.get("only_instances", []),
        executor=data.get("executor", "pi"),
    )


def load_config(path: str | Path) -> HarnessConfig:
    """Load and validate a YAML configuration file."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        data = yaml.safe_load(f)

    if not isinstance(data, dict):
        raise ValueError("Config file must contain a YAML mapping")

    # Parse orchestrator
    if "orchestrator" not in data:
        raise ValueError("Config must define an 'orchestrator' section")

    orchestrator = _parse_agent(data["orchestrator"])

    # Parse teams
    teams: list[TeamConfig] = []
    for team_data in data.get("teams", []):
        lead = _parse_agent(team_data["lead"])
        workers = [_parse_agent(w) for w in team_data.get("workers", [])]
        instances = [
            TeamInstanceConfig(
                name=inst["name"],
                model_overrides=inst.get("models", {}),
            )
            for inst in team_data.get("instances", [])
        ]
        teams.append(
            TeamConfig(
                name=team_data["name"],
                color=team_data.get("color", "white"),
                lead=lead,
                workers=workers,
                instances=instances,
            )
        )

    # Parse commands
    commands: dict[str, CommandConfig] = {}
    for cmd_data in data.get("commands", []):
        steps = [
            CommandStep(
                team=s["team"],
                prompt_template=s.get("prompt", "{input}"),
            )
            for s in cmd_data.get("steps", [])
        ]
        cmd = CommandConfig(
            name=cmd_data["name"],
            description=cmd_data.get("description", ""),
            steps=steps,
        )
        commands[cmd.name] = cmd

    base_dir = str(path.parent.parent.resolve())
    return HarnessConfig(
        orchestrator=orchestrator,
        teams=teams,
        base_dir=base_dir,
        commands=commands,
    )


def validate_config(config: HarnessConfig) -> list[str]:
    """Validate config and return a list of warnings (empty if all good)."""
    warnings: list[str] = []

    # Check system prompt files exist
    base = Path(config.base_dir)
    for agent_cfg in [config.orchestrator] + [t.lead for t in config.teams] + [
        w for t in config.teams for w in t.workers
    ]:
        prompt_path = base / agent_cfg.system_prompt
        if not prompt_path.exists():
            warnings.append(f"System prompt not found: {prompt_path}")

        for skill_path in agent_cfg.skills:
            sp = base / skill_path
            if not sp.exists():
                warnings.append(f"Skill file not found: {sp}")

        for exp in agent_cfg.expertise:
            # Expertise files may not exist yet — that's fine, they'll be created
            pass

    # Check for duplicate agent names
    names = [config.orchestrator.name]
    for team in config.teams:
        names.append(team.lead.name)
        names.extend(w.name for w in team.workers)
    if len(names) != len(set(names)):
        warnings.append("Duplicate agent names detected")

    # Validate commands reference existing teams (including instance-expanded names)
    base_names = {t.name for t in config.teams}
    instance_names = {inst.name for t in config.teams for inst in t.instances}
    all_team_names = base_names | instance_names
    for cmd_name, cmd in config.commands.items():
        for step in cmd.steps:
            if step.team not in all_team_names:
                warnings.append(
                    f"Command '{cmd_name}' step references unknown team '{step.team}'"
                )

    return warnings
