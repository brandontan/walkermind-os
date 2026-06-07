"""Per-scan market snapshot recorder (Phase-2c-2, blueprint §12.1).

Persists the raw Gamma market universe each scan tick prices — before any
strategy filtering — into ``market_snapshots`` so the future walk-forward replay
(Lane 2c-3) has a bias-free historical substrate to re-run the real signal →
router → gate path over. Append-only, fail-soft, and gated by
``SCAN_SNAPSHOT_ENABLED`` at the call site — a write error is swallowed and never
breaks the scan loop. The full upstream dict is stored in ``raw`` so the replay
is not limited to the extracted columns.
"""
from __future__ import annotations

import json
from typing import Any

import structlog

from ...database import get_pool

logger = structlog.get_logger(__name__)


def _f(value: Any) -> float | None:
    """Best-effort float; None on missing/blank/non-numeric."""
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _extract(market: dict) -> tuple | None:
    """Map one Gamma market dict to a snapshot row tuple, or None if unusable.

    Defensive about Gamma's shape: ``conditionId``/``id`` for the key, ``bestBid``/
    ``bestAsk`` for top-of-book, ``liquidity``/``liquidityNum`` for depth, and a
    mid from the bid/ask midpoint, falling back to ``lastTradePrice`` then the
    first of ``outcomePrices`` (which Gamma may send as a JSON-encoded string).
    """
    market_id = market.get("conditionId") or market.get("condition_id") or market.get("id")
    if not market_id:
        return None
    best_bid = _f(market.get("bestBid"))
    best_ask = _f(market.get("bestAsk"))
    if best_bid is not None and best_ask is not None:
        mid: float | None = (best_bid + best_ask) / 2.0
    else:
        mid = _f(market.get("lastTradePrice"))
        if mid is None:
            prices = market.get("outcomePrices")
            if isinstance(prices, str):
                try:
                    prices = json.loads(prices)
                except (ValueError, TypeError):
                    prices = None
            if isinstance(prices, list) and prices:
                mid = _f(prices[0])
    liquidity = _f(market.get("liquidity")) or _f(market.get("liquidityNum"))
    category = market.get("category")
    return (
        str(market_id)[:100],
        str(category)[:64] if category else None,
        best_bid, best_ask, mid, liquidity,
        json.dumps(market, default=str),
    )


async def record_market_snapshots(
    scan_run_id: str | None,
    markets: list[dict],
    *,
    pool: object | None = None,
) -> int:
    """WARP-82: NO durable persistence — market snapshots are real-time only.

    Per the operator architecture ruling ("real-time signals do not need durable
    storage"), the former market_snapshots write is removed; the raw
    universe stays in-memory inside the scanner cycle. Kept as a fail-soft no-op
    (returns 0) so the gated call site in ``signal_scan_job.run_once`` and any
    test harness keep working without a code change. The ``market_snapshots``
    table is dropped in migration 087.
    """
    if not markets:
        return 0
    # Debug-only visibility; never persisted.
    logger.debug("market_snapshots_skipped count=%d (durable persistence killed, WARP-82)", len(markets))
    return 0


__all__ = ["record_market_snapshots"]
