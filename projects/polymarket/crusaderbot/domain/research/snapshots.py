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
    """Persist a snapshot row per market for this scan tick. Returns rows written.

    Fail-soft: any error logs and returns 0 — the scan loop is never broken. The
    caller is responsible for the ``SCAN_SNAPSHOT_ENABLED`` gate.
    """
    if not markets:
        return 0
    rows = [r for r in (_extract(m) for m in markets if isinstance(m, dict)) if r]
    if not rows:
        return 0
    payload = [(scan_run_id, *r) for r in rows]
    try:
        pool = pool or get_pool()
        async with pool.acquire() as conn:  # type: ignore[attr-defined]
            await conn.executemany(
                """
                INSERT INTO market_snapshots
                    (scan_run_id, market_id, category, best_bid, best_ask,
                     mid_price, liquidity_usdc, raw, scanned_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, NOW())
                """,
                payload,
            )
    except Exception as exc:  # noqa: BLE001 — fail-soft, never break the scan loop
        logger.warning("market_snapshot_write_failed", error=str(exc))
        return 0
    return len(payload)


__all__ = ["record_market_snapshots"]
