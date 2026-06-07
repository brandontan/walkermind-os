"""Heisenberg agent 556 sync job — populates heisenberg_realtime_trades buffer.

Every HEISENBERG_REALTIME_TRADES_INTERVAL_SEC (default 60s) when the feature
flag is on:

  1. Fetch trades from the last HEISENBERG_REALTIME_TRADES_WINDOW_SEC
     (default 300s = 5 min — wider than the poll cycle so we don't drop
     trades on a slow tick).
  2. UPSERT each trade by (wallet, condition_id, trade_time, side).
  3. DELETE rows older than HEISENBERG_REALTIME_TRADES_RETENTION_HOURS
     (default 24h).

Triple-gated:
  - HEISENBERG_API_TOKEN env var set (client returns [] otherwise — no-op)
  - HEISENBERG_REALTIME_TRADES_ENABLED config flag (scheduler registers only
    when on — see scheduler.py)
  - asyncio coalesce + max_instances=1 (scheduler-side concurrency cap)

The buffer is dormant — no downstream consumer reads it yet. A future
copy-trade fast-track lane will tap it.
"""
from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone

from ..config import get_settings
from ..database import get_pool
from ..services import heisenberg_trades

log = logging.getLogger(__name__)

JOB_ID = "heisenberg_realtime_trades_sync"


async def run_job() -> tuple[int, int]:
    """Fetch + upsert + prune one tick. Returns (upserted, pruned).

    Never raises. Token-unset / DB error / upstream error all return (0, 0)
    and log a warning.
    """
    if not os.getenv("HEISENBERG_API_TOKEN", ""):
        log.warning("heisenberg_realtime_sync: HEISENBERG_API_TOKEN unset — skipping")
        return 0, 0

    cfg = get_settings()
    window = int(getattr(cfg, "HEISENBERG_REALTIME_TRADES_WINDOW_SEC", 300))
    retention_hours = int(getattr(cfg, "HEISENBERG_REALTIME_TRADES_RETENTION_HOURS", 24))

    t0 = time.monotonic()
    try:
        trades = await heisenberg_trades.fetch_recent(window_seconds=window, limit=200)
    except Exception as exc:
        log.exception("heisenberg_realtime_sync: fetch failed: %s", exc)
        return 0, 0

    # WARP-82: NO durable persistence. Per the operator ruling ("real-time
    # signals do not need durable storage"), the former UPSERT into
    # heisenberg_realtime_trades + retention prune are removed; trades are
    # debug-logged only. The table is dropped in migration 087.
    #
    # CONSEQUENCE (intentional, flagged): the durable buffer was the data source
    # for the Playbook Sharp Money module (domain/playbook/sharp_flow.py) and the
    # copy-trade fast-track. With no buffer, sharp_flow returns no flow (fail-soft)
    # → Sharp Money abstains, and the fast-track has nothing to mirror. This is the
    # accepted trade-off of killing real-time persistence.
    for tr in trades:
        log.debug(
            "heisenberg_trade wallet=%s cid=%s side=%s size=%s ts=%s",
            tr.wallet, tr.condition_id, tr.side, tr.size_usdc, tr.trade_time,
        )
    log.info(
        "heisenberg_realtime_sync: fetched=%d (not persisted, WARP-82) window=%ds elapsed=%.2fs",
        len(trades), window, time.monotonic() - t0,
    )
    return len(trades), 0


async def _prune(retention_hours: int) -> int:
    """Delete buffer rows older than `retention_hours`. Returns deleted count."""
    if retention_hours <= 0:
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(hours=retention_hours)
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM heisenberg_realtime_trades WHERE fetched_at < $1",
                cutoff,
            )
        # asyncpg `execute()` returns 'DELETE N' on success.
        try:
            return int(str(result).split()[-1])
        except (ValueError, IndexError) as exc:
            log.warning(
                "heisenberg_realtime_sync: prune result parse failed result=%r err=%s",
                result, exc,
            )
            return 0
    except Exception as exc:
        log.warning("heisenberg_realtime_sync: prune failed: %s", exc)
        return 0


__all__ = ["run_job", "JOB_ID"]
