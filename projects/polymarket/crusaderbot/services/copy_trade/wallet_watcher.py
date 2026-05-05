"""Polymarket leader-wallet trade poller for the copy-trade strategy.

Two public coroutines:

    fetch_recent_wallet_trades(wallet, limit)
        → list[dict] of recent trades for the wallet, freshest first.
        Bounded by a 5 s per-call timeout and a process-wide 1 req/s rate
        limit shared across every concurrent watcher. Failures are swallowed
        — the function returns `[]` rather than propagating, so a single
        flaky leader cannot crash the per-user scan loop.

    fetch_leader_open_condition_ids(wallet)
        → set[str] of condition_ids the leader currently holds an open
        position in. Used by `CopyTradeStrategy.evaluate_exit` to detect
        a leader exit (mirror_condition_id ∉ leader_open_set ⇒ leader_exit).

Foundation contract: this module is pure I/O. It never places orders, never
writes to the execution path, never bypasses risk gates.

Rate-limit design: a single asyncio.Lock + monotonic timestamp gates every
outbound call. The lock is module-global so independent CopyTradeStrategy
instances (one per worker, one per scan loop) never collectively exceed
1 req/s against the Data API.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ...integrations import polymarket as pm

logger = logging.getLogger(__name__)

POLYMARKET_FETCH_TIMEOUT_SEC: float = 5.0
GLOBAL_RATE_LIMIT_INTERVAL_SEC: float = 1.0

_rate_lock = asyncio.Lock()
_last_request_at: float = 0.0


async def _await_rate_limit_slot() -> None:
    """Hold the module-global slot until the 1 req/s budget allows the call.

    `time.monotonic()` is used rather than `loop.time()` so the limiter
    behaves consistently when the event loop is restarted between tests.
    """
    global _last_request_at
    async with _rate_lock:
        now = time.monotonic()
        elapsed = now - _last_request_at
        wait = GLOBAL_RATE_LIMIT_INTERVAL_SEC - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


async def fetch_recent_wallet_trades(
    wallet_address: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` recent trades for the leader wallet.

    Returns:
        A list of trade dicts (Polymarket Data API shape). Empty list on:
            * blank wallet address
            * 5 s timeout
            * any HTTP / parse error
            * Data API responds with anything other than a list
    """
    if not wallet_address:
        return []
    await _await_rate_limit_slot()
    try:
        trades = await asyncio.wait_for(
            pm.get_user_activity(wallet_address, limit=limit),
            timeout=POLYMARKET_FETCH_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "wallet_watcher fetch timed out wallet=%s timeout=%ss",
            wallet_address, POLYMARKET_FETCH_TIMEOUT_SEC,
        )
        return []
    except Exception as exc:
        logger.warning(
            "wallet_watcher fetch failed wallet=%s err=%s",
            wallet_address, exc,
        )
        return []
    if not isinstance(trades, list):
        return []
    return trades


async def fetch_leader_open_condition_ids(wallet_address: str) -> set[str]:
    """Return the set of condition_ids the leader currently holds.

    Implementation detail: the Polymarket Data API exposes positions on the
    same `/activity` endpoint as a derivative — for now we approximate "still
    open" by treating the most recent BUY without a matching SELL as held.
    A full positions endpoint integration is deferred to P3d when the exit
    watcher consumes this. Until then, the conservative behaviour is to
    report the leader as STILL holding any condition_id where their last
    trade was a BUY — that prevents premature leader_exit fires.
    """
    if not wallet_address:
        return set()
    trades = await fetch_recent_wallet_trades(wallet_address, limit=50)
    if not trades:
        return set()

    # Walk newest -> oldest. First action seen per condition_id wins:
    #   first action is BUY  -> leader is currently long that condition
    #   first action is SELL -> leader has exited (do not include)
    seen: dict[str, str] = {}
    for trade in trades:
        cond = trade.get("conditionId") or trade.get("condition_id")
        side = (trade.get("side") or "").upper()
        if not cond or side not in ("BUY", "SELL"):
            continue
        cond_str = str(cond)
        if cond_str in seen:
            continue
        seen[cond_str] = side
    return {cond for cond, side in seen.items() if side == "BUY"}


__all__ = [
    "fetch_recent_wallet_trades",
    "fetch_leader_open_condition_ids",
    "POLYMARKET_FETCH_TIMEOUT_SEC",
    "GLOBAL_RATE_LIMIT_INTERVAL_SEC",
]
