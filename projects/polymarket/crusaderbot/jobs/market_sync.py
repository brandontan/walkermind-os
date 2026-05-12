"""Heisenberg market sync — upserts real Polymarket markets via agent 574.

Runs every 30 minutes. Pulls active markets with min_volume >= 50k from the
Heisenberg parameterized-retrieval endpoint and upserts them into the markets
table using condition_id as the primary key.

Fails gracefully if HEISENBERG_API_TOKEN is unset.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from ..database import get_pool
from ..services.heisenberg import retrieve

logger = logging.getLogger(__name__)

JOB_ID = "heisenberg_market_sync"

_AGENT_ID = 574
_PARAMS: dict[str, str] = {"closed": "False", "min_volume": "50000"}
_LIMIT = 100


async def run_job() -> int:
    """Fetch markets from Heisenberg agent 574 and upsert into markets table.

    Returns number of markets upserted.
    """
    if not os.getenv("HEISENBERG_API_TOKEN", ""):
        logger.warning("market_sync: HEISENBERG_API_TOKEN not set — skipping cycle")
        return 0

    try:
        results = await retrieve(_AGENT_ID, _PARAMS, limit=_LIMIT)
    except Exception as exc:
        logger.warning("market_sync: heisenberg fetch failed: %s", exc)
        return 0

    if not results:
        logger.info("market_sync: no results from agent %d", _AGENT_ID)
        return 0

    pool = get_pool()
    upserts = 0
    async with pool.acquire() as conn:
        for m in results:
            try:
                condition_id = str(
                    m.get("condition_id") or m.get("conditionId") or ""
                )
                if not condition_id:
                    continue

                slug = str(m.get("slug") or m.get("market_slug") or "")[:80]
                question = str(m.get("question") or m.get("title") or "")[:500]
                category = str(
                    m.get("category")
                    or m.get("event_slug")
                    or m.get("groupItemTitle")
                    or ""
                )[:50]

                outcome_prices = m.get("outcomePrices") or []
                yes_price = _safe_float(
                    m.get("side_a_implied")
                    or m.get("yes_price")
                    or (outcome_prices[0] if outcome_prices else None),
                    default=0.50,
                )
                no_price = _safe_float(
                    m.get("side_b_implied")
                    or m.get("no_price")
                    or (outcome_prices[1] if len(outcome_prices) > 1 else None),
                    default=0.50,
                )
                yes_token_id = _str_or_none(
                    m.get("side_a_token_id") or m.get("yes_token_id"), maxlen=100
                )
                no_token_id = _str_or_none(
                    m.get("side_b_token_id") or m.get("no_token_id"), maxlen=100
                )
                resolution_at = _parse_dt(m.get("end_date") or m.get("endDate"))
                liquidity_usdc = _safe_float(
                    m.get("liquidity_usdc")
                    or m.get("liquidity")
                    or m.get("volume_num")
                    or m.get("volume"),
                    default=0.0,
                )

                await conn.execute(
                    """
                    INSERT INTO markets
                        (id, slug, question, category, status,
                         yes_price, no_price, yes_token_id, no_token_id,
                         liquidity_usdc, resolution_at, condition_id, is_demo, synced_at)
                    VALUES ($1,$2,$3,$4,'active',$5,$6,$7,$8,$9,$10,$11,FALSE,NOW())
                    ON CONFLICT (id) DO UPDATE SET
                        slug          = EXCLUDED.slug,
                        question      = EXCLUDED.question,
                        category      = EXCLUDED.category,
                        status        = 'active',
                        yes_price     = EXCLUDED.yes_price,
                        no_price      = EXCLUDED.no_price,
                        yes_token_id  = EXCLUDED.yes_token_id,
                        no_token_id   = EXCLUDED.no_token_id,
                        liquidity_usdc = EXCLUDED.liquidity_usdc,
                        resolution_at = EXCLUDED.resolution_at,
                        condition_id  = EXCLUDED.condition_id,
                        is_demo       = FALSE,
                        synced_at     = NOW()
                    """,
                    condition_id, slug, question, category,
                    yes_price, no_price, yes_token_id, no_token_id,
                    liquidity_usdc, resolution_at, condition_id,
                )
                upserts += 1
            except Exception as exc:
                logger.warning(
                    "market_sync: upsert failed condition_id=%s: %s",
                    m.get("condition_id"), exc,
                )

    logger.info("market_sync: upserted %d markets", upserts)
    return upserts


def _safe_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _str_or_none(value: Any, maxlen: int = 255) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s[:maxlen] if s else None


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


__all__ = ["run_job", "JOB_ID"]
