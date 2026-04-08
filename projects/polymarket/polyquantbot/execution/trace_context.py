"""execution.trace_context — Async-safe trace context for trade lifecycle observability."""
from __future__ import annotations

from contextvars import ContextVar
import uuid

_TRACE_ID_CTX: ContextVar[str] = ContextVar("trade_trace_id", default="")


def create_trace_id() -> str:
    """Create a new globally unique trace identifier."""
    return f"trace-{uuid.uuid4().hex}"


def set_trace_id(trace_id: str) -> str:
    """Bind a trace identifier to the current async context."""
    _TRACE_ID_CTX.set(trace_id)
    return trace_id


def get_trace_id() -> str:
    """Return current trace id bound to context, if any."""
    return _TRACE_ID_CTX.get()


def ensure_trace_id(trace_id: str | None = None) -> str:
    """Return a valid trace id, generating and binding one when absent."""
    active = trace_id or get_trace_id()
    if active:
        set_trace_id(active)
        return active
    created = create_trace_id()
    set_trace_id(created)
    return created
