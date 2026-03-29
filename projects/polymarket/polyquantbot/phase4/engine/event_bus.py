"""Async fan-out event bus for Phase 4 event-driven architecture."""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Coroutine

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
MARKET_DATA = "MARKET_DATA"
SIGNAL = "SIGNAL"
FILTERED_SIGNAL = "FILTERED_SIGNAL"
POSITION_SIZED = "POSITION_SIZED"
ORDER_FILLED = "ORDER_FILLED"
STATE_UPDATED = "STATE_UPDATED"
TELEGRAM_NOTIFY = "TELEGRAM_NOTIFY"
SYSTEM_ERROR = "SYSTEM_ERROR"
CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
HEALTH_CHECK = "HEALTH_CHECK"

Handler = Callable[["EventEnvelope"], Coroutine[Any, Any, None]]


@dataclass
class EventEnvelope:
    """Immutable event container propagated through the pipeline."""

    event_type: str
    source: str
    payload: dict[str, Any]
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    market_id: str | None = None


class EventBus:
    """Async pub/sub bus with per-subscriber queues and worker tasks."""

    def __init__(self) -> None:
        """Initialise empty subscriber registry."""
        self._subscribers: dict[str, list[asyncio.Queue[EventEnvelope]]] = {}
        self._tasks: list[asyncio.Task] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register an async handler for event_type.

        Each handler gets its own Queue so a slow handler can't block others.
        """
        queue: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        if event_type not in self._subscribers:
            self._subscribers[event_type] = []
        self._subscribers[event_type].append(queue)

        async def _worker() -> None:
            while True:
                envelope = await queue.get()
                try:
                    await handler(envelope)
                except Exception as exc:
                    log.error(
                        "event_handler_error",
                        event_type=event_type,
                        correlation_id=envelope.correlation_id,
                        error=str(exc),
                    )
                finally:
                    queue.task_done()

        task = asyncio.create_task(_worker())
        self._tasks.append(task)

    async def publish(self, envelope: EventEnvelope) -> None:
        """Fan-out envelope to all subscribers of its event_type."""
        queues = self._subscribers.get(envelope.event_type, [])
        for q in queues:
            await q.put(envelope)
        log.debug(
            "event_published",
            event_type=envelope.event_type,
            correlation_id=envelope.correlation_id,
            market_id=envelope.market_id,
            subscribers=len(queues),
        )

    async def shutdown(self) -> None:
        """Cancel all worker tasks."""
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        log.info("event_bus_shutdown", tasks_cancelled=len(self._tasks))
