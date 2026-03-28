"""
Paper executor — Phase 2.
Adds: partial fill simulation, dynamic slippage, fee calculation.
"""

import asyncio
import random
import uuid
import structlog
from dataclasses import dataclass

log = structlog.get_logger()


@dataclass
class OrderResult:
    order_id: str
    market_id: str
    outcome: str
    filled_price: float
    filled_size: float
    fee: float
    status: str   # "FILLED" | "PARTIAL" | "REJECTED"


async def execute_paper_order(
    market_id: str,
    outcome: str,
    price: float,
    size: float,
    slippage_bps: int,
    fee_pct: float,
    market_depth_threshold: float,
) -> OrderResult:
    """
    Simulate paper execution with:
    - Latency: 100–250ms
    - Dynamic slippage: scales with size/depth ratio
    - Partial fill: if size > depth threshold, fill 50%
    - Fee: fee_pct * filled_size
    """
    latency_ms = random.randint(100, 250)
    await asyncio.sleep(latency_ms / 1000)

    # Partial fill simulation
    if size > market_depth_threshold:
        filled_size = round(size * 0.5, 2)
        status = "PARTIAL"
    else:
        filled_size = size
        status = "FILLED"

    # Dynamic slippage: base + size-driven component
    size_ratio = filled_size / max(market_depth_threshold, 1.0)
    dynamic_slippage_bps = slippage_bps * (1.0 + size_ratio * 0.5)
    slippage = price * (dynamic_slippage_bps / 10_000)
    filled_price = min(price + slippage, 0.999)

    fee = round(filled_size * fee_pct, 4)
    order_id = str(uuid.uuid4())

    log.info(
        "paper_order_executed",
        order_id=order_id,
        market_id=market_id,
        filled_price=round(filled_price, 6),
        filled_size=filled_size,
        fee=fee,
        status=status,
        latency_ms=latency_ms,
    )

    return OrderResult(
        order_id=order_id,
        market_id=market_id,
        outcome=outcome,
        filled_price=filled_price,
        filled_size=filled_size,
        fee=fee,
        status=status,
    )
