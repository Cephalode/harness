"""File-based persistent state store for Harness orchestration system.

Provides a single source of truth for runtime state, persisted as JSON files
with atomic writes. Designed to work alongside the EventBus for event-driven
state mutations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass
class AgentState:
    """Snapshot of a single agent's current state."""

    name: str
    status: str = "idle"  # "idle", "running", "done", "error"
    model: str = ""
    team: str | None = None
    last_message: str = ""
    last_updated: float = 0.0


@dataclass
class TaskState:
    """Currently active task."""

    task: str
    platform: str = ""  # "cli", "discord", "dashboard"
    started_at: float = 0.0
    status: str = "pending"  # "pending", "running", "completed", "failed"


@dataclass
class StageState:
    """State of a single orchestration stage (one team round)."""

    stage_id: str
    team: str = ""
    round: int = 0
    workers_used: list[str] = field(default_factory=list)
    status: str = "running"  # "running", "completed"
    result_summary: str = ""
    started_at: float = 0.0
    completed_at: float = 0.0


# ---------------------------------------------------------------------------
# Atomic write helper
# ---------------------------------------------------------------------------


async def _atomic_write(path: Path, data: str) -> None:
    """Write *data* to *path* atomically via tmp-file + os.rename."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as fh:
        await fh.write(data)
        await fh.flush()
        os.fsync(fh.fileno())
    os.rename(tmp_path, path)


# ---------------------------------------------------------------------------
# StateStore
# ---------------------------------------------------------------------------


class StateStore:
    """File-based persistent state store.

    Directory layout::

        state/
        ├── active_task.json
        ├── agents/
        │   └── {name}.json
        ├── stages/
        │   └── {stage_id}.json
        ├── artifacts/
        ├── messages.jsonl
        └── meta.json
    """

    def __init__(self, state_dir: str = "state") -> None:
        self.state_dir = Path(state_dir)
        self._agents_dir = self.state_dir / "agents"
        self._stages_dir = self.state_dir / "stages"
        self._artifacts_dir = self.state_dir / "artifacts"
        self._meta_path = self.state_dir / "meta.json"
        self._task_path = self.state_dir / "active_task.json"
        self._events_path = self.state_dir / "messages.jsonl"
        self._meta: dict = {}

    # -- lifecycle -----------------------------------------------------------

    async def init(self) -> None:
        """Create directory structure and load (or create) meta.json."""
        self._agents_dir.mkdir(parents=True, exist_ok=True)
        self._stages_dir.mkdir(parents=True, exist_ok=True)
        self._artifacts_dir.mkdir(parents=True, exist_ok=True)

        if self._meta_path.exists():
            async with aiofiles.open(self._meta_path, "r", encoding="utf-8") as fh:
                raw = await fh.read()
                self._meta = json.loads(raw) if raw.strip() else {}
        else:
            self._meta = {
                "session_id": "",
                "created_at": time.time(),
                "last_updated": time.time(),
                "platform": "",
            }
            await self._flush_meta()

    # -- snapshot ------------------------------------------------------------

    async def snapshot(self) -> dict:
        """Return the full state tree as a dict suitable for API responses."""
        agents = await self.get_agents()
        task = await self.get_task()
        stages = await self.get_stages()
        meta = await self.get_meta()
        events = await self.get_events(since=0.0)
        return {
            "meta": meta,
            "task": asdict(task) if task else None,
            "agents": {name: asdict(a) for name, a in agents.items()},
            "stages": [asdict(s) for s in stages],
            "event_count": len(events),
        }

    # -- agents --------------------------------------------------------------

    async def get_agents(self) -> dict[str, AgentState]:
        """Read all agent state files from ``state/agents/``."""
        agents: dict[str, AgentState] = {}
        if not self._agents_dir.exists():
            return agents
        for path in self._agents_dir.glob("*.json"):
            try:
                async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                    raw = await fh.read()
                data = json.loads(raw)
                agent = AgentState(**data)
                agents[agent.name] = agent
            except Exception:
                logger.warning("Failed to read agent state from %s", path, exc_info=True)
        return agents

    async def get_agent(self, name: str) -> AgentState | None:
        """Return a single agent's state, or ``None`` if not found."""
        path = self._agents_dir / f"{name}.json"
        if not path.exists():
            return None
        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                raw = await fh.read()
            data = json.loads(raw)
            return AgentState(**data)
        except Exception:
            logger.warning("Failed to read agent state for %s", name, exc_info=True)
            return None

    async def set_agent_status(
        self, name: str, status: str, **kwargs: object
    ) -> None:
        """Write agent state to ``state/agents/{name}.json`` with atomic write."""
        existing = await self.get_agent(name)
        now = time.time()
        if existing is None:
            agent = AgentState(name=name, status=status, last_updated=now, **kwargs)  # type: ignore[arg-type]
        else:
            agent = AgentState(
                name=existing.name,
                status=status,
                model=kwargs.get("model", existing.model) if "model" in kwargs else existing.model,  # type: ignore[arg-type]
                team=kwargs.get("team", existing.team) if "team" in kwargs else existing.team,  # type: ignore[arg-type]
                last_message=kwargs.get("last_message", existing.last_message) if "last_message" in kwargs else existing.last_message,  # type: ignore[arg-type]
                last_updated=now,
            )
        data = json.dumps(asdict(agent), ensure_ascii=False, indent=2)
        path = self._agents_dir / f"{name}.json"
        await _atomic_write(path, data)

    # -- task ----------------------------------------------------------------

    async def get_task(self) -> TaskState | None:
        """Read the current active task, or ``None`` if none set."""
        if not self._task_path.exists():
            return None
        try:
            async with aiofiles.open(self._task_path, "r", encoding="utf-8") as fh:
                raw = await fh.read()
            data = json.loads(raw)
            return TaskState(**data)
        except Exception:
            logger.warning("Failed to read active task", exc_info=True)
            return None

    async def set_task(self, task: str, platform: str = "") -> None:
        """Write the active task to ``state/active_task.json``."""
        ts = TaskState(
            task=task,
            platform=platform,
            started_at=time.time(),
            status="running",
        )
        data = json.dumps(asdict(ts), ensure_ascii=False, indent=2)
        await _atomic_write(self._task_path, data)

    async def clear_task(self) -> None:
        """Delete the active task file."""
        if self._task_path.exists():
            self._task_path.unlink()

    # -- stages --------------------------------------------------------------

    async def get_stages(self) -> list[StageState]:
        """Read all stage files from ``state/stages/``."""
        stages: list[StageState] = []
        if not self._stages_dir.exists():
            return stages
        for path in sorted(self._stages_dir.glob("*.json")):
            try:
                async with aiofiles.open(path, "r", encoding="utf-8") as fh:
                    raw = await fh.read()
                data = json.loads(raw)
                stages.append(StageState(**data))
            except Exception:
                logger.warning("Failed to read stage from %s", path, exc_info=True)
        return stages

    async def add_stage(self, stage: StageState) -> None:
        """Persist a new stage to ``state/stages/{stage_id}.json``."""
        data = json.dumps(asdict(stage), ensure_ascii=False, indent=2)
        path = self._stages_dir / f"{stage.stage_id}.json"
        await _atomic_write(path, data)

    async def update_stage(self, stage_id: str, data: dict) -> None:
        """Update an existing stage file with the given *data* dict."""
        path = self._stages_dir / f"{stage_id}.json"
        if not path.exists():
            logger.warning("update_stage: stage %s not found", stage_id)
            return
        async with aiofiles.open(path, "r", encoding="utf-8") as fh:
            raw = await fh.read()
        existing = json.loads(raw)
        existing.update(data)
        updated = json.dumps(existing, ensure_ascii=False, indent=2)
        await _atomic_write(path, updated)

    # -- events (messages.jsonl) --------------------------------------------

    async def append_event(self, event: dict) -> None:
        """Append a JSON line to ``state/messages.jsonl``."""
        line = json.dumps(event, ensure_ascii=False) + "\n"
        async with aiofiles.open(self._events_path, "a", encoding="utf-8") as fh:
            await fh.write(line)

    async def get_events(self, since: float = 0.0) -> list[dict]:
        """Read events from ``messages.jsonl`` with *timestamp* > *since*."""
        events: list[dict] = []
        if not self._events_path.exists():
            return events
        async with aiofiles.open(self._events_path, "r", encoding="utf-8") as fh:
            async for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    ev = json.loads(line)
                    if ev.get("timestamp", 0.0) > since:
                        events.append(ev)
                except json.JSONDecodeError:
                    continue
        return events

    # -- meta ----------------------------------------------------------------

    async def get_meta(self) -> dict:
        """Return the meta dict (in-memory copy, refreshed from disk)."""
        if self._meta_path.exists():
            try:
                async with aiofiles.open(self._meta_path, "r", encoding="utf-8") as fh:
                    raw = await fh.read()
                self._meta = json.loads(raw) if raw.strip() else self._meta
            except Exception:
                logger.warning("Failed to read meta.json", exc_info=True)
        return dict(self._meta)

    async def set_meta(self, **kwargs: object) -> None:
        """Update meta.json with the given key/value pairs."""
        self._meta.update(kwargs)
        self._meta["last_updated"] = time.time()
        await self._flush_meta()

    async def _flush_meta(self) -> None:
        """Write in-memory meta dict to disk."""
        data = json.dumps(self._meta, ensure_ascii=False, indent=2)
        await _atomic_write(self._meta_path, data)

    # -- event processing ----------------------------------------------------

    def process_event(self, event: object) -> None:
        """Translate a :class:`HarnessEvent` into state mutations.

        Accepts any object with ``.type``, ``.agent``, ``.team``, ``.data``,
        ``.timestamp`` attributes (duck-typed to avoid circular imports).

        Fire-and-forget: internally schedules work via
        :func:`asyncio.create_task` so the caller is never blocked.
        Must be called from within a running event loop.
        """
        asyncio.create_task(self._handle_event(event))

    # -- internal event handler ----------------------------------------------

    async def _handle_event(self, event: object) -> None:
        """Actually process an event. Called as a background task."""
        try:
            event_type: str = getattr(event, "type", "unknown")
            agent_name: str | None = getattr(event, "agent", None)
            team_name: str | None = getattr(event, "team", None)
            event_data: dict = getattr(event, "data", {}) or {}
            timestamp: float = getattr(event, "timestamp", 0.0) or time.time()

            # All events get appended to the message log
            event_dict = {
                "type": event_type,
                "agent": agent_name,
                "team": team_name,
                "data": event_data,
                "timestamp": timestamp,
            }
            await self.append_event(event_dict)

            # Dispatch on event type
            if event_type == "agent_start":
                await self.set_agent_status(
                    agent_name or "unknown",
                    "running",
                    team=team_name,
                    model=event_data.get("model", ""),
                )

            elif event_type == "agent_end":
                status = "error" if event_data.get("status") == "error" else "done"
                await self.set_agent_status(
                    agent_name or "unknown",
                    status,
                    team=team_name,
                    last_message=event_data.get("summary", ""),
                )

            elif event_type == "worker_status":
                await self.set_agent_status(
                    agent_name or "unknown",
                    event_data.get("status", "running"),
                    team=team_name,
                    last_message=event_data.get("message", ""),
                )

            elif event_type == "team_start":
                stage_id = event_data.get("stage_id", f"{team_name}-{timestamp:.0f}")
                stage = StageState(
                    stage_id=stage_id,
                    team=team_name or "",
                    round=event_data.get("round", 0),
                    workers_used=event_data.get("workers", []),
                    status="running",
                    started_at=timestamp,
                )
                await self.add_stage(stage)

            elif event_type == "team_done":
                stage_id = event_data.get("stage_id", f"{team_name}-{timestamp:.0f}")
                await self.update_stage(
                    stage_id,
                    {
                        "status": "completed",
                        "result_summary": event_data.get("summary", ""),
                        "completed_at": time.time(),
                        "workers_used": event_data.get("workers", []),
                    },
                )

            elif event_type == "session_start":
                task_text = event_data.get("message", "") or event_data.get("task", "")
                platform = event_data.get("platform", "")
                if task_text:
                    await self.set_task(task_text, platform)
                await self.set_meta(
                    session_id=event_data.get("session_id", ""),
                    platform=platform,
                )

            elif event_type == "session_end":
                await self.clear_task()

        except Exception:
            logger.warning(
                "StateStore.process_event failed", exc_info=True
            )
