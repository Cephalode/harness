"""Session management and conversation logging to JSONL."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any


@dataclass
class Message:
    """A single message in a conversation."""
    role: str  # "user", "assistant", "system", "agent"
    content: str
    agent: str | None = None
    team: str | None = None
    timestamp: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)


class Session:
    """Manages a single conversation session with JSONL logging."""

    def __init__(self, session_id: str | None = None, sessions_dir: str = "sessions") -> None:
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.sessions_dir = Path(sessions_dir)
        self.messages: list[Message] = []
        self.created_at = time.time()
        self._log_path = self.sessions_dir / f"{self.session_id}.jsonl"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

    @property
    def log_path(self) -> Path:
        return self._log_path

    def add_message(
        self,
        role: str,
        content: str,
        agent: str | None = None,
        team: str | None = None,
        **metadata: Any,
    ) -> Message:
        """Add a message and append it to the JSONL log."""
        msg = Message(
            role=role,
            content=content,
            agent=agent,
            team=team,
            metadata=metadata,
        )
        self.messages.append(msg)
        self._append_to_log(msg)
        return msg

    def _append_to_log(self, msg: Message) -> None:
        """Append a message to the JSONL log file."""
        entry = {
            "session_id": self.session_id,
            "role": msg.role,
            "content": msg.content,
            "agent": msg.agent,
            "team": msg.team,
            "timestamp": msg.timestamp,
            "metadata": msg.metadata,
        }
        with open(self._log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_conversation_text(self, max_messages: int | None = None) -> str:
        """Get the conversation as formatted text for context injection."""
        msgs = self.messages
        if max_messages and len(msgs) > max_messages:
            msgs = msgs[-max_messages:]
        lines: list[str] = []
        for msg in msgs:
            if msg.role == "user":
                lines.append(f"User: {msg.content}")
            elif msg.role == "assistant":
                agent_label = msg.agent or "orchestrator"
                lines.append(f"{agent_label}: {msg.content}")
            elif msg.role == "agent":
                agent_label = msg.agent or "agent"
                lines.append(f"[{agent_label}]: {msg.content}")
            elif msg.role == "system":
                lines.append(f"System: {msg.content}")
        return "\n".join(lines)

    def compact(self) -> None:
        """Compact conversation history — keep first message and last N messages."""
        if len(self.messages) <= 4:
            return
        # Keep first user message + recent context
        first = self.messages[0]
        recent = self.messages[-3:]
        self.messages = [first] + recent

    def clear(self) -> None:
        """Clear all messages in this session."""
        self.messages.clear()

    def load_from_log(self) -> None:
        """Load messages from the JSONL log file."""
        if not self._log_path.exists():
            return
        self.messages.clear()
        with open(self._log_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    self.messages.append(
                        Message(
                            role=entry["role"],
                            content=entry["content"],
                            agent=entry.get("agent"),
                            team=entry.get("team"),
                            timestamp=entry.get("timestamp", time.time()),
                            metadata=entry.get("metadata", {}),
                        )
                    )
                except (json.JSONDecodeError, KeyError):
                    continue
