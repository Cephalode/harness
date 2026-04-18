"""Load skill markdown files and inject into system prompts."""

from __future__ import annotations

from pathlib import Path


class SkillLoader:
    """Loads skill markdown files and formats them for system prompt injection."""

    def __init__(self, base_dir: str = ".") -> None:
        self.base_dir = Path(base_dir).resolve()

    def _resolve_path(self, path: str) -> Path:
        """Resolve a skill file path."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p

    def load(self, path: str) -> str:
        """Load a single skill file."""
        resolved = self._resolve_path(path)
        if resolved.exists():
            return resolved.read_text(encoding="utf-8").strip()
        return f"[Skill file not found: {path}]"

    def load_many(self, paths: list[str]) -> str:
        """Load multiple skill files and format them."""
        parts: list[str] = []
        for path in paths:
            content = self.load(path)
            name = Path(path).stem
            parts.append(f"### Skill: {name}\n\n{content}")
        if not parts:
            return ""
        return "## Skills\n\n" + "\n\n---\n\n".join(parts)

    def list_available(self) -> list[str]:
        """List all available skill files."""
        skills_dir = self.base_dir / "skills"
        if not skills_dir.exists():
            return []
        return [str(p.relative_to(self.base_dir)) for p in sorted(skills_dir.glob("*.md"))]
