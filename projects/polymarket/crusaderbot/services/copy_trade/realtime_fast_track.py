"""Copy-trade fast-track consumer — reads heisenberg_realtime_trades buffer.

Sub-minute mirror evaluation. The existing copy_trade.monitor.run_once() polls
the wallet-watcher (Polymarket Data API) every 30s. That path remains intact
as a fallback — this consumer rides on top of the Heisenberg agent 556
real-time buffer so a leader trade lands in our mirror queue within ~60s
of execution upstream (vs up to 5-10 min for the wallet-watcher path's
HTTP polling latency).

Pipeline:
  1. List active copy_trade_tasks (same source as monitor).
  2. Group by target wallet.
  3. For each wallet: SELECT FROM heisenberg_realtime_trades
       WHERE wallet = leader_wallet
         AND trade_time > task.last_realtime_seen_at (NULL -> NOW() - 5min).
  4. For each fresh trade, delegate to monitor._process_one(task, raw, wallet)
     — the SAME execution path the slow leader poller uses. Dedup is handled
     by copy_trade_idempotency (existing table), so a trade landing in both
     paths is processed exactly once.
  5. UPDATE task.last_realtime_seen_at = max(trade_time) per task.

Triple-gated:
  - HEISENBERG_API_TOKEN env set (otherwise buffer is empty anyway)
  - HEISENBERG_REALTIME_TRADES_ENABLED config flag (otherwise buffer stale)
  - HEISENBERG_FAST_TRACK_ENABLED config flag (scheduler registers job only
    when on — default OFF for first deploy)

Plus the four existing copy-trade safety gates apply unchanged:
  - kill_switch (existing in monitor._process_one path)
  - global copy_trade strategy on/off (existing _is_globally_disabled)
  - per-user copy_trade_task pause flag (existing repository filter)
  - 13-step risk gate (existing in TradeEngine pipeline)
"""
from __future__ import annotations

import structlog
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ...config import get_settings
from ...database import get_pool
from ...domain.copy_trade.models import CopyTradeTask
from ...domain.copy_trade.repository import list_active_tasks
from . import monitor as _monitor

log = structlog.get_logger(__name__)

JOB_ID = "copy_trade_realtime_fast_track"

# When a task has never run before (NULL watermark), look back this many
# seconds so we catch recently-buffered trades without scanning the full 24h.
_INITIAL_LOOKBACK_SEC = 300


async def run_once() -> tuple[int, int]:
    """Execute one fast-track tick. Returns (scanned, dispatched).

    Never raises — every error path returns (0, 0) and logs. APScheduler
    must never see an unhandled exception.
    """
    try:
        # Defence-in-depth: scheduler only registers this job when
        # HEISENBERG_FAST_TRACK_ENABLED is on, but if the operator flips
        # HEISENBERG_REALTIME_TRADES_ENABLED off without disabling the
        # fast-track, the buffer goes stale. Same for HEISENBERG_API_TOKEN —
        # without it the producer cannot insert fresh rows. Enforce both
        # explicitly so the consumer cannot operate on stale data.
        s = get_settings()
        if not getattr(s, "HEISENBERG_FAST_TRACK_ENABLED", False):
            return 0, 0
        if not getattr(s, "HEISENBERG_REALTIME_TRADES_ENABLED", False):
            log.info("copy_trade_fast_track: realtime producer disabled — skipping tick")
            return 0, 0
        if not (getattr(s, "HEISENBERG_API_TOKEN", "") or "").strip():
            log.info("copy_trade_fast_track: HEISENBERG_API_TOKEN unset — skipping tick")
            return 0, 0

        # Same gates as the existing monitor — reuse rather than duplicate.
        if await _monitor.kill_switch_is_active():
            log.warning("copy_trade_fast_track: kill switch active — skipping tick")
            return 0, 0
        if await _monitor._is_globally_disabled():
            log.info("copy_trade_fast_track: globally disabled by admin — skipping tick")
            return 0, 0

        tasks = await list_active_tasks()
        if not tasks:
            return 0, 0

        # Group by wallet so one buffer query per wallet covers all subscribers.
        wallet_to_tasks: dict[str, list[CopyTradeTask]] = {}
        for task in tasks:
            wallet_to_tasks.setdefault(task.wallet_address, []).append(task)

        total_scanned = 0
        total_dispatched = 0
        for wallet, wallet_tasks in wallet_to_tasks.items():
            scanned, dispatched = await _process_wallet(wallet, wallet_tasks)
            total_scanned += scanned
            total_dispatched += dispatched

        log.info(
            "copy_trade_fast_track tick done",
            tasks=len(tasks),
            wallets=len(wallet_to_tasks),
            scanned=total_scanned,
            dispatched=total_dispatched,
        )
        return total_scanned, total_dispatched

    except Exception as exc:
        log.exception("copy_trade_fast_track: unexpected error", error=str(exc))
        return 0, 0


async def _process_wallet(
    wallet: str,
    tasks: list[CopyTradeTask],
) -> tuple[int, int]:
    """Fetch fresh trades for one leader wallet across all subscriber tasks.

    Each task has its own watermark — a slower subscriber may need to catch
    up on trades a faster subscriber already processed. We fetch the
    SUPERSET of all task lookbacks (min of all watermarks) then per-task
    filter client-side so each task's watermark is honoured precisely.
    """
    # Earliest watermark across tasks = how far back we need to scan.
    now = datetime.now(timezone.utc)
    fallback = now - timedelta(seconds=_INITIAL_LOOKBACK_SEC)
    earliest = min(
        (t.last_realtime_seen_at or fallback) for t in tasks
    )

    # Agent 556 stores wallets as all-lowercase hex (verified on live buffer).
    # `task.wallet_address` may be checksummed (mixed case) depending on how
    # the user entered it. Lowercase the query arg so the index hit is preserved
    # without resorting to LOWER(wallet) which would defeat the wallet index.
    wallet_key = wallet.lower()
    pool = get_pool()
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT trade_time, raw
                  FROM heisenberg_realtime_trades
                 WHERE wallet = $1
                   AND trade_time > $2
                 ORDER BY trade_time ASC
                """,
                wallet_key, earliest,
            )
    except Exception as exc:
        log.warning(
            "copy_trade_fast_track: buffer fetch failed",
            wallet=wallet, error=str(exc),
        )
        return 0, 0

    if not rows:
        return 0, 0

    scanned = 0
    dispatched = 0
    # Per task, find the trades newer than its watermark and dispatch.
    # Watermark advances ONLY past successfully-processed trades — a failure
    # halts the loop so the failed trade (and any after it) get retried on the
    # next tick. copy_trade_idempotency dedupes the retry of already-processed
    # successes that fell before the failure.
    for task in tasks:
        task_cutoff = task.last_realtime_seen_at or fallback
        latest_seen = task_cutoff
        failed = False
        for row in rows:
            trade_time = row["trade_time"]
            if trade_time <= task_cutoff:
                continue
            scanned += 1
            raw = dict(row["raw"]) if row["raw"] else {}
            try:
                await _monitor._process_one(task, raw, wallet)
                dispatched += 1
                if trade_time > latest_seen:
                    latest_seen = trade_time
            except Exception as exc:
                log.warning(
                    "copy_trade_fast_track: _process_one failed — halting task",
                    task_id=str(task.id), wallet=wallet, error=str(exc),
                )
                failed = True
                break

        if latest_seen > task_cutoff:
            await _bump_watermark(task.id, latest_seen)

        if failed:
            log.info(
                "copy_trade_fast_track: task paused for retry on next tick",
                task_id=str(task.id), wallet=wallet,
            )

    return scanned, dispatched


async def _bump_watermark(task_id: UUID, ts: datetime) -> None:
    """UPDATE copy_trade_tasks.last_realtime_seen_at — best-effort."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE copy_trade_tasks
                   SET last_realtime_seen_at = GREATEST(
                       COALESCE(last_realtime_seen_at, $2), $2
                   )
                 WHERE id = $1
                """,
                task_id, ts,
            )
    except Exception as exc:
        log.warning(
            "copy_trade_fast_track: watermark bump failed",
            task_id=str(task_id), error=str(exc),
        )


__all__ = ["run_once", "JOB_ID"]
