"""File permission enforcement per agent — domain locking."""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath

from .config import DomainConfig


class DomainEnforcer:
    """Enforces file read/write permissions for an agent based on domain config."""

    def __init__(self, domain: DomainConfig, base_dir: str = ".") -> None:
        self.domain = domain
        self.base_dir = Path(base_dir).resolve()

    def _resolve(self, path: str) -> Path:
        """Resolve a path relative to base_dir."""
        p = Path(path)
        if not p.is_absolute():
            p = self.base_dir / p
        return p.resolve()

    def _matches_prefix(self, path: Path, prefixes: list[str]) -> bool:
        """Check if path falls under any of the allowed prefixes."""
        if "." in prefixes:
            return True  # full access
        for prefix in prefixes:
            prefix_path = (self.base_dir / prefix).resolve()
            try:
                path.relative_to(prefix_path)
                return True
            except ValueError:
                continue
        return False

    def can_read(self, path: str) -> bool:
        """Check if the agent is allowed to read this path."""
        resolved = self._resolve(path)
        return self._matches_prefix(resolved, self.domain.read)

    def can_write(self, path: str) -> bool:
        """Check if the agent is allowed to write/update this path."""
        resolved = self._resolve(path)
        return self._matches_prefix(resolved, self.domain.update)

    def filter_writes(self, paths: list[str]) -> list[str]:
        """Filter a list of paths to only those the agent can write to."""
        return [p for p in paths if self.can_write(p)]

    def format_domain_rules(self) -> str:
        """Format domain rules for injection into system prompt."""
        read_str = ", ".join(self.domain.read) if self.domain.read else "none"
        write_str = ", ".join(self.domain.update) if self.domain.update else "none"
        return (
            f"## Domain Permissions\n"
            f"You are ONLY allowed to modify files in these directories:\n"
            f"- **Read access**: {read_str}\n"
            f"- **Write/Update access**: {write_str}\n\n"
            f"You MUST NOT attempt to read or modify files outside your permitted domains.\n"
            f"If a task requires access outside your domain, respond explaining what you need "
            f"and request that it be delegated to an agent with appropriate permissions.\n"
        )
