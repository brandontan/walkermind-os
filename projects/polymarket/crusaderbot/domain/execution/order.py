"""Close-order helper — submits a position close with a single bounded retry.

Capital-safety contract (paper vs live):
  * **paper** mode: errors out of ``router.close`` are DB-only (asyncpg
    transient, ledger row contention) and are safe to retry — the close
    transaction rolls back atomically on failure. We retry once after
    ``CLOSE_RETRY_DELAY_SECONDS``.
  * **live** mode: an exception out of ``router.close`` cannot be safely
    classified as pre-submit. ``live.close_position`` calls
    ``polymarket.submit_live_order`` directly and re-raises whatever the
    submit raises. A network timeout or HTTP 5xx after the broker has
    actually queued the SELL is *post-submit ambiguous* — retrying would
    risk a duplicate SELL and an over-close (closing what is already
    closed, or going effectively short on the CTF token). For live mode
    we therefore make a single attempt only; failure feeds the operator
    reconciliation path via ``alert_operator_close_failed_persistent``.
    A later lane that splits ``live.close_position`` into prepare/submit
    (mirroring the entry path) can re-enable retry on a typed
    ``LivePreSubmitError``.

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
PAPER_CLOSE_MAX_ATTEMPTS: int = 2  # initial + one retry
LIVE_CLOSE_MAX_ATTEMPTS: int = 1   # single attempt — see module docstring
# Backwards-compat alias for tests / external callers that imported the
# original constant. Maps to the paper-side budget (the original behaviour).
CLOSE_MAX_ATTEMPTS: int = PAPER_CLOSE_MAX_ATTEMPTS


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


def _max_attempts_for(position: dict[str, Any]) -> int:
    """Pick the retry budget for a position based on its mode.

    Live mode is single-attempt: a submit error cannot be safely classified
    as pre-submit today (live.close_position re-raises whatever
    submit_live_order raises), so retrying risks a duplicate on-chain SELL.
    Paper mode tolerates a single retry — its errors are DB-only and roll
    back atomically.
    """
    if position.get("mode") == "live":
        return LIVE_CLOSE_MAX_ATTEMPTS
    return PAPER_CLOSE_MAX_ATTEMPTS


async def submit_close_with_retry(
    *,
    position: dict[str, Any],
    exit_price: float,
    exit_reason: str,
    submitter: CloseSubmitter | None = None,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
) -> CloseResult:
    """Submit a close order, retrying once on failure (paper only).

    ``submitter`` defaults to ``router.close`` so production code calls the
    real engine. Tests inject a stub to exercise success / first-fail-then-ok
    / always-fail / live-no-retry branches without touching network or DB.

    Retry budget:
      * paper -> 2 attempts (initial + one retry after 5 s).
      * live  -> 1 attempt. A submit-time exception is post-submit ambiguous
        and cannot be retried without risking a duplicate SELL — failure
        flows to the operator-reconciliation path instead.
    """
    submit = submitter or router.close
    max_attempts = _max_attempts_for(position)
    last_error: str | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            payload = await submit(
                position=position,
                exit_price=exit_price,
                exit_reason=exit_reason,
            )
            return CloseResult(ok=True, payload=payload, error=None)
        except Exception as exc:  # broker errors are typed in live.py; we
            #                     catch broadly here so paper-side asyncpg
            #                     errors and live-side post-submit-ambiguous
            #                     errors are both surfaced rather than
            #                     swallowed. Note: live mode never retries
            #                     past the first attempt — see module docstring.
            last_error = f"{type(exc).__name__}: {exc}"
            logger.warning(
                "close attempt %d/%d failed for position %s (mode=%s): %s",
                attempt, max_attempts, position.get("id"),
                position.get("mode"), last_error,
            )
            if attempt < max_attempts:
                await sleep(CLOSE_RETRY_DELAY_SECONDS)
    return CloseResult(ok=False, payload=None, error=last_error)
