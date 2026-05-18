"""Async in-process event bus for CrusaderBot.

Usage:
    subscribe("position.opened", handler)
    await emit("position.opened", telegram_user_id=..., market_id=..., ...)

Failure contract:
    Each handler runs as a fire-and-forget asyncio task.
    Exceptions in any handler are caught and logged — one failing handler
    never blocks the caller or other handlers.
"""
from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from typing import Any, Callable, Coroutine

logger = logging.getLogger(__name__)

_EventHandler = Callable[..., Coroutine[Any, Any, None]]

_subscribers: dict[str, list[_EventHandler]] = defaultdict(list)
_background_tasks: set[asyncio.Task[Any]] = set()


def subscribe(event: str, handler: _EventHandler) -> None:
    """Register an async handler for the given event name."""
    _subscribers[event].append(handler)


async def emit(event: str, **payload: Any) -> None:
    """Dispatch event to all registered handlers as fire-and-forget tasks.

    Returns immediately after scheduling; handlers execute concurrently.
    """
    for handler in list(_subscribers.get(event, [])):
        task = asyncio.create_task(_safe_call(handler, event, payload))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)


async def _safe_call(
    handler: _EventHandler,
    event: str,
    payload: dict[str, Any],
) -> None:
    try:
        await handler(**payload)
    except Exception as exc:
        logger.error(
            "event_bus: handler_error event=%s handler=%s error=%s",
            event,
            getattr(handler, "__name__", str(handler)),
            exc,
        )
