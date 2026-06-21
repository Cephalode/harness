"""Tests for harness.state — async persistent state store."""

import asyncio
import json
import pytest
from dataclasses import asdict

from harness.state import (
    AgentState,
    TaskState,
    StageState,
    StateStore,
    _atomic_write,
)


# ─── Data models ───────────────────────────────────────────────

class TestAgentState:
    def test_defaults(self):
        a = AgentState(name="test")
        assert a.status == "idle"
        assert a.model == ""
        assert a.team is None
        assert a.last_message == ""
        assert a.last_updated == 0.0

    def test_asdict(self):
        a = AgentState(name="agent1", status="running", team="t1")
        d = asdict(a)
        assert d["name"] == "agent1"
        assert d["status"] == "running"
        assert d["team"] == "t1"


class TestTaskState:
    def test_defaults(self):
        t = TaskState(task="do stuff")
        assert t.platform == ""
        assert t.status == "pending"
        assert t.started_at == 0.0


class TestStageState:
    def test_defaults(self):
        s = StageState(stage_id="stage-1")
        assert s.team == ""
        assert s.round == 0
        assert s.status == "running"
        assert s.workers_used == []


# ─── _atomic_write ─────────────────────────────────────────────

class TestAtomicWrite:
    @pytest.mark.asyncio
    async def test_creates_file(self, tmp_path):
        target = tmp_path / "sub" / "test.json"
        await _atomic_write(target, '{"key": "value"}')
        assert target.exists()
        assert json.loads(target.read_text()) == {"key": "value"}

    @pytest.mark.asyncio
    async def test_overwrites_existing(self, tmp_path):
        target = tmp_path / "test.json"
        target.write_text("old")
        await _atomic_write(target, "new")
        assert target.read_text() == "new"


# ─── StateStore ───────────────────────────────────────────────

# Helper to create an initialized store synchronously
def _make_store(tmp_path):
    return StateStore(state_dir=str(tmp_path / "state"))


class TestStateStoreInit:
    @pytest.mark.asyncio
    async def test_init_creates_dirs(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        assert (tmp_path / "state" / "agents").exists()
        assert (tmp_path / "state" / "stages").exists()
        assert (tmp_path / "state" / "artifacts").exists()
        assert (tmp_path / "state" / "meta.json").exists()


class TestStateStoreAgents:
    @pytest.mark.asyncio
    async def test_set_and_get_agent(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_agent_status("agent1", "running", team="t1", model="gpt-4o")
        agent = await store.get_agent("agent1")
        assert agent is not None
        assert agent.name == "agent1"
        assert agent.status == "running"
        assert agent.team == "t1"
        assert agent.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_get_agent_not_found(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        assert await store.get_agent("nonexistent") is None

    @pytest.mark.asyncio
    async def test_update_agent_status(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_agent_status("a1", "running", team="t1")
        await store.set_agent_status("a1", "done", last_message="complete")
        agent = await store.get_agent("a1")
        assert agent.status == "done"
        assert agent.last_message == "complete"
        assert agent.team == "t1"

    @pytest.mark.asyncio
    async def test_get_agents(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_agent_status("a1", "running")
        await store.set_agent_status("a2", "idle")
        agents = await store.get_agents()
        assert len(agents) == 2
        assert "a1" in agents
        assert "a2" in agents


class TestStateStoreTask:
    @pytest.mark.asyncio
    async def test_set_and_get_task(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_task("Fix the bug", platform="cli")
        task = await store.get_task()
        assert task is not None
        assert task.task == "Fix the bug"
        assert task.platform == "cli"
        assert task.status == "running"

    @pytest.mark.asyncio
    async def test_clear_task(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_task("do stuff")
        await store.clear_task()
        assert await store.get_task() is None

    @pytest.mark.asyncio
    async def test_no_task_initially(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        assert await store.get_task() is None


class TestStateStoreStages:
    @pytest.mark.asyncio
    async def test_add_and_get_stages(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        stage = StageState(stage_id="s1", team="eng", round=1)
        await store.add_stage(stage)
        stages = await store.get_stages()
        assert len(stages) == 1
        assert stages[0].stage_id == "s1"
        assert stages[0].team == "eng"

    @pytest.mark.asyncio
    async def test_update_stage(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        stage = StageState(stage_id="s1", team="eng", status="running")
        await store.add_stage(stage)
        await store.update_stage("s1", {"status": "completed", "result_summary": "Done!"})
        stages = await store.get_stages()
        assert stages[0].status == "completed"
        assert stages[0].result_summary == "Done!"

    @pytest.mark.asyncio
    async def test_update_nonexistent_stage(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.update_stage("ghost", {"status": "completed"})

    @pytest.mark.asyncio
    async def test_stages_sorted_by_name(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.add_stage(StageState(stage_id="s2"))
        await store.add_stage(StageState(stage_id="s1"))
        await store.add_stage(StageState(stage_id="s3"))
        stages = await store.get_stages()
        ids = [s.stage_id for s in stages]
        assert ids == sorted(ids)


class TestStateStoreEvents:
    @pytest.mark.asyncio
    async def test_append_and_get_events(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.append_event({"type": "test", "timestamp": 100.0, "msg": "hello"})
        await store.append_event({"type": "test", "timestamp": 200.0, "msg": "world"})
        events = await store.get_events(since=0.0)
        assert len(events) == 2

    @pytest.mark.asyncio
    async def test_get_events_with_filter(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.append_event({"type": "a", "timestamp": 100.0})
        await store.append_event({"type": "b", "timestamp": 200.0})
        events = await store.get_events(since=150.0)
        assert len(events) == 1
        assert events[0]["type"] == "b"

    @pytest.mark.asyncio
    async def test_get_events_no_file(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        events = await store.get_events()
        assert events == []


class TestStateStoreMeta:
    @pytest.mark.asyncio
    async def test_meta(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_meta(session_id="abc123", platform="discord")
        meta = await store.get_meta()
        assert meta["session_id"] == "abc123"
        assert meta["platform"] == "discord"
        assert "last_updated" in meta

    @pytest.mark.asyncio
    async def test_snapshot(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_agent_status("a1", "running")
        await store.set_task("test task")
        snap = await store.snapshot()
        assert "meta" in snap
        assert "task" in snap
        assert "agents" in snap
        assert "stages" in snap
        assert "a1" in snap["agents"]


class TestStateStoreProcessEvent:
    @pytest.mark.asyncio
    async def test_process_event_agent_start(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()

        class FakeEvent:
            type = "agent_start"
            agent = "agent1"
            team = "t1"
            data = {"model": "gpt-4o"}
            timestamp = 1000.0

        store.process_event(FakeEvent())
        await asyncio.sleep(0.1)
        agent = await store.get_agent("agent1")
        assert agent is not None
        assert agent.status == "running"
        assert agent.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_process_event_session_start(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()

        class FakeEvent:
            type = "session_start"
            agent = None
            team = None
            data = {"message": "hello", "platform": "cli", "session_id": "s1"}
            timestamp = 1000.0

        store.process_event(FakeEvent())
        await asyncio.sleep(0.1)
        task = await store.get_task()
        assert task is not None
        assert task.task == "hello"

    @pytest.mark.asyncio
    async def test_process_event_session_end(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()
        await store.set_task("some task")

        class FakeEvent:
            type = "session_end"
            agent = None
            team = None
            data = {}
            timestamp = 1000.0

        store.process_event(FakeEvent())
        await asyncio.sleep(0.1)
        assert await store.get_task() is None

    @pytest.mark.asyncio
    async def test_process_event_agent_end_error(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()

        class FakeEvent:
            type = "agent_end"
            agent = "worker1"
            team = "eng"
            data = {"status": "error", "reason": "timeout"}
            timestamp = 1000.0

        store.process_event(FakeEvent())
        await asyncio.sleep(0.1)
        agent = await store.get_agent("worker1")
        assert agent is not None
        assert agent.status == "error"
        assert agent.last_message == "timeout"

    @pytest.mark.asyncio
    async def test_process_event_team_start(self, tmp_path):
        store = _make_store(tmp_path)
        await store.init()

        class FakeEvent:
            type = "team_start"
            agent = None
            team = "engineering"
            data = {"stage_id": "eng-1", "round": 2, "workers": ["w1", "w2"]}
            timestamp = 1000.0

        store.process_event(FakeEvent())
        await asyncio.sleep(0.1)
        stages = await store.get_stages()
        assert len(stages) == 1
        assert stages[0].stage_id == "eng-1"
        assert stages[0].team == "engineering"
        assert stages[0].round == 2
