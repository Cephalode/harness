"""Per-agent expertise/mental model management — load and update markdown files."""

from __future__ import annotations

from pathlib import Path

from .config import ExpertiseConfig


class ExpertiseManager:
    """Manages per-agent expertise/mental model markdown files."""

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir).resolve()

    def _resolve_path(self, path: str) -> Path:
        """Resolve an expertise file path."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    def load(self, config: ExpertiseConfig) -> str:
        """Load expertise content for an agent. Returns empty string if not found."""
        path = self._resolve_path(config.path)
        if path.exists():
            content = path.read_text(encoding="utf-8").strip()
            # Enforce max lines
            lines = content.splitlines()
            if len(lines) > config.max_lines:
                lines = lines[-config.max_lines:]
                content = "\n".join(lines)
            return content
        return ""

    def load_all(self, configs: list[ExpertiseConfig]) -> str:
        """Load and concatenate all expertise files for an agent."""
        parts: list[str] = []
        for cfg in configs:
            content = self.load(cfg)
            if content:
                parts.append(content)
        return "\n\n".join(parts)

    def update(self, config: ExpertiseConfig, content: str) -> None:
        """Update an expertise file with new content (if updatable)."""
        if not config.updatable:
            return
        path = self._resolve_path(config.path)
        path.parent.mkdir(parents=True, exist_ok=True)

        # Enforce max lines
        lines = content.splitlines()
        if len(lines) > config.max_lines:
            lines = lines[-config.max_lines:]

        path.write_text("\n".join(lines), encoding="utf-8")

    def append_insight(self, config: ExpertiseConfig, insight: str) -> None:
        """Append a new insight to the expertise file."""
        if not config.updatable:
            return
        existing = self.load(config)
        if existing:
            new_content = existing + "\n\n" + insight
        else:
            new_content = insight
        self.update(config, new_content)

    def format_expertise_section(self, configs: list[ExpertiseConfig]) -> str:
        """Format expertise content for system prompt injection."""
        content = self.load_all(configs)
        if not content:
            return ""
        return (
            f"## Your Expertise & Mental Model\n\n"
            f"This is your accumulated knowledge from previous sessions. "
            f"Use it to inform your work and build upon it.\n\n"
            f"{content}\n"
        )

    def get_agent_names(self) -> list[str]:
        """List all agents that have expertise files."""
        expertise_dir = self.base_dir / "expertise"
        if not expertise_dir.exists():
            return []
        return [p.stem for p in expertise_dir.glob("*.md")]
