"""Async fan-out EventBus — Phase 6.

Unchanged from Phase 5. Dual-priority queues:
  HIGH: ORDER_FILLED, STATE_UPDATED, PORTFOLIO_DECISION
  LOW:  MARKET_DATA and all others

HIGH priority consumers drain before LOW is processed.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Awaitable, Callable

import structlog

log = structlog.get_logger()

# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------
MARKET_DATA = "MARKET_DATA"
SIGNAL = "SIGNAL"
FILTERED_SIGNAL = "FILTERED_SIGNAL"
POSITION_SIZED = "POSITION_SIZED"
ORDER_REQUEST = "ORDER_REQUEST"
ORDER_FILLED = "ORDER_FILLED"
STATE_UPDATED = "STATE_UPDATED"
TELEGRAM_NOTIFY = "TELEGRAM_NOTIFY"
SYSTEM_ERROR = "SYSTEM_ERROR"
CIRCUIT_BREAKER_OPEN = "CIRCUIT_BREAKER_OPEN"
PORTFOLIO_DECISION = "PORTFOLIO_DECISION"

HIGH_PRIORITY_EVENTS: frozenset[str] = frozenset(
    {ORDER_FILLED, STATE_UPDATED, PORTFOLIO_DECISION}
)

Handler = Callable[["EventEnvelope"], Awaitable[None]]


@dataclass
class EventEnvelope:
    """Immutable event container propagated through the pipeline."""

    event_type: str
    source: str
    payload: dict
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp_ms: int = field(default_factory=lambda: int(time.time() * 1000))
    market_id: str | None = None

    @staticmethod
    def create(
        event_type: str,
        source: str,
        payload: dict,
        correlation_id: str | None = None,
        market_id: str | None = None,
    ) -> "EventEnvelope":
        """Factory method for creating envelopes with optional correlation ID."""
        return EventEnvelope(
            event_type=event_type,
            source=source,
            payload=payload,
            correlation_id=correlation_id or str(uuid.uuid4()),
            timestamp_ms=int(time.time() * 1000),
            market_id=market_id,
        )


class EventBus:
    """Async pub/sub bus with dual-priority per-subscriber queues."""

    def __init__(self) -> None:
        """Initialise empty subscriber registry."""
        self._high_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._low_queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        self._worker_tasks: list[asyncio.Task] = []

    def subscribe(self, event_type: str, handler: Handler) -> None:
        """Register an async handler. HIGH priority events get a dedicated high queue."""
        q: asyncio.Queue[EventEnvelope] = asyncio.Queue()
        if event_type in HIGH_PRIORITY_EVENTS:
            self._high_queues[event_type].append(q)
            priority = "HIGH"
        else:
            self._low_queues[event_type].append(q)
            priority = "LOW"

        async def worker() -> None:
            while True:
                envelope = await q.get()
                try:
                    await handler(envelope)
                except Exception as exc:
                    log.error(
                        "handler_exception",
                        event_type=event_type,
                        handler=handler.__name__,
                        correlation_id=envelope.correlation_id,
                        market_id=envelope.market_id,
                        error=str(exc),
                    )
                finally:
                    q.task_done()

        self._worker_tasks.append(asyncio.create_task(worker()))
        log.info(
            "handler_subscribed",
            event_type=event_type,
            handler=handler.__name__,
            priority=priority,
        )

    async def publish(self, envelope: EventEnvelope) -> None:
        """Fan-out envelope to all subscribers of its event_type."""
        if envelope.event_type in HIGH_PRIORITY_EVENTS:
            queues = self._high_queues.get(envelope.event_type, [])
            priority = "HIGH"
        else:
            queues = self._low_queues.get(envelope.event_type, [])
            priority = "LOW"

        for q in queues:
            await q.put(envelope)

        log.debug(
            "bus_publish",
            event_type=envelope.event_type,
            correlation_id=envelope.correlation_id,
            market_id=envelope.market_id,
            priority=priority,
            subscriber_count=len(queues),
        )

    async def shutdown(self) -> None:
        """Cancel all worker tasks."""
        for task in self._worker_tasks:
            task.cancel()
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        log.info("event_bus_shutdown", tasks_cancelled=len(self._worker_tasks))
