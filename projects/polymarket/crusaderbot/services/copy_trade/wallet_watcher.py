"""Polymarket leader-wallet trade poller for the copy-trade strategy.

Two public coroutines + one custom exception:

    fetch_recent_wallet_trades(wallet, limit)
        → list[dict] of recent trades for the wallet, freshest first.
        Bounded by a 5 s per-call timeout and a process-wide 1 req/s rate
        limit shared across every concurrent watcher. Failures are swallowed
        — the function returns `[]` rather than propagating, so a single
        flaky leader cannot crash the per-user scan loop. Empty list and
        API failure are intentionally indistinguishable on the scan path:
        either way "emit no signals" is correct.

    fetch_leader_open_condition_ids(wallet)
        → set[str] of condition_ids the leader currently holds an open
        position in. Used by `CopyTradeStrategy.evaluate_exit` to detect
        a leader exit. Raises `WalletWatcherUnavailable` on API failure
        rather than returning an empty set, because on the exit path
        "API down" must NOT be conflated with "leader closed everything"
        — the strategy would otherwise force-close mirrored positions
        during a Polymarket Data API outage.

    WalletWatcherUnavailable
        Raised by `fetch_leader_open_condition_ids` when the underlying
        Data API call times out, fails, or returns a malformed payload.

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


class WalletWatcherUnavailable(Exception):
    """Raised when the Polymarket Data API cannot answer a wallet query.

    Distinct from "wallet has nothing to report" — the scan path tolerates
    both as `[]`, but the exit path MUST treat unavailability as `hold`
    rather than as an explicit leader-exit signal.
    """


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


async def _fetch_activity_strict(
    wallet_address: str,
    limit: int,
) -> list[dict[str, Any]]:
    """Internal: rate-limited, timeout-bounded fetch that propagates failures.

    Empty wallet address is NOT a failure — it is "nothing to fetch", and
    we return an empty list. Every other error path raises
    `WalletWatcherUnavailable` so the caller can tell apart "wallet has
    no recent activity" from "the data source is unreachable".
    """
    if not wallet_address:
        return []
    await _await_rate_limit_slot()
    try:
        trades = await asyncio.wait_for(
            pm.get_user_activity(wallet_address, limit=limit),
            timeout=POLYMARKET_FETCH_TIMEOUT_SEC,
        )
    except asyncio.TimeoutError as exc:
        raise WalletWatcherUnavailable(
            f"polymarket data api timeout for wallet={wallet_address}"
            f" after {POLYMARKET_FETCH_TIMEOUT_SEC}s"
        ) from exc
    except Exception as exc:
        raise WalletWatcherUnavailable(
            f"polymarket data api error for wallet={wallet_address}: {exc}"
        ) from exc
    if not isinstance(trades, list):
        raise WalletWatcherUnavailable(
            f"polymarket data api returned non-list payload for "
            f"wallet={wallet_address}"
        )
    return trades


async def fetch_recent_wallet_trades(
    wallet_address: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Fetch up to ``limit`` recent trades for the leader wallet.

    Tolerant by design: returns ``[]`` for blank input, timeout, HTTP error,
    or malformed payload. The scan path uses this — emitting no signals on
    a flaky leader is the correct behaviour.

    Callers that need to distinguish "no activity" from "API failure" must
    use ``_fetch_activity_strict`` (or call ``fetch_leader_open_condition_ids``
    which already does so).
    """
    try:
        return await _fetch_activity_strict(wallet_address, limit)
    except WalletWatcherUnavailable as exc:
        logger.warning("wallet_watcher fetch failed (swallowed): %s", exc)
        return []


async def fetch_leader_open_condition_ids(wallet_address: str) -> set[str]:
    """Return the set of condition_ids the leader currently holds.

    Implementation detail: the Polymarket Data API exposes positions on the
    same `/activity` endpoint as a derivative — for now we approximate "still
    open" by treating the most recent BUY without a matching SELL as held.
    A full positions endpoint integration is deferred to P3d when the exit
    watcher consumes this. Until then, the conservative behaviour is to
    report the leader as STILL holding any condition_id where their last
    trade was a BUY — that prevents premature leader_exit fires.

    Raises:
        WalletWatcherUnavailable: the Polymarket Data API timed out, errored,
            or returned a malformed payload. The caller MUST treat this as
            "do not exit" — conflating it with "no open positions" would
            force-close every mirrored position during a Polymarket outage.
    """
    if not wallet_address:
        return set()
    trades = await _fetch_activity_strict(wallet_address, limit=50)
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
    "WalletWatcherUnavailable",
    "POLYMARKET_FETCH_TIMEOUT_SEC",
    "GLOBAL_RATE_LIMIT_INTERVAL_SEC",
]
