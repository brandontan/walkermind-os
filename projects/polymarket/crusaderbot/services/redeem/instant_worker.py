"""R12e instant redeem worker.

Processes a single ``redeem_queue`` row immediately on resolution
detection. Triggered as an asyncio task from
``redeem_router._process_market_resolution`` when the position owner has
``auto_redeem_mode='instant'``.

Behaviour (per R12e spec):

  1. Activation guard — short-circuit to a log line when
     ``AUTO_REDEEM_ENABLED`` is false.
  2. Atomic claim — flip the queue row from pending → processing. If the
     claim does not land (already taken by the hourly worker or another
     instant task), exit silently.
  3. Gas guard — for live positions only, read the current Polygon gas
     price. If above ``INSTANT_REDEEM_GAS_GWEI_MAX`` or unreadable,
     release the row back to pending so the hourly worker drains it
     later. Paper positions skip gas entirely (no on-chain action).
  4. Settlement attempt — call
     ``redeem_router.settle_winning_position``.
  5. On failure — sleep 30s, retry once. If the retry also fails,
     release the row back to pending (failure_count incremented). The
     hourly worker will pick it up; persistent failures eventually page
     the operator from the hourly path so the alert dimension is unified.
"""
from __future__ import annotations

import asyncio
import logging
from uuid import UUID

from ...config import get_settings
from ...integrations import polygon
from . import redeem_router

logger = logging.getLogger(__name__)

INSTANT_RETRY_DELAY_SECONDS: float = 30.0


async def try_process(queue_id: UUID) -> None:
    """Process a single redeem_queue row on the instant fast-path.

    Never raises — every failure mode is logged and converted into a
    queue state transition so the hourly worker remains the single
    fallback channel.
    """
    s = get_settings()
    if not s.AUTO_REDEEM_ENABLED:
        logger.info("auto-redeem disabled, skipping instant worker queue=%s",
                    queue_id)
        return

    try:
        claimed = await redeem_router.claim_queue_row(queue_id)
    except Exception as exc:
        logger.error("instant claim failed queue=%s: %s", queue_id, exc)
        return

    if claimed is None:
        return  # already claimed by hourly worker — that path will settle it

    try:
        await _gas_guard_and_settle(claimed)
    except Exception as exc:
        # Defensive net — should not be reachable since
        # _gas_guard_and_settle catches and routes its own failures.
        logger.error("instant worker fell through to defensive net "
                     "queue=%s: %s", queue_id, exc)
        try:
            await redeem_router.release_back_to_pending(
                queue_id, increment_failure=True, error=str(exc),
            )
        except Exception as inner:
            logger.error("instant defensive release failed queue=%s: %s",
                         queue_id, inner)


async def _gas_guard_and_settle(claimed: dict) -> None:
    queue_id: UUID = claimed["queue_id"]
    s = get_settings()

    if claimed["mode"] == "live":
        gas_ok = await _gas_ok(s.INSTANT_REDEEM_GAS_GWEI_MAX)
        if not gas_ok:
            await redeem_router.release_back_to_pending(
                queue_id, increment_failure=False,
            )
            return

    try:
        await redeem_router.settle_winning_position(claimed)
        await redeem_router.mark_done(queue_id)
        return
    except Exception as exc:
        logger.warning("instant settle attempt 1 failed queue=%s: %s — "
                       "retrying in %.0fs", queue_id, exc,
                       INSTANT_RETRY_DELAY_SECONDS)

    await asyncio.sleep(INSTANT_RETRY_DELAY_SECONDS)

    try:
        await redeem_router.settle_winning_position(claimed)
        await redeem_router.mark_done(queue_id)
        return
    except Exception as exc:
        logger.error("instant settle attempt 2 failed queue=%s: %s — "
                     "deferring to hourly worker", queue_id, exc)
        try:
            await redeem_router.release_back_to_pending(
                queue_id, increment_failure=True, error=str(exc),
            )
        except Exception as inner:
            logger.error("instant release-after-retry failed queue=%s: %s",
                         queue_id, inner)


async def _gas_ok(threshold_gwei: float) -> bool:
    """Read Polygon gas price and compare to the configured threshold.

    On read failure, treat as a gas-spike (return False) so the live
    redeem is deferred to the hourly worker rather than submitted blind.
    """
    try:
        gwei = await polygon.gas_price_gwei()
    except Exception as exc:
        logger.error("instant redeem gas read failed: %s — deferring "
                     "to hourly worker", exc)
        return False
    if gwei > threshold_gwei:
        logger.warning(
            "instant redeem gas-spike defer: %.1f gwei > %.1f — "
            "hourly queue will retry", gwei, threshold_gwei,
        )
        return False
    return True
