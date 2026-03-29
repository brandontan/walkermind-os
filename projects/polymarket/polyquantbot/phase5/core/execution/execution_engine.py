"""Execution engine — Phase 5.

Hybrid maker/taker with slippage guard and partial fill retry.
Wraps paper_executor; OrderResult contract unchanged.
"""
from __future__ import annotations

import asyncio
import time

import structlog

from ..signal_model import SignalResult
from .paper_executor import OrderResult, execute_paper_order

log = structlog.get_logger()


class ExecutionEngine:
    """Hybrid maker/taker execution with slippage guard and partial fill retry."""

    def __init__(
        self,
        maker_timeout_ms: int,
        maker_spread_threshold: float,
        max_slippage_pct: float,
        min_order_size: float,
        slippage_bps: int,
        fee_pct: float,
        market_depth_threshold: float,
    ) -> None:
        """Initialise engine from config values."""
        self._maker_timeout_ms = maker_timeout_ms
        self._maker_spread_threshold = maker_spread_threshold
        self._max_slippage_pct = max_slippage_pct
        self._min_order_size = min_order_size
        self._slippage_bps = slippage_bps
        self._fee_pct = fee_pct
        self._depth_threshold = market_depth_threshold

    async def execute(
        self,
        market_id: str,
        outcome: str,
        price: float,
        size: float,
        market_ctx: dict,
        correlation_id: str = "",
    ) -> OrderResult:
        """Execute order with maker/taker hybrid logic.

        Steps:
          1. Compute spread from market_ctx.
          2. Choose MAKER if spread >= threshold, else TAKER.
          3. MAKER: attempt limit fill within timeout; fallback to TAKER.
          4. Slippage guard: abort or reduce size on breach.
          5. Partial fill: retry taker for remainder if >= min_order_size.

        Returns:
            Merged OrderResult (filled_size = sum of fills).
        """
        bound = log.bind(
            correlation_id=correlation_id,
            market_id=market_id,
            outcome=outcome,
        )
        t0 = time.time()

        bid: float = market_ctx.get("bid", price - 0.005)
        ask: float = market_ctx.get("ask", price + 0.005)
        spread = ask - bid

        mode = "MAKER" if spread >= self._maker_spread_threshold else "TAKER"
        limit_price = bid + spread * 0.3 if outcome == "YES" else ask - spread * 0.3

        # ── MAKER attempt ─────────────────────────────────────────────────────
        primary_result: OrderResult | None = None
        if mode == "MAKER":
            try:
                result = await asyncio.wait_for(
                    execute_paper_order(
                        market_id=market_id,
                        outcome=outcome,
                        price=limit_price,
                        size=size,
                        slippage_bps=self._slippage_bps // 2,
                        fee_pct=self._fee_pct,
                        market_depth_threshold=self._depth_threshold,
                    ),
                    timeout=self._maker_timeout_ms / 1000,
                )
                primary_result = result
                bound.info("maker_filled",
                           filled_price=result.filled_price, size=result.filled_size)
            except asyncio.TimeoutError:
                bound.warning("maker_timeout", timeout_ms=self._maker_timeout_ms)
                mode = "TAKER_FALLBACK"
            except Exception as exc:
                bound.warning("maker_error", error=str(exc))
                mode = "TAKER_FALLBACK"

        # ── TAKER (original or fallback) ──────────────────────────────────────────
        if primary_result is None:
            primary_result = await execute_paper_order(
                market_id=market_id,
                outcome=outcome,
                price=ask if outcome == "YES" else bid,
                size=size,
                slippage_bps=self._slippage_bps,
                fee_pct=self._fee_pct,
                market_depth_threshold=self._depth_threshold,
            )

        # ── Slippage guard ───────────────────────────────────────────────────────
        slippage_pct = abs(primary_result.filled_price - price) / max(price, 1e-9)
        if slippage_pct > self._max_slippage_pct:
            if primary_result.filled_size > self._min_order_size * 2:
                reduced_size = primary_result.filled_size * 0.5
                bound.warning(
                    "slippage_guard_size_reduced",
                    slippage_pct=round(slippage_pct * 100, 3),
                    original_size=primary_result.filled_size,
                    reduced_size=reduced_size,
                )
                primary_result = OrderResult(
                    order_id=primary_result.order_id,
                    market_id=primary_result.market_id,
                    outcome=primary_result.outcome,
                    filled_price=primary_result.filled_price,
                    filled_size=reduced_size,
                    fee=round(reduced_size * self._fee_pct, 4),
                    status="SLIPPAGE_REDUCED",
                )
            else:
                bound.warning(
                    "slippage_guard_abort",
                    slippage_pct=round(slippage_pct * 100, 3),
                    size=primary_result.filled_size,
                )
                return OrderResult(
                    order_id=primary_result.order_id,
                    market_id=market_id,
                    outcome=outcome,
                    filled_price=primary_result.filled_price,
                    filled_size=0.0,
                    fee=0.0,
                    status="ABORTED_SLIPPAGE",
                )

        # ── Partial fill retry ─────────────────────────────────────────────────────
        final_result = primary_result
        if primary_result.status == "PARTIAL":
            remaining = size - primary_result.filled_size
            if remaining >= self._min_order_size:
                bound.info("partial_fill_retry", remaining=remaining)
                try:
                    retry = await execute_paper_order(
                        market_id=market_id,
                        outcome=outcome,
                        price=ask,
                        size=remaining,
                        slippage_bps=self._slippage_bps,
                        fee_pct=self._fee_pct,
                        market_depth_threshold=self._depth_threshold,
                    )
                    merged_size = primary_result.filled_size + retry.filled_size
                    merged_fee = primary_result.fee + retry.fee
                    avg_price = (
                        primary_result.filled_price * primary_result.filled_size
                        + retry.filled_price * retry.filled_size
                    ) / max(merged_size, 1e-9)
                    final_result = OrderResult(
                        order_id=primary_result.order_id,
                        market_id=market_id,
                        outcome=outcome,
                        filled_price=round(avg_price, 6),
                        filled_size=round(merged_size, 4),
                        fee=round(merged_fee, 4),
                        status="FILLED",
                    )
                except Exception as exc:
                    bound.warning("partial_retry_failed", error=str(exc))

        elapsed_ms = int((time.time() - t0) * 1000)
        bound.info(
            "execution_detail",
            mode=mode,
            spread=round(spread, 6),
            slippage_pct=round(slippage_pct * 100, 3),
            latency_ms=elapsed_ms,
            filled_size=final_result.filled_size,
            filled_price=final_result.filled_price,
            fee=final_result.fee,
            status=final_result.status,
        )
        return final_result

    async def execute_arb_pair(
        self,
        sig_yes: SignalResult,
        sig_no: SignalResult,
        size: float,
        market_ctx: dict,
        correlation_id: str,
    ) -> tuple[OrderResult, OrderResult]:
        """Execute YES and NO legs sequentially for arbitrage.

        No rollback in paper mode. Logs warning if either leg aborted.
        """
        bound = log.bind(
            correlation_id=correlation_id,
            market_id=sig_yes.market_id,
            strategy="arbitrage",
        )
        bound.info("arb_pair_start", size=size)

        res_yes = await self.execute(
            market_id=sig_yes.market_id, outcome="YES",
            price=sig_yes.p_market, size=size,
            market_ctx=market_ctx, correlation_id=correlation_id,
        )
        res_no = await self.execute(
            market_id=sig_no.market_id, outcome="NO",
            price=sig_no.p_market, size=size,
            market_ctx=market_ctx, correlation_id=correlation_id,
        )

        if "ABORTED" in res_yes.status or "ABORTED" in res_no.status:
            bound.warning("arb_pair_partial_abort",
                          yes_status=res_yes.status, no_status=res_no.status)
        else:
            bound.info("arb_pair_complete",
                       yes_filled=res_yes.filled_size, no_filled=res_no.filled_size)
        return res_yes, res_no
