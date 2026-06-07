"""Heisenberg agent 556 sync job — feeds the in-memory real-time trade buffer.

Every HEISENBERG_REALTIME_TRADES_INTERVAL_SEC (default 60s) when the feature
flag is on:

  1. Fetch trades from the last HEISENBERG_REALTIME_TRADES_WINDOW_SEC
     (default 300s = 5 min — wider than the poll cycle so we don't drop
     trades on a slow tick).
  2. Record each trade into the in-memory buffer (services.heisenberg_buffer),
     which dedups by (wallet, condition_id, trade_time, side) and prunes
     entries older than HEISENBERG_REALTIME_TRADES_RETENTION_HOURS (default 24h).

No durable storage — per the operator ruling "real-time signals do not need
durable storage", the buffer lives in process memory (the
``heisenberg_realtime_trades`` table was the top disk hog, dropped in migration
087). Consumers: the Playbook Sharp Money module (domain/playbook/sharp_flow.py)
and the copy-trade fast-track (services/copy_trade/realtime_fast_track.py) read
the same buffer.

Triple-gated:
  - HEISENBERG_API_TOKEN env var set (client returns [] otherwise — no-op)
  - HEISENBERG_REALTIME_TRADES_ENABLED config flag (scheduler registers only
    when on — see scheduler.py)
  - asyncio coalesce + max_instances=1 (scheduler-side concurrency cap)
"""
from __future__ import annotations

import logging
import os
import time

from ..config import get_settings
from ..services import heisenberg_buffer, heisenberg_trades

log = logging.getLogger(__name__)

JOB_ID = "heisenberg_realtime_trades_sync"


async def run_job() -> tuple[int, int]:
    """Fetch + record one tick into the in-memory buffer. Returns (recorded, 0).

    Never raises. Token-unset / upstream error returns (0, 0) and logs. The
    second tuple element is retained as 0 for the scheduler-listener metadata
    shape (the former durable-prune count; pruning is now in-buffer).
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

    recorded = heisenberg_buffer.record_trades(trades, retention_hours=retention_hours)
    log.info(
        "heisenberg_realtime_sync: fetched=%d recorded=%d buffer_size=%d window=%ds elapsed=%.2fs",
        len(trades), recorded, heisenberg_buffer.size(), window, time.monotonic() - t0,
    )
    return recorded, 0


__all__ = ["run_job", "JOB_ID"]
