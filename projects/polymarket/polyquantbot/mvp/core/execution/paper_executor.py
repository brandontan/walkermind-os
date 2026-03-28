"""
Paper trade executor — simulates fills with latency and slippage.
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
    status: str   # "FILLED" | "REJECTED"


async def execute_paper_order(
    market_id: str,
    outcome: str,
    price: float,
    size: float,
    slippage_bps: int,
) -> OrderResult:
    """
    Simulate paper execution:
    - Random latency 100–250ms
    - Apply slippage: price += slippage_bps/10000
    """
    latency_ms = random.randint(100, 250)
    await asyncio.sleep(latency_ms / 1000)

    slippage = price * (slippage_bps / 10_000)
    filled_price = min(price + slippage, 0.999)   # cap at 0.999

    order_id = str(uuid.uuid4())
    log.info(
        "paper_order_filled",
        order_id=order_id,
        market_id=market_id,
        filled_price=round(filled_price, 6),
        filled_size=size,
        latency_ms=latency_ms,
    )
    return OrderResult(
        order_id=order_id,
        market_id=market_id,
        outcome=outcome,
        filled_price=filled_price,
        filled_size=size,
        status="FILLED",
    )
