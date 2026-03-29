"""Paper order executor — Phase 6.

Unchanged contract from Phase 5. Simulates order fills with latency,
slippage, partial fills, and fee deduction.

OrderResult fields: order_id, market_id, outcome, filled_price,
                    filled_size, fee, status.
"""
from __future__ import annotations

import asyncio
import random
import uuid
from dataclasses import dataclass

import structlog

log = structlog.get_logger()


@dataclass
class OrderResult:
    """Result of a paper order execution."""

    order_id: str
    market_id: str
    outcome: str            # "YES" | "NO"
    filled_price: float
    filled_size: float
    fee: float
    status: str             # FILLED | PARTIAL | ABORTED_SLIPPAGE | SLIPPAGE_REDUCED | REJECTED


async def execute_paper_order(
    market_id: str,
    outcome: str,
    price: float,
    size: float,
    slippage_bps: int = 50,
    fee_pct: float = 0.02,
    market_depth_threshold: float = 50.0,
) -> OrderResult:
    """Simulate paper order with latency, slippage, partial fill, and fee.

    Args:
        market_id: Target market identifier.
        outcome: "YES" or "NO".
        price: Requested fill price.
        size: Requested position size in dollars.
        slippage_bps: Slippage in basis points.
        fee_pct: Fee as fraction of filled size.
        market_depth_threshold: Threshold above which partial fills occur.

    Returns:
        OrderResult with fill details.
    """
    # Simulate execution latency 100–250ms
    await asyncio.sleep(random.uniform(0.1, 0.25))

    partial = size > market_depth_threshold
    filled_size = size * 0.5 if partial else size

    size_ratio = filled_size / max(market_depth_threshold, 1e-9)
    effective_slippage = slippage_bps * (1 + size_ratio * 0.5)
    filled_price = price * (1 + effective_slippage / 10_000)

    fee = filled_size * fee_pct
    status = "PARTIAL" if partial else "FILLED"

    log.info(
        "paper_order_executed",
        market_id=market_id,
        outcome=outcome,
        filled_price=round(filled_price, 6),
        filled_size=round(filled_size, 4),
        requested_size=round(size, 4),
        partial=partial,
        fee=round(fee, 4),
        status=status,
    )

    return OrderResult(
        order_id=str(uuid.uuid4()),
        market_id=market_id,
        outcome=outcome,
        filled_price=filled_price,
        filled_size=filled_size,
        fee=fee,
        status=status,
    )
