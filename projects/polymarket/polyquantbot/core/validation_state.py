"""Phase 24 — ValidationStateStore: Shared validation-state registry.

A lightweight, asyncio-safe in-memory store that holds the current system
health state and the metrics that produced it.  Intended to be instantiated
once (singleton) and shared across the monitoring pipeline.

Design:
    - All mutations happen in a single asyncio event loop — no Lock needed.
    - ``update()`` is synchronous and O(1).
    - ``get_state()`` returns a shallow copy so callers cannot mutate internals.
"""
from __future__ import annotations

import time
from typing import Any

import structlog

from ..monitoring.validation_engine import ValidationState

log = structlog.get_logger()


class ValidationStateStore:
    """In-memory registry for the current validation state.

    Attributes:
        current_state:    Most recent :class:`ValidationState`.
        last_metrics:     The metric dict that produced the current state.
        last_update_time: Unix timestamp of the most recent ``update()`` call.
    """

    def __init__(self) -> None:
        self.current_state: ValidationState = ValidationState.HEALTHY
        self.last_metrics: dict[str, Any] = {}
        self.last_update_time: float = time.time()

    # ── Mutation ──────────────────────────────────────────────────────────────

    def update(self, state: ValidationState, metrics: dict[str, Any]) -> None:
        """Persist the latest validation state and metrics snapshot.

        Args:
            state:   The :class:`ValidationState` returned by
                     :class:`ValidationEngine`.
            metrics: The metrics dict that produced ``state``.
        """
        self.current_state = state
        self.last_metrics = dict(metrics)
        self.last_update_time = time.time()

        log.info(
            "validation_state_updated",
            state=state.value,
            update_time=round(self.last_update_time, 3),
        )

    # ── Query ─────────────────────────────────────────────────────────────────

    def get_state(self) -> dict[str, Any]:
        """Return a snapshot of the current state as a plain dict.

        Returns:
            Dict with keys:
                ``state``            — current :class:`ValidationState` value string.
                ``last_metrics``     — copy of the last metrics dict.
                ``last_update_time`` — Unix timestamp of last update.
        """
        return {
            "state": self.current_state.value,
            "last_metrics": dict(self.last_metrics),
            "last_update_time": self.last_update_time,
        }
