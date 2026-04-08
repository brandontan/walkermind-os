"""execution.event_logger — Structured lifecycle event model for observability."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import structlog

from .trace_context import ensure_trace_id

log = structlog.get_logger(__name__)

CANONICAL_OUTCOMES: set[str] = {
    "attempted",
    "allowed",
    "blocked",
    "executed",
    "partial_fill",
    "rejected",
    "failed",
    "skipped",
    "updated",
    "restore_success",
    "restore_failure",
}


@dataclass(frozen=True)
class TradeLifecycleEvent:
    trace_id: str
    event_type: str
    timestamp: str
    component: str
    outcome: str
    payload: dict[str, Any] = field(default_factory=dict)


class EventLogger:
    """Emit structured lifecycle events with canonical outcomes only."""

    def __init__(self) -> None:
        self._events: list[TradeLifecycleEvent] = []

    def emit(
        self,
        *,
        event_type: str,
        component: str,
        outcome: str,
        payload: dict[str, Any] | None = None,
        trace_id: str | None = None,
    ) -> TradeLifecycleEvent:
        if outcome not in CANONICAL_OUTCOMES:
            raise ValueError(f"Non-canonical outcome: {outcome}")
        event = TradeLifecycleEvent(
            trace_id=ensure_trace_id(trace_id),
            event_type=event_type,
            timestamp=datetime.now(timezone.utc).isoformat(),
            component=component,
            outcome=outcome,
            payload=payload or {},
        )
        self._events.append(event)
        log.info("trade_lifecycle_event", **asdict(event))
        return event

    def list_events(self) -> list[TradeLifecycleEvent]:
        return list(self._events)

    def clear(self) -> None:
        self._events.clear()


event_logger = EventLogger()


def reconstruct_lifecycle(trace_id: str, events: list[TradeLifecycleEvent]) -> list[TradeLifecycleEvent]:
    """Return ordered lifecycle events for a trace for replay/reconstruction."""
    selected = [event for event in events if event.trace_id == trace_id]
    return sorted(selected, key=lambda event: event.timestamp)
