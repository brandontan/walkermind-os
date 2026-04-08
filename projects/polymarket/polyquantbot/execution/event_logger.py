from datetime import datetime
from typing import Any


def emit_event(
    trace_id: str,
    event_type: str,
    component: str,
    outcome: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if trace_id is None or str(trace_id).strip() == "":
        raise ValueError("trace_id is required")
    if event_type is None or str(event_type).strip() == "":
        raise ValueError("event_type is required")
    if component is None or str(component).strip() == "":
        raise ValueError("component is required")
    if outcome is None or str(outcome).strip() == "":
        raise ValueError("outcome is required")

    return {
        "trace_id": trace_id,
        "event_type": event_type,
        "component": component,
        "outcome": outcome,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload or {},
    }
