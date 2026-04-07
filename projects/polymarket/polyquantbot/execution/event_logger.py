"""execution.event_logger — structured event emission and lifecycle replay."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Mapping

import structlog

log = structlog.get_logger(__name__)

CANONICAL_OUTCOMES: set[str] = {
    "blocked",
    "duplicate_blocked",
    "rejected",
    "partial_fill",
    "executed",
    "failed",
    "restore_failure",
    "restore_success",
}


@dataclass(frozen=True)
class StructuredEvent:
    trace_id: str
    event_type: str
    timestamp: float
    component: str
    payload: Dict[str, Any]


class EventLogger:
    """In-memory structured event logger with replay support."""

    def __init__(self) -> None:
        self._events: list[StructuredEvent] = []

    def emit(
        self,
        *,
        trace_id: str,
        event_type: str,
        component: str,
        payload: Mapping[str, Any] | None = None,
    ) -> StructuredEvent:
        _payload = dict(payload or {})
        self._enforce_outcome_taxonomy(_payload)
        event = StructuredEvent(
            trace_id=trace_id,
            event_type=event_type,
            timestamp=time.time(),
            component=component,
            payload=_payload,
        )
        self._events.append(event)
        log.info("structured_event", **asdict(event))
        return event

    def emit_failure(
        self,
        *,
        trace_id: str,
        component: str,
        error: Exception,
        context: Mapping[str, Any] | None = None,
    ) -> StructuredEvent:
        payload: dict[str, Any] = dict(context or {})
        payload.update(
            {
                "error_type": type(error).__name__,
                "component": component,
                "context": dict(context or {}),
                "error": str(error),
                "outcome": "failed",
            }
        )
        return self.emit(
            trace_id=trace_id,
            event_type="failure",
            component=component,
            payload=payload,
        )

    def replay(self, trace_id: str) -> List[Dict[str, Any]]:
        return [asdict(event) for event in self._events if event.trace_id == trace_id]

    def clear(self) -> None:
        self._events.clear()

    def _enforce_outcome_taxonomy(self, payload: dict[str, Any]) -> None:
        outcome = payload.get("outcome")
        if outcome is None:
            return
        outcome_s = str(outcome)
        if outcome_s not in CANONICAL_OUTCOMES:
            raise ValueError(f"invalid_outcome_taxonomy:{outcome_s}")


_EVENT_LOGGER = EventLogger()


def get_event_logger() -> EventLogger:
    return _EVENT_LOGGER
