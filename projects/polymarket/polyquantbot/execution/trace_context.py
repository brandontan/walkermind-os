"""execution.trace_context — trace identifier utilities for trade lifecycle observability."""
from __future__ import annotations

from dataclasses import dataclass
import uuid


@dataclass(frozen=True)
class TraceContext:
    """Immutable execution trace context bound to a trade intent."""

    trace_id: str



def create_trace_id() -> str:
    """Return a unique trace identifier for a single trade intent."""
    return f"trace-{uuid.uuid4().hex}"



def create_trace_context() -> TraceContext:
    """Create a new trace context for a trade intent."""
    return TraceContext(trace_id=create_trace_id())
