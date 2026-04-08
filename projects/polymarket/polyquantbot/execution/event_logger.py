from __future__ import annotations

from datetime import datetime
from typing import Any


def _require_text(value: str | None, field_name: str) -> str:
    if value is None:
        raise ValueError(f"{field_name} must not be None")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _normalize_outcome(outcome: str | None) -> str:
    normalized = _require_text(outcome, "outcome")
    return normalized.lower().replace(" ", "_").replace("-", "_")


def emit_event(
    trace_id: str | None,
    event_type: str | None,
    component: str | None,
    outcome: str | None,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Emit a structured observability event with strict contract validation."""
    normalized_trace_id = _require_text(trace_id, "trace_id")
    normalized_event_type = _require_text(event_type, "event_type")
    normalized_component = _require_text(component, "component")
    normalized_outcome = _normalize_outcome(outcome)

    return {
        "trace_id": normalized_trace_id,
        "event_type": normalized_event_type,
        "component": normalized_component,
        "outcome": normalized_outcome,
        "timestamp": datetime.utcnow().isoformat(),
        "payload": payload or {},
    }
