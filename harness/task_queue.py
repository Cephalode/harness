"""Sequential task queue for orchestrator message processing.

Ensures only one message is processed at a time, preventing concurrent
GLM-5.1 requests from blocking HTTP handlers. Tasks are queued, processed
FIFO, and results are stored for retrieval.

Queue events are emitted to the EventBus so the dashboard can show
queue position and status in real-time.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import asdict, dataclass, field
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .events import EventBus
    from .orchestrator import Orchestrator

logger = logging.getLogger(__name__)


@dataclass
class QueuedTask:
    """A single task in the queue."""
    task_id: str
    message: str
    status: str = "queued"  # queued, running, completed, failed
    position: int = 0
    result: str = ""
    error: str = ""
    created_at: float = field(default_factory=time.time)
    started_at: float = 0.0
    completed_at: float = 0.0
    platform: str = "dashboard"


class TaskQueue:
    """Async FIFO task queue with single-worker processing.

    Usage:
        queue = TaskQueue(orchestrator, event_bus)
        await queue.start()  # starts the background worker
        task_id = await queue.enqueue("build the auth system")
        # ... later ...
        result = queue.get_result(task_id)
    """

    def __init__(
        self,
        orchestrator: Orchestrator,
        event_bus: EventBus | None = None,
        state_store: Any | None = None,
    ) -> None:
        self._orchestrator = orchestrator
        self._event_bus = event_bus
        self._state_store = state_store
        self._queue: asyncio.Queue[QueuedTask] = asyncio.Queue()
        self._tasks: dict[str, QueuedTask] = {}
        self._worker_task: asyncio.Task | None = None
        self._running = False
        self._current_task: QueuedTask | None = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Start the background worker."""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())
        logger.info("TaskQueue started")

    async def stop(self) -> None:
        """Stop the worker and cancel current task."""
        self._running = False
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        logger.info("TaskQueue stopped")

    async def enqueue(self, message: str, platform: str = "dashboard") -> str:
        """Add a message to the queue. Returns task_id immediately."""
        task_id = uuid.uuid4().hex[:12]
        task = QueuedTask(
            task_id=task_id,
            message=message,
            platform=platform,
        )

        async with self._lock:
            task.position = self._queue.qsize() + (1 if self._current_task else 0)

        self._tasks[task_id] = task
        await self._queue.put(task)

        # Emit queue event
        if self._event_bus:
            from .events import HarnessEvent
            self._event_bus.emit(HarnessEvent(
                "task_queued",
                data={
                    "task_id": task_id,
                    "message": message[:100],
                    "position": task.position,
                },
            ))

        logger.info("Enqueued task %s: %s (position: %d)", task_id, message[:50], task.position)
        return task_id

    def get_status(self) -> dict[str, Any]:
        """Get full queue status."""
        tasks_info = []
        for task in self._tasks.values():
            tasks_info.append(asdict(task))

        return {
            "queue_length": self._queue.qsize(),
            "is_processing": self._current_task is not None,
            "current_task": asdict(self._current_task) if self._current_task else None,
            "tasks": tasks_info,
            "total_processed": sum(1 for t in self._tasks.values() if t.status in ("completed", "failed")),
        }

    def get_task(self, task_id: str) -> QueuedTask | None:
        """Get a specific task by ID."""
        return self._tasks.get(task_id)

    def get_result(self, task_id: str) -> dict[str, Any] | None:
        """Get the result of a completed task."""
        task = self._tasks.get(task_id)
        if not task:
            return None
        return asdict(task)

    async def _worker(self) -> None:
        """Background worker: processes tasks from the queue one at a time."""
        while self._running:
            try:
                task = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            await self._process_task(task)

    async def _process_task(self, task: QueuedTask) -> None:
        """Process a single task through the orchestrator."""
        task.status = "running"
        task.started_at = time.time()
        self._current_task = task

        # Update positions for remaining queued tasks
        self._update_positions()

        if self._event_bus:
            from .events import HarnessEvent
            self._event_bus.emit(HarnessEvent(
                "task_started",
                data={
                    "task_id": task.task_id,
                    "message": task.message[:100],
                },
            ))

        logger.info("Processing task %s: %s", task.task_id, task.message[:80])

        try:
            result = await self._orchestrator.process_message(task.message)
            task.status = "completed"
            task.result = result
            task.completed_at = time.time()

            if self._event_bus:
                self._event_bus.emit(HarnessEvent(
                    "task_completed",
                    data={
                        "task_id": task.task_id,
                        "result_length": len(result),
                        "duration": task.completed_at - task.started_at,
                    },
                ))

            logger.info(
                "Completed task %s in %.1fs",
                task.task_id,
                task.completed_at - task.started_at,
            )

        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.completed_at = time.time()

            if self._event_bus:
                self._event_bus.emit(HarnessEvent(
                    "task_failed",
                    data={
                        "task_id": task.task_id,
                        "error": str(exc)[:200],
                    },
                ))

            logger.error("Task %s failed: %s", task.task_id, exc)

        finally:
            # Clear state store task regardless of success/failure
            if self._state_store:
                try:
                    await self._state_store.clear_task()
                except Exception:
                    logger.warning("Failed to clear state store task", exc_info=True)
            self._current_task = None
            self._update_positions()

    def _update_positions(self) -> None:
        """Update position numbers for all queued tasks."""
        position = 1 if self._current_task else 0
        queued = [t for t in self._tasks.values() if t.status == "queued"]
        queued.sort(key=lambda t: t.created_at)
        for i, t in enumerate(queued):
            t.position = position + i
