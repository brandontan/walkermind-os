from __future__ import annotations

from contextvars import ContextVar
from typing import Optional
from uuid import uuid4

_TRACE_ID: ContextVar[Optional[str]] = ContextVar("trade_trace_id", default=None)


def generate_trace_id() -> str:
    """Generate a lightweight UUID4 trace identifier."""
    return uuid4().hex


def get_trace_id() -> str:
    """Return the current trace identifier, generating one when absent."""
    trace_id = _TRACE_ID.get()
    if trace_id:
        return trace_id
    new_trace_id = generate_trace_id()
    _TRACE_ID.set(new_trace_id)
    return new_trace_id


def set_trace_id(trace_id: str) -> None:
    """Set the current trace identifier for propagation across call chains."""
    _TRACE_ID.set(trace_id)


def clear_trace_id() -> None:
    """Clear the active trace identifier."""
    _TRACE_ID.set(None)
