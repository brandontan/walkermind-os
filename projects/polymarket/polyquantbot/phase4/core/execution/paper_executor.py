"""Paper order executor with partial fills, dynamic slippage, and fees."""
from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass
from typing import Any

import structlog

log = structlog.get_logger()


@dataclass
class OrderResult:
    """Result of a paper order execution."""

    success: bool
    market_id: str
    fill_price: float
    filled_size: float
    requested_size: float
    latency_ms: int
    fee: float
    partial: bool = False
    error: str | None = None


class PaperExecutor:
    """Simulates order execution for paper trading."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Initialise with config."""
        paper_cfg = cfg.get("paper", {})
        trading_cfg = cfg.get("trading", {})
        self._slippage_bps = paper_cfg.get("slippage_bps", 50)
        self._fee_pct = trading_cfg.get("fee_pct", 0.02)
        self._depth_threshold = trading_cfg.get("market_depth_threshold", 50.0)

    async def execute_paper_order(
        self,
        market_id: str,
        price: float,
        size: float,
    ) -> OrderResult:
        """Simulate paper order with latency, slippage, partial fill, and fee."""
        start = time.time()

        # Simulate execution latency 100-250ms
        await asyncio.sleep(random.uniform(0.1, 0.25))

        # Partial fill if size exceeds depth threshold
        partial = size > self._depth_threshold
        filled_size = size * 0.5 if partial else size

        # Dynamic slippage: increases with size ratio
        size_ratio = filled_size / self._depth_threshold if self._depth_threshold > 0 else 1.0
        effective_slippage = self._slippage_bps * (1 + size_ratio * 0.5)
        fill_price = price * (1 + effective_slippage / 10_000)

        # Fee calculation
        fee = filled_size * self._fee_pct

        latency_ms = int((time.time() - start) * 1000)

        log.info(
            "paper_order_executed",
            market_id=market_id,
            fill_price=round(fill_price, 6),
            filled_size=round(filled_size, 4),
            requested_size=round(size, 4),
            partial=partial,
            fee=round(fee, 4),
            latency_ms=latency_ms,
        )

        return OrderResult(
            success=True,
            market_id=market_id,
            fill_price=fill_price,
            filled_size=filled_size,
            requested_size=size,
            latency_ms=latency_ms,
            fee=fee,
            partial=partial,
        )
