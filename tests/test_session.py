"""Tests for harness.session — session management and conversation logging."""

import json
import time

import pytest

from harness.session import Message, Session


# ─── Message ──────────────────────────────────────────────────

class TestMessage:
    def test_defaults(self):
        msg = Message(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.agent is None
        assert msg.team is None
        assert msg.metadata == {}
        assert isinstance(msg.timestamp, float)

    def test_custom_values(self):
        msg = Message(
            role="assistant",
            content="response",
            agent="orchestrator",
            team="engineering",
            metadata={"model": "gpt-4o"},
        )
        assert msg.agent == "orchestrator"
        assert msg.team == "engineering"
        assert msg.metadata["model"] == "gpt-4o"


# ─── Session init ─────────────────────────────────────────────

class TestSessionInit:
    def test_creates_session_dir(self, tmp_path):
        sessions_dir = tmp_path / "sessions"
        session = Session(session_id="test123", sessions_dir=str(sessions_dir))
        assert sessions_dir.exists()

    def test_generates_session_id(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        assert len(session.session_id) == 12

    def test_custom_session_id(self, tmp_path):
        session = Session(session_id="abc", sessions_dir=str(tmp_path))
        assert session.session_id == "abc"

    def test_log_path(self, tmp_path):
        session = Session(session_id="myid", sessions_dir=str(tmp_path))
        assert session.log_path.name == "myid.jsonl"

    def test_empty_messages(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        assert session.messages == []


# ─── add_message / logging ────────────────────────────────────

class TestSessionAddMessage:
    def test_add_user_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        msg = session.add_message(role="user", content="Hello!")
        assert msg.role == "user"
        assert msg.content == "Hello!"
        assert len(session.messages) == 1

    def test_add_assistant_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        msg = session.add_message(
            role="assistant", content="Hi!", agent="orchestrator"
        )
        assert msg.agent == "orchestrator"
        assert session.messages[0] is msg

    def test_log_file_written(self, tmp_path):
        session = Session(session_id="logtest", sessions_dir=str(tmp_path))
        session.add_message(role="user", content="logged msg")
        log_content = session.log_path.read_text()
        assert "logged msg" in log_content
        entry = json.loads(log_content.strip())
        assert entry["session_id"] == "logtest"
        assert entry["role"] == "user"

    def test_multiple_messages_append(self, tmp_path):
        session = Session(session_id="multi", sessions_dir=str(tmp_path))
        session.add_message(role="user", content="first")
        session.add_message(role="assistant", content="second", agent="bot")
        lines = session.log_path.read_text().strip().splitlines()
        assert len(lines) == 2


# ─── get_conversation_text ────────────────────────────────────

class TestSessionConversationText:
    def test_empty_session(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        assert session.get_conversation_text() == ""

    def test_formats_user_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="user", content="What is 2+2?")
        text = session.get_conversation_text()
        assert "User: What is 2+2?" in text

    def test_formats_assistant_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(
            role="assistant", content="4", agent="orchestrator"
        )
        text = session.get_conversation_text()
        assert "orchestrator: 4" in text

    def test_formats_agent_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="agent", content="result", agent="worker1")
        text = session.get_conversation_text()
        assert "[worker1]: result" in text

    def test_formats_system_message(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="system", content="init")
        text = session.get_conversation_text()
        assert "System: init" in text

    def test_max_messages(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        for i in range(10):
            session.add_message(role="user", content=f"msg {i}")
        text = session.get_conversation_text(max_messages=3)
        # Should only include last 3
        assert "msg 7" in text
        assert "msg 9" in text
        assert "msg 0" not in text

    def test_assistant_default_agent_label(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="assistant", content="hi")
        text = session.get_conversation_text()
        assert "orchestrator: hi" in text


# ─── compact ──────────────────────────────────────────────────

class TestSessionCompact:
    def test_compact_keeps_first_and_recent(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="user", content="first")
        for i in range(2, 10):
            session.add_message(role="assistant", content=f"msg {i}")
        session.compact()
        assert len(session.messages) == 4  # first + 3 recent
        assert session.messages[0].content == "first"

    def test_compact_short_session_no_op(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="user", content="a")
        session.add_message(role="assistant", content="b")
        session.compact()
        assert len(session.messages) == 2


# ─── clear ────────────────────────────────────────────────────

class TestSessionClear:
    def test_clear_removes_all_messages(self, tmp_path):
        session = Session(sessions_dir=str(tmp_path))
        session.add_message(role="user", content="a")
        session.add_message(role="user", content="b")
        session.clear()
        assert len(session.messages) == 0


# ─── load_from_log ────────────────────────────────────────────

class TestSessionLoadFromLog:
    def test_load_from_existing_log(self, tmp_path):
        session = Session(session_id="loadtest", sessions_dir=str(tmp_path))
        session.add_message(role="user", content="saved msg")
        session.add_message(role="assistant", content="reply", agent="bot")

        # Create new session with same ID and load
        session2 = Session(session_id="loadtest", sessions_dir=str(tmp_path))
        session2.load_from_log()
        assert len(session2.messages) == 2
        assert session2.messages[0].content == "saved msg"
        assert session2.messages[1].agent == "bot"

    def test_load_nonexistent_log(self, tmp_path):
        session = Session(session_id="nonexistent", sessions_dir=str(tmp_path))
        session.load_from_log()
        assert session.messages == []

    def test_load_handles_corrupt_lines(self, tmp_path):
        session = Session(session_id="corrupt", sessions_dir=str(tmp_path))
        session.add_message(role="user", content="good msg")
        # Append a corrupt line to the log
        with open(session.log_path, "a") as f:
            f.write("not valid json\n")
        session2 = Session(session_id="corrupt", sessions_dir=str(tmp_path))
        session2.load_from_log()
        assert len(session2.messages) == 1
        assert session2.messages[0].content == "good msg"
