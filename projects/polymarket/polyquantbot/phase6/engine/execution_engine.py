"""Execution engine — Phase 6 rewrite.

EV-aware routing with dynamic cost model, strict decision tree,
liquidity cap, adaptive limit pricing, and partial fill protection.

──────────────────────────────────────────────────────────────────
COST MODEL
──────────────────────────────────────────────────────────────────
  volatility    = spread / max(mid_price, ε)         ← spread-implied vol proxy
  alpha_buffer  = clamp(base_alpha + vol × scale, 0, max_alpha)
  expected_cost = slippage_bps/10_000 + taker_fee + alpha_buffer

All costs expressed as a fraction of the order price for comparison with EV.

──────────────────────────────────────────────────────────────────
FILL PROBABILITY
──────────────────────────────────────────────────────────────────
  spread_score = clamp(spread / maker_threshold, 0.0, 1.0)
  depth_score  = clamp(1 − size / max(volume × 0.2, size × 2), 0.1, 1.0)
  fill_prob    = spread_score × depth_score   ∈ [0.0, 1.0]

──────────────────────────────────────────────────────────────────
DECISION TREE
──────────────────────────────────────────────────────────────────
  1. EV ≤ 0                                        → REJECT
  2. EV < expected_cost                            → REJECT (no edge after cost)
  3. spread ≥ maker_threshold AND fill_prob ≥ fill_prob_threshold
                                                   → MAKER  (earn the spread)
  4. EV > expected_cost × hybrid_ev_multiplier     → TAKER  (high edge, take now)
  5. else                                          → HYBRID (MAKER try → TAKER fallback)

──────────────────────────────────────────────────────────────────
LIQUIDITY CAP
──────────────────────────────────────────────────────────────────
  cap           = volume × liquidity_cap_pct
  adjusted_size = min(requested_size, cap)   if cap ≥ min_order_size

──────────────────────────────────────────────────────────────────
ADAPTIVE PRICING (limit orders)
──────────────────────────────────────────────────────────────────
  offset      = spread × 0.3          ← 30% inside the spread
  YES limit   = bid + offset          ← aggressive inside ask
  NO  limit   = ask − offset          ← aggressive inside bid

──────────────────────────────────────────────────────────────────
PARTIAL FILL PROTECTION
──────────────────────────────────────────────────────────────────
  • Safe precision via Decimal ROUND_DOWN to lot_step.
    (Handles FP artifacts like 4.999999 that floor() would wrongly round to 4.)
  • Max 1 TAKER retry for remaining unfilled size.
  • Abort retry if remaining < min_order_size.
  • Abort retry if slippage > max_slippage_pct on either leg.
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

import structlog

from ..config.execution_config import ExecutionConfig
from ..core.execution.paper_executor import OrderResult, execute_paper_order
from ..core.signal_model import SignalResult

log = structlog.get_logger()


# ── ExecutionDecision ─────────────────────────────────────────────────────────

@dataclass
class ExecutionDecision:
    """Routing decision produced by ExecutionEngine.decide().

    Consumed by ExecutionEngine.execute() and persisted in POSITION_SIZED payload.
    """

    mode: str           # TAKER | MAKER | HYBRID | REJECT
    limit_price: float  # adaptive limit price for MAKER/HYBRID
    adjusted_size: float    # after liquidity cap + lot rounding
    expected_cost: float    # total cost fraction (slippage + fee + alpha_buffer)
    fill_prob: float        # estimated maker fill probability ∈ [0, 1]
    reason: str             # human-readable decision rationale
    correlation_id: str
    market_id: str
    outcome: str            # "YES" | "NO"


# ── ExecutionEngine ───────────────────────────────────────────────────────────

class ExecutionEngine:
    """Phase 6 execution engine: decide routing, execute orders, protect fills."""

    def __init__(self, cfg: ExecutionConfig) -> None:
        """Initialise with immutable ExecutionConfig.

        Args:
            cfg: Frozen ExecutionConfig dataclass from config.yaml.
        """
        self._cfg = cfg

    # ── Private helpers ───────────────────────────────────────────────────────

    def _calc_expected_cost(
        self,
        price: float,
        spread: float,
    ) -> float:
        """Compute expected cost as fraction of price.

        Components:
            slippage_frac = slippage_bps / 10_000
            volatility    = spread / max(price, ε)        (spread-implied vol)
            alpha_buffer  = clamp(base_alpha + vol × scale, 0, max_alpha)
            total_cost    = slippage_frac + taker_fee + alpha_buffer

        Extreme volatility is capped at max_alpha_buffer to bound the buffer.
        """
        slippage_frac = self._cfg.slippage_bps / 10_000
        volatility = spread / max(price, 1e-9)
        raw_alpha = self._cfg.base_alpha_buffer + volatility * self._cfg.volatility_scale
        alpha_buffer = min(raw_alpha, self._cfg.max_alpha_buffer)
        return slippage_frac + self._cfg.taker_fee_pct + alpha_buffer

    def _calc_fill_prob(
        self,
        spread: float,
        size: float,
        volume: float,
    ) -> float:
        """Estimate probability of a maker limit order filling.

        Intuition:
          - Wider spread → more room for a limit order → higher fill chance.
          - Smaller size relative to depth → less market impact → higher fill.

        Clamped to [0.0, 1.0].
        """
        spread_score = min(spread / max(self._cfg.maker_spread_threshold, 1e-9), 1.0)
        denominator = max(volume * 0.2, size * 2.0, 1e-9)
        depth_score = max(0.1, min(1.0, 1.0 - size / denominator))
        return round(spread_score * depth_score, 6)

    def _apply_liquidity_cap(self, size: float, volume: float) -> float:
        """Cap order size to liquidity_cap_pct of market volume.

        Only applies cap when it would still yield a viable order.
        """
        cap = volume * self._cfg.liquidity_cap_pct
        if cap >= self._cfg.min_order_size:
            return min(size, cap)
        return size

    def _round_to_lot(self, size: float) -> float:
        """Round size DOWN to nearest lot_step using Decimal.

        Handles floating-point artifacts (e.g., 4.999999 instead of 5.0):
          1. Pre-round to 6 decimal places to collapse near-integer values.
          2. Use Decimal ROUND_DOWN to lot_step for exact integer arithmetic.

        Example:
            size=4.999999, lot_step=1.0 → round(4.999999, 6)=5.0 → 5.0
            size=5.4, lot_step=1.0      → round(5.4, 6)=5.4     → 5.0
        """
        if self._cfg.lot_step <= 0:
            return size
        safe = round(size, 6)           # collapse FP artifacts first
        step = Decimal(str(self._cfg.lot_step))
        val = Decimal(str(safe))
        rounded = (val / step).to_integral_value(rounding=ROUND_DOWN) * step
        return float(rounded)

    def _adaptive_limit_price(
        self,
        outcome: str,
        bid: float,
        ask: float,
        spread: float,
    ) -> float:
        """Compute adaptive limit price inside the spread.

        Offset = spread × 0.3  (30% inside — aggressive but not crossing).
        YES buyers: limit = bid + offset  (inside the spread, below ask)
        NO  buyers: limit = ask − offset  (inside the spread, above bid)
        """
        offset = spread * 0.3
        if outcome == "YES":
            price = bid + offset
        else:
            price = ask - offset
        return round(max(0.01, min(0.99, price)), 6)

    # ── Public API ────────────────────────────────────────────────────────────

    def decide(
        self,
        signal: SignalResult,
        size: float,
        market_ctx: dict,
        correlation_id: str,
    ) -> ExecutionDecision:
        """Apply the Phase 6 decision tree to produce an ExecutionDecision.

        The decision is purely synchronous (no I/O). Routing is based on:
          expected_cost, fill_prob, spread, and EV.

        Args:
            signal: Adjusted signal from CorrelationEngine.
            size: Proposed size from CapitalAllocator (USD).
            market_ctx: Snapshot dict with bid, ask, volume, spread keys.
            correlation_id: Request ID for log correlation.

        Returns:
            ExecutionDecision with mode and all parameters for execute().
        """
        market_id = signal.market_id
        outcome = signal.outcome
        ev = signal.ev
        p_market = signal.p_market

        bid: float = market_ctx.get("bid", p_market - 0.005)
        ask: float = market_ctx.get("ask", p_market + 0.005)
        spread = max(ask - bid, 1e-6)
        volume: float = market_ctx.get("volume", 100.0)

        # ── Step 1: Liquidity cap + lot rounding ──────────────────────────────
        capped_size = self._apply_liquidity_cap(size, volume)
        adjusted_size = self._round_to_lot(capped_size)

        if adjusted_size < self._cfg.min_order_size:
            return ExecutionDecision(
                mode="REJECT",
                limit_price=p_market,
                adjusted_size=0.0,
                expected_cost=0.0,
                fill_prob=0.0,
                reason="adjusted_size_below_min_order_size",
                correlation_id=correlation_id,
                market_id=market_id,
                outcome=outcome,
            )

        # ── Step 2: Cost model ────────────────────────────────────────────────
        expected_cost = self._calc_expected_cost(p_market, spread)
        fill_prob = self._calc_fill_prob(spread, adjusted_size, volume)
        limit_price = self._adaptive_limit_price(outcome, bid, ask, spread)

        # ── Step 3: Decision tree ─────────────────────────────────────────────
        if ev <= 0:
            mode = "REJECT"
            reason = f"ev={ev:.6f} <= 0"

        elif ev < expected_cost:
            mode = "REJECT"
            reason = f"ev={ev:.6f} < expected_cost={expected_cost:.6f}"

        elif (
            spread >= self._cfg.maker_spread_threshold
            and fill_prob >= self._cfg.fill_prob_threshold
        ):
            mode = "MAKER"
            reason = (
                f"spread={spread:.4f} >= threshold={self._cfg.maker_spread_threshold}"
                f", fill_prob={fill_prob:.3f} >= {self._cfg.fill_prob_threshold}"
            )

        elif ev > expected_cost * self._cfg.hybrid_ev_multiplier:
            mode = "TAKER"
            reason = (
                f"ev={ev:.6f} > cost*{self._cfg.hybrid_ev_multiplier}"
                f"={expected_cost * self._cfg.hybrid_ev_multiplier:.6f}"
            )

        else:
            mode = "HYBRID"
            reason = (
                f"hybrid: ev={ev:.6f}, cost={expected_cost:.6f}, "
                f"fill_prob={fill_prob:.3f}"
            )

        log.info(
            "execution_decision",
            correlation_id=correlation_id,
            market_id=market_id,
            outcome=outcome,
            strategy=signal.strategy,
            mode=mode,
            reason=reason,
            ev=round(ev, 6),
            expected_cost=round(expected_cost, 6),
            fill_prob=round(fill_prob, 4),
            spread=round(spread, 6),
            adjusted_size=adjusted_size,
            limit_price=limit_price,
        )

        return ExecutionDecision(
            mode=mode,
            limit_price=limit_price,
            adjusted_size=adjusted_size,
            expected_cost=round(expected_cost, 6),
            fill_prob=round(fill_prob, 4),
            reason=reason,
            correlation_id=correlation_id,
            market_id=market_id,
            outcome=outcome,
        )

    async def execute(
        self,
        decision: ExecutionDecision,
        signal: SignalResult,
        market_ctx: dict,
        cfg_paper: dict,
    ) -> OrderResult:
        """Execute an order based on an ExecutionDecision.

        Execution path:
          REJECT → return zero-filled OrderResult immediately.
          MAKER  → attempt limit order at decision.limit_price.
          TAKER  → take at market ask/bid price.
          HYBRID → try MAKER (asyncio.wait_for timeout), fallback to TAKER.

        After primary fill:
          - Slippage guard: abort (filled_size=0) if slippage > max_slippage_pct.
          - Partial fill: one TAKER retry for remaining size if:
              remaining = _round_to_lot(total − filled) >= min_order_size
              AND retry slippage ≤ max_slippage_pct.
          - Merged result uses size-weighted average price.

        Args:
            decision: Output of decide().
            signal: Adjusted signal (for p_market reference).
            market_ctx: Live bid/ask/volume context.
            cfg_paper: Paper trading config dict (slippage_bps, etc.).

        Returns:
            OrderResult with filled_size=0 if rejected/aborted.
        """
        if decision.mode == "REJECT":
            return OrderResult(
                order_id=str(uuid.uuid4()),
                market_id=decision.market_id,
                outcome=decision.outcome,
                filled_price=0.0,
                filled_size=0.0,
                fee=0.0,
                status="REJECTED",
            )

        bound = log.bind(
            correlation_id=decision.correlation_id,
            market_id=decision.market_id,
            outcome=decision.outcome,
            mode=decision.mode,
        )

        t0 = time.time()
        bid: float = market_ctx.get("bid", signal.p_market - 0.005)
        ask: float = market_ctx.get("ask", signal.p_market + 0.005)
        slippage_bps: int = cfg_paper.get("slippage_bps", self._cfg.slippage_bps)
        depth_threshold: float = cfg_paper.get(
            "market_depth_threshold", self._cfg.market_depth_threshold
        )

        # ── Primary execution ─────────────────────────────────────────────────
        primary: OrderResult | None = None

        if decision.mode in ("MAKER", "HYBRID"):
            try:
                primary = await asyncio.wait_for(
                    execute_paper_order(
                        market_id=decision.market_id,
                        outcome=decision.outcome,
                        price=decision.limit_price,
                        size=decision.adjusted_size,
                        slippage_bps=slippage_bps // 2,    # tighter for maker
                        fee_pct=self._cfg.maker_fee_pct,
                        market_depth_threshold=depth_threshold,
                    ),
                    timeout=self._cfg.maker_timeout_ms / 1000,
                )
                bound.info(
                    "maker_filled",
                    filled_price=primary.filled_price,
                    size=primary.filled_size,
                    status=primary.status,
                )
            except asyncio.TimeoutError:
                bound.warning("maker_timeout", timeout_ms=self._cfg.maker_timeout_ms)
                primary = None
            except Exception as exc:
                bound.warning("maker_error", error=str(exc))
                primary = None

        # TAKER (original or fallback for HYBRID/MAKER timeout)
        if primary is None:
            taker_price = ask if decision.outcome == "YES" else bid
            primary = await execute_paper_order(
                market_id=decision.market_id,
                outcome=decision.outcome,
                price=taker_price,
                size=decision.adjusted_size,
                slippage_bps=slippage_bps,
                fee_pct=self._cfg.taker_fee_pct,
                market_depth_threshold=depth_threshold,
            )

        # ── Slippage guard ────────────────────────────────────────────────────
        ref_price = signal.p_market
        slippage_pct = abs(primary.filled_price - ref_price) / max(ref_price, 1e-9)
        if slippage_pct > self._cfg.max_slippage_pct:
            bound.warning(
                "execution_abort_slippage",
                slippage_pct=round(slippage_pct * 100, 3),
                max_slippage_pct=round(self._cfg.max_slippage_pct * 100, 1),
                filled_price=primary.filled_price,
                ref_price=ref_price,
            )
            return OrderResult(
                order_id=primary.order_id,
                market_id=decision.market_id,
                outcome=decision.outcome,
                filled_price=primary.filled_price,
                filled_size=0.0,
                fee=0.0,
                status="ABORTED_SLIPPAGE",
            )

        # ── Partial fill protection (max 1 TAKER retry) ───────────────────────
        final = primary
        if primary.status == "PARTIAL":
            raw_remaining = decision.adjusted_size - primary.filled_size
            # Safe lot rounding: round(val, 6) first eliminates FP artifacts
            remaining = self._round_to_lot(raw_remaining)

            if remaining < self._cfg.min_order_size:
                bound.info(
                    "partial_fill_remainder_below_min",
                    remaining=remaining,
                    min_size=self._cfg.min_order_size,
                )
            else:
                bound.info("partial_fill_retry", remaining=remaining)
                taker_retry_price = ask if decision.outcome == "YES" else bid
                try:
                    retry = await execute_paper_order(
                        market_id=decision.market_id,
                        outcome=decision.outcome,
                        price=taker_retry_price,
                        size=remaining,
                        slippage_bps=self._cfg.partial_slippage_bps,
                        fee_pct=self._cfg.taker_fee_pct,
                        market_depth_threshold=depth_threshold,
                    )
                    retry_slippage = (
                        abs(retry.filled_price - ref_price) / max(ref_price, 1e-9)
                    )
                    if retry_slippage > self._cfg.max_slippage_pct:
                        bound.warning(
                            "partial_retry_abort_slippage",
                            retry_slippage_pct=round(retry_slippage * 100, 3),
                        )
                        # Keep only primary fill — do not merge
                    else:
                        merged_size = primary.filled_size + retry.filled_size
                        if merged_size > 0:
                            avg_price = (
                                primary.filled_price * primary.filled_size
                                + retry.filled_price * retry.filled_size
                            ) / merged_size
                        else:
                            avg_price = primary.filled_price
                        final = OrderResult(
                            order_id=primary.order_id,
                            market_id=decision.market_id,
                            outcome=decision.outcome,
                            filled_price=round(avg_price, 6),
                            filled_size=round(merged_size, 4),
                            fee=round(primary.fee + retry.fee, 4),
                            status="FILLED",
                        )
                        bound.info(
                            "partial_fill_merged",
                            total_size=final.filled_size,
                            avg_price=final.filled_price,
                        )
                except Exception as exc:
                    bound.warning("partial_retry_error", error=str(exc))

        elapsed_ms = int((time.time() - t0) * 1000)
        bound.info(
            "execution_complete",
            filled_size=final.filled_size,
            filled_price=final.filled_price,
            fee=final.fee,
            status=final.status,
            latency_ms=elapsed_ms,
        )
        return final
