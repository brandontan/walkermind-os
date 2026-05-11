"""Market signal scanner — edge-finder publication writer.

Polls Polymarket API, applies edge_finder strategy logic, and writes entry
signals into signal_publications for the signal_following pipeline to consume.

Pipeline role:
    market_signal_scanner (this job, 60s) → signal_publications
    signal_following_scan (existing, 3min) → signal_publications → execution

Edge-finder logic:
    YES price < EDGE_PRICE_THRESHOLD → publish YES entry signal
    NO  price < EDGE_PRICE_THRESHOLD → publish NO  entry signal

Deduplication: a (feed_id, market_id, side) triple is not re-published within
DEDUP_WINDOW_HOURS so a market stuck at the threshold edge doesn't flood the
table on every tick.

All signals carry is_demo=TRUE and expire after SIGNAL_EXPIRY_HOURS.
Only markets above MIN_LIQUIDITY are considered.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import UUID

from ..database import get_pool
from ..integrations import polymarket

logger = logging.getLogger(__name__)

# Fixed demo feed UUID — must match migration 024_signal_scan_engine_seed.sql
DEMO_FEED_ID: UUID = UUID("00000000-0000-0000-0001-000000000001")

EDGE_PRICE_THRESHOLD: float = 0.15
MIN_LIQUIDITY: float = 1_000.0
DEDUP_WINDOW_HOURS: int = 2
SIGNAL_EXPIRY_HOURS: int = 4
DEFAULT_SIGNAL_SIZE_USDC: float = 10.0
DEFAULT_CONFIDENCE: float = 0.65

JOB_ID = "market_signal_scanner"


async def _feed_is_active() -> bool:
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT 1 FROM signal_feeds WHERE id=$1 AND status='active'",
            DEMO_FEED_ID,
        )
    return row is not None


async def _already_published(market_id: str, side: str) -> bool:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=DEDUP_WINDOW_HOURS)
    pool = get_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(
            """
            SELECT 1 FROM signal_publications
             WHERE feed_id = $1
               AND market_id = $2
               AND side = $3
               AND exit_signal = FALSE
               AND exit_published_at IS NULL
               AND published_at > $4
            """,
            DEMO_FEED_ID, market_id, side, cutoff,
        )
    return row is not None


async def _publish_signal(
    market_id: str,
    side: str,
    target_price: float,
    payload: dict,
) -> None:
    expires_at = datetime.now(timezone.utc) + timedelta(hours=SIGNAL_EXPIRY_HOURS)
    pool = get_pool()
    async with pool.acquire() as conn:
        await conn.execute(
            """
            INSERT INTO signal_publications
                (feed_id, market_id, side, target_price, signal_type,
                 payload, exit_signal, published_at, expires_at, is_demo)
            VALUES ($1, $2, $3, $4, 'edge_finder',
                    $5::jsonb, FALSE, NOW(), $6, TRUE)
            """,
            DEMO_FEED_ID, market_id, side, target_price,
            json.dumps(payload), expires_at,
        )


async def run_job() -> tuple[int, int]:
    """Run one scan tick. Returns (markets_scanned, signals_published).

    Errors during individual market processing are contained so one bad
    market row cannot crash the whole scan tick.
    """
    if not await _feed_is_active():
        logger.warning(
            "market_signal_scanner: demo feed not active — "
            "run migration 024_signal_scan_engine_seed.sql",
        )
        return 0, 0

    try:
        markets = await polymarket.get_markets(limit=200)
    except Exception as exc:
        logger.warning("market_signal_scanner: polymarket fetch failed: %s", exc)
        return 0, 0

    if not markets:
        return 0, 0

    scanned = 0
    published = 0

    for m in markets:
        try:
            if m.get("closed") or m.get("resolved"):
                continue
            mid = str(m.get("id") or m.get("conditionId") or "")
            if not mid:
                continue
            liq = float(m.get("liquidity") or 0)
            if liq < MIN_LIQUIDITY:
                continue

            outcomes = m.get("outcomePrices") or [None, None]
            yes_p: float | None = (
                float(outcomes[0]) if outcomes and outcomes[0] is not None else None
            )
            no_p: float | None = (
                float(outcomes[1])
                if len(outcomes) > 1 and outcomes[1] is not None
                else None
            )
            scanned += 1

            base: dict = {
                "strategy": "edge_finder",
                "liquidity": liq,
                "question": str(m.get("question") or "")[:200],
                "confidence": DEFAULT_CONFIDENCE,
                "size_usdc": DEFAULT_SIGNAL_SIZE_USDC,
            }

            if yes_p is not None and yes_p < EDGE_PRICE_THRESHOLD:
                if not await _already_published(mid, "YES"):
                    await _publish_signal(
                        mid, "YES", yes_p,
                        {**base, "yes_price": yes_p, "signal_reason": "yes_edge"},
                    )
                    published += 1
                    logger.info(
                        "market_signal_scanner: YES edge published "
                        "market=%s yes_price=%.3f", mid, yes_p,
                    )

            if no_p is not None and no_p < EDGE_PRICE_THRESHOLD:
                if not await _already_published(mid, "NO"):
                    await _publish_signal(
                        mid, "NO", no_p,
                        {**base, "no_price": no_p, "signal_reason": "no_edge"},
                    )
                    published += 1
                    logger.info(
                        "market_signal_scanner: NO edge published "
                        "market=%s no_price=%.3f", mid, no_p,
                    )

        except Exception as exc:
            logger.warning(
                "market_signal_scanner: market processing failed mid=%s: %s",
                m.get("id"), exc,
            )

    logger.info(
        "market_signal_scanner: tick done scanned=%d published=%d",
        scanned, published,
    )
    return scanned, published


__all__ = ["run_job", "JOB_ID", "DEMO_FEED_ID"]
