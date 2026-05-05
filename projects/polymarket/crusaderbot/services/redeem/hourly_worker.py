"""R12e hourly batch redeem worker.

Runs on the redeem-interval cron (``Settings.REDEEM_INTERVAL``, default
60 minutes). Drains every pending row in ``redeem_queue`` sequentially:

  * Pending rows from users on hourly mode (the primary path)
  * Gas-deferred rows the instant worker released back to pending
  * Failure-deferred rows from the instant worker's retry-once path

Per R12e spec the worker submits ONE redeem per position (CTF contract
constraint — no batched calls). On per-row failure the worker increments
``failure_count`` and pages the operator at >= 2 consecutive failures.
The operator alert path (``monitoring.alerts._dispatch``) carries its
own per-key cooldown so a stuck position does not page on every tick.
"""
from __future__ import annotations

import logging

from ...config import get_settings
from ...database import get_pool
from ...monitoring import alerts
from . import redeem_router

logger = logging.getLogger(__name__)

OPERATOR_ALERT_THRESHOLD: int = 2


async def run_once() -> None:
    """Drain all pending redeem_queue rows. Sequential, never raises.

    Begins by reaping any rows stuck in ``processing`` past the
    stale-after threshold — these are presumed orphaned by a crashed
    instant worker or a process restart. The reaper runs ahead of the
    drain SELECT so reaped rows are picked up in the same tick instead
    of waiting another 60 minutes.
    """
    s = get_settings()
    if not s.AUTO_REDEEM_ENABLED:
        logger.info("auto-redeem disabled, skipping hourly worker")
        return

    try:
        reaped = await redeem_router.reap_stale_processing()
        if reaped:
            logger.warning(
                "hourly redeem reaper: released %d stale processing "
                "row(s) back to pending", reaped,
            )
    except Exception as exc:
        logger.error("hourly redeem reaper failed: %s — continuing drain",
                     exc)

    pool = get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT id FROM redeem_queue WHERE status='pending' "
            "ORDER BY queued_at ASC",
        )
    if not rows:
        return

    logger.info("hourly redeem worker: %d pending row(s)", len(rows))
    for r in rows:
        try:
            await _process(r["id"])
        except Exception as exc:
            # _process owns its own error-routing; this catch is the
            # last line of defence against a queue drain being killed
            # by one buggy row.
            logger.error("hourly worker row %s leaked: %s", r["id"], exc)


async def _process(queue_id) -> None:
    claimed = await redeem_router.claim_queue_row(queue_id)
    if claimed is None:
        return

    try:
        await redeem_router.settle_winning_position(claimed)
        await redeem_router.mark_done(queue_id)
        return
    except Exception as exc:
        new_count = await redeem_router.release_back_to_pending(
            queue_id, increment_failure=True, error=str(exc),
        )
        logger.error(
            "hourly redeem failed queue=%s position=%s failure_count=%d: %s",
            queue_id, claimed.get("id"), new_count, exc,
        )
        if new_count >= OPERATOR_ALERT_THRESHOLD:
            await _page_operator(claimed, new_count, str(exc))


async def _page_operator(claimed: dict, failure_count: int, last_error: str) -> None:
    """Page the operator about a persistently failing redeem.

    Uses ``monitoring.alerts._dispatch`` so the per-key cooldown matches
    the rest of the operator-alert surface — repeat failures on the same
    queue row do not flood Telegram.
    """
    body = (
        "[CrusaderBot] persistent redeem failure\n"
        f"queue: {claimed.get('queue_id')}\n"
        f"position: {claimed.get('id')}\n"
        f"user: {claimed.get('user_id')}\n"
        f"market: {claimed.get('market_id')}\n"
        f"side: {claimed.get('side')}\n"
        f"mode: {claimed.get('mode')}\n"
        f"failures: {failure_count}\n"
        f"last_error: {last_error[:300]}"
    )
    try:
        await alerts._dispatch(
            "redeem_failed_persistent", str(claimed.get("queue_id")), body,
        )
    except Exception as exc:
        logger.error("operator alert dispatch failed for queue=%s: %s",
                     claimed.get("queue_id"), exc)
