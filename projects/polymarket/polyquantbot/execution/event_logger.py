from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

import structlog

from .trace_context import get_trace_id

log = structlog.get_logger(__name__)


class EventLogger:
    """Emit structured execution observability events."""

    def __init__(self, sink: Callable[[dict[str, Any]], None] | None = None) -> None:
        self._sink = sink

    def emit_event(
        self,
        *,
        event_type: str,
        component: str,
        outcome: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        event_payload: dict[str, Any] = {
            "trace_id": get_trace_id(),
            "event_type": event_type,
            "component": component,
            "outcome": outcome,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "payload": payload or {},
        }

        if self._sink is not None:
            self._sink(event_payload)

        if outcome == "failure":
            log.warning("execution_observability_event", **event_payload)
        else:
            log.info("execution_observability_event", **event_payload)

        return event_payload

    def emit_failure(
        self,
        *,
        event_type: str,
        component: str,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.emit_event(
            event_type=event_type,
            component=component,
            outcome="failure",
            payload=payload,
        )
