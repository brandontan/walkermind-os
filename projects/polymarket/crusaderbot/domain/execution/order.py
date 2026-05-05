"""Close-order helper — submits a position close with a single bounded retry.

The exit watcher needs uniform retry semantics across paper and live engines:
on a CLOB error, wait ``CLOSE_RETRY_DELAY_SECONDS`` and try once more before
surfacing the failure to the watcher's failure-tracking path. Routing through
``router.close`` keeps this module agnostic to the underlying engine — paper,
live, or the mock CLOB used in tests all look identical from here.

This module never touches engine internals or the ``MockClobClient`` directly;
all engine-specific behaviour lives in ``paper.py`` / ``live.py``.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from . import router

logger = logging.getLogger(__name__)

CLOSE_RETRY_DELAY_SECONDS: float = 5.0
CLOSE_MAX_ATTEMPTS: int = 2  # initial + one retry


@dataclass(frozen=True)
class CloseResult:
    """Outcome of a single ``submit_close_with_retry`` call.

    ``ok`` reflects whether the close succeeded after the retry chain.
    ``error`` is populated only on permanent failure and never carries a
    silent ``None`` for a fail — surfaced explicitly so the watcher's
    consecutive-failure tracker can record it.
    """

    ok: bool
    payload: dict[str, Any] | None
    error: str | None


CloseSubmitter = Callable[..., Awaitable[dict[str, Any]]]


async def submit_close_with_retry(
    *,
    position: dict[str, Any],
    exit_price: float,
    exit_reason: str,
    submitter: CloseSubmitter | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CloseResult:
    """Submit a close order, retrying once on failure.

    ``submitter`` defaults to ``router.close`` so production code calls the
    real engine. Tests inject a stub to exercise success / first-fail-then-ok
    / always-fail branches without touching network or DB.

    The retry is intentionally narrow: ONE delayed retry, not an exponential
    chain. CLOB-side post-submit ambiguity is the live engine's problem
    (LivePostSubmitError surfaces to the watcher and is not retried — the
    watcher records the failure and lets the operator reconcile).
    """
    submit = submitter or router.close
    last_error: str | None = None
    for attempt in range(1, CLOSE_MAX_ATTEMPTS + 1):
        try:
            payload = await submit(
                position=position,
                exit_price=exit_price,
                exit_reason=exit_reason,
            )
            return CloseResult(ok=True, payload=payload, error=None)
        except Exception as exc:  # broker errors are typed in live.py; we
            #                     catch broadly here so paper-side asyncpg
            #                     errors and live-side LivePostSubmitError
            #                     are both surfaced rather than swallowed.
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "close attempt %d/%d failed for position %s: %s",
                attempt, CLOSE_MAX_ATTEMPTS, position.get("id"), last_error,
            )
            if attempt < CLOSE_MAX_ATTEMPTS:
                await sleep(CLOSE_RETRY_DELAY_SECONDS)
    return CloseResult(ok=False, payload=None, error=last_error)
