"""Tests for harness.events — event bus, event serialization."""

import asyncio
import json
import time

import pytest

from harness.events import EventBus, HarnessEvent


# ─── HarnessEvent ─────────────────────────────────────────────

class TestHarnessEvent:
    def test_defaults(self):
        event = HarnessEvent(type="test")
        assert event.type == "test"
        assert event.agent is None
        assert event.team is None
        assert event.data == {}
        assert isinstance(event.timestamp, float)

    def test_custom_values(self):
        event = HarnessEvent(
            type="agent_start",
            agent="worker1",
            team="engineering",
            data={"model": "gpt-4o"},
        )
        assert event.agent == "worker1"
        assert event.team == "engineering"
        assert event.data["model"] == "gpt-4o"

    def test_to_json(self):
        event = HarnessEvent(
            type="agent_start",
            agent="a1",
            team="t1",
            data={"key": "value"},
            timestamp=12345.0,
        )
        raw = event.to_json()
        parsed = json.loads(raw)
        assert parsed["type"] == "agent_start"
        assert parsed["agent"] == "a1"
        assert parsed["team"] == "t1"
        assert parsed["data"]["key"] == "value"
        assert parsed["timestamp"] == 12345.0

    def test_to_json_unicode(self):
        event = HarnessEvent(type="test", data={"msg": "日本語テスト"})
        raw = event.to_json()
        assert "日本語テスト" in raw

    def test_from_json(self):
        data = {
            "type": "agent_end",
            "agent": "worker2",
            "team": "qa",
            "data": {"status": "success"},
            "timestamp": 999.0,
        }
        event = HarnessEvent.from_json(data)
        assert event.type == "agent_end"
        assert event.agent == "worker2"
        assert event.team == "qa"
        assert event.data["status"] == "success"
        assert event.timestamp == 999.0

    def test_from_json_missing_fields(self):
        event = HarnessEvent.from_json({"type": "ping"})
        assert event.type == "ping"
        assert event.agent is None
        assert event.data == {}

    def test_from_json_empty(self):
        event = HarnessEvent.from_json({})
        assert event.type == "unknown"

    def test_roundtrip(self):
        original = HarnessEvent(
            type="custom",
            agent="a",
            team="t",
            data={"x": 1},
            timestamp=42.0,
        )
        json_str = original.to_json()
        restored = HarnessEvent.from_json(json.loads(json_str))
        assert restored.type == original.type
        assert restored.agent == original.agent
        assert restored.team == original.team
        assert restored.data == original.data


# ─── EventBus ─────────────────────────────────────────────────

class TestEventBus:
    def test_subscribe_returns_queue(self):
        bus = EventBus()
        q = bus.subscribe()
        assert isinstance(q, asyncio.Queue)

    def test_emit_delivers_to_subscriber(self):
        bus = EventBus()
        q = bus.subscribe()
        event = HarnessEvent(type="test", data={"key": "val"})
        bus.emit(event)
        received = q.get_nowait()
        assert received.type == "test"
        assert received.data["key"] == "val"

    def test_emit_delivers_to_multiple_subscribers(self):
        bus = EventBus()
        q1 = bus.subscribe()
        q2 = bus.subscribe()
        event = HarnessEvent(type="multi")
        bus.emit(event)
        assert q1.get_nowait() is event
        assert q2.get_nowait() is event

    def test_unsubscribe(self):
        bus = EventBus()
        q = bus.subscribe()
        bus.unsubscribe(q)
        event = HarnessEvent(type="after_unsub")
        bus.emit(event)
        assert q.empty()

    def test_unsubscribe_nonexistent_queue(self):
        bus = EventBus()
        other_q = asyncio.Queue()
        # Should not raise
        bus.unsubscribe(other_q)

    def test_history_tracks_events(self):
        bus = EventBus()
        bus.emit(HarnessEvent(type="e1", timestamp=100.0))
        bus.emit(HarnessEvent(type="e2", timestamp=200.0))
        bus.emit(HarnessEvent(type="e3", timestamp=300.0))
        assert len(bus._history) == 3

    def test_get_history_all(self):
        bus = EventBus()
        bus.emit(HarnessEvent(type="a", timestamp=100.0))
        bus.emit(HarnessEvent(type="b", timestamp=200.0))
        history = bus.get_history(since=0.0)
        assert len(history) == 2

    def test_get_history_since(self):
        bus = EventBus()
        bus.emit(HarnessEvent(type="a", timestamp=100.0))
        bus.emit(HarnessEvent(type="b", timestamp=200.0))
        bus.emit(HarnessEvent(type="c", timestamp=300.0))
        history = bus.get_history(since=150.0)
        assert len(history) == 2
        assert history[0].type == "b"

    def test_history_truncates_at_max(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.emit(HarnessEvent(type=f"e{i}"))
        assert len(bus._history) == 5
        # Should keep the last 5
        assert bus._history[0].type == "e5"
        assert bus._history[-1].type == "e9"

    def test_add_listener(self):
        bus = EventBus()
        received = []
        bus.add_listener(lambda e: received.append(e))
        event = HarnessEvent(type="listened")
        bus.emit(event)
        assert len(received) == 1
        assert received[0].type == "listened"
