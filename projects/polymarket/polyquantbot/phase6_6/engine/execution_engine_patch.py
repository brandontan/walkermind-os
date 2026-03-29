"""Execution engine patch — Phase 6.6.

Replaces the Phase 6 fill-probability model with a physics-inspired,
deterministic formula that reacts realistically to three independent
market conditions:

    depth_ratio   = min(depth / max(size, 1e-3), 10.0)
    latency_penalty = exp(−latency_ms × volatility × 0.01)
    spread_penalty  = exp(−spread × 10)
    fill_prob       = clamp(depth_ratio × latency_penalty × spread_penalty, 0, 1)

Interpretation:
    depth_ratio:     order is small relative to available liquidity → easier fill.
                     Capped at 10 to prevent extreme values dominating.
    latency_penalty: high latency × high volatility → price likely to move away
                     before maker limit order is reached → lower fill chance.
    spread_penalty:  wide spread → market is illiquid or stressed → harder fill.

Design guarantees:
    - Fully deterministic (no random.* calls).
    - Monotone in each dimension when others are fixed.
    - All intermediate values are finite (exp() cannot produce NaN given
      finite inputs; depth/size division guarded by 1e-3 floor).
    - Output always ∈ [0.0, 1.0].

Backward compatibility:
    ExecutionEnginePatch exposes:
      - calc_fill_prob(depth, size, latency_ms, volatility, spread, correlation_id)
          → float ∈ [0.0, 1.0]
      - decide_v2(signal_ev, size, market_ctx, latency_ms, volatility, correlation_id)
          → ExecutionDecisionV2 dataclass (strict superset of Phase 6 ExecutionDecision)

    The Phase 6 ExecutionEngine.decide() and .execute() remain unchanged.
    Callers may replace the fill_prob value in the decision dict before
    calling execute(), or use ExecutionEnginePatch.decide_v2() directly.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal
from typing import Optional

import structlog

log = structlog.get_logger()

# Hard limits on dynamic fill-prob factors
_DEPTH_RATIO_CAP: float = 10.0
_MIN_DENOM: float = 1e-3     # minimum size denominator (avoid /0)
_MIN_PRICE: float = 1e-9     # minimum price reference


def _clamp(value: float, lo: float, hi: float) -> float:
    """Clamp a float to the closed interval [lo, hi]."""
    return max(lo, min(hi, value))


# ── Result dataclasses ────────────────────────────────────────────────────────

@dataclass
class FillProbResult:
    """Diagnostic breakdown of the fill_prob computation."""

    fill_prob: float
    depth_ratio: float
    latency_penalty: float
    spread_penalty: float
    inputs: dict          # raw inputs for tracing
    correlation_id: str


@dataclass
class ExecutionDecisionV2:
    """Phase 6.6 routing decision — strict superset of Phase 6 ExecutionDecision.

    All Phase 6 fields are present; new fields are additive (no removals).
    Compatible with Phase 6 execute() after extracting base fields.
    """

    # ── Phase 6 fields (unchanged) ────────────────────────────────────────────
    mode: str             # TAKER | MAKER | HYBRID | REJECT
    limit_price: float    # adaptive limit price for MAKER/HYBRID
    adjusted_size: float  # after liquidity cap + lot rounding
    expected_cost: float  # total cost fraction
    fill_prob: float      # estimated maker fill probability ∈ [0, 1]
    reason: str
    correlation_id: str
    market_id: str
    outcome: str          # "YES" | "NO"

    # ── Phase 6.6 additions ───────────────────────────────────────────────────
    fill_prob_breakdown: Optional[FillProbResult] = None
    latency_ms: float = 0.0
    volatility: float = 0.0


# ── Core calculator ───────────────────────────────────────────────────────────

class ExecutionEnginePatch:
    """Phase 6.6 patch providing a realistic, deterministic fill-prob model.

    Can be used standalone (calc_fill_prob) or as a full routing engine
    (decide_v2) that wraps the Phase 6 decision tree with the new model.

    Thread-safety: fully stateless — safe for concurrent asyncio use.
    """

    def __init__(
        self,
        # ── Cost model params (mirrors ExecutionConfig) ───────────────────────
        slippage_bps: int = 50,
        taker_fee_pct: float = 0.02,
        maker_fee_pct: float = 0.01,
        base_alpha_buffer: float = 0.005,
        max_alpha_buffer: float = 0.05,
        volatility_scale: float = 2.0,
        # ── Routing params ────────────────────────────────────────────────────
        maker_spread_threshold: float = 0.02,
        fill_prob_threshold: float = 0.60,
        hybrid_ev_multiplier: float = 2.0,
        # ── Sizing params ─────────────────────────────────────────────────────
        min_order_size: float = 5.0,
        lot_step: float = 1.0,
        liquidity_cap_pct: float = 0.10,
        max_slippage_pct: float = 0.03,
    ) -> None:
        """Initialise with execution parameters.

        All defaults mirror Phase 6 config.yaml execution block.
        Construct via from_config() for production use.
        """
        self._slippage_bps = slippage_bps
        self._taker_fee = taker_fee_pct
        self._maker_fee = maker_fee_pct
        self._base_alpha = base_alpha_buffer
        self._max_alpha = max_alpha_buffer
        self._vol_scale = volatility_scale
        self._maker_thresh = maker_spread_threshold
        self._fill_prob_thresh = fill_prob_threshold
        self._hybrid_mult = hybrid_ev_multiplier
        self._min_size = min_order_size
        self._lot_step = lot_step
        self._liq_cap_pct = liquidity_cap_pct
        self._max_slip = max_slippage_pct

    # ── Phase 6.6 fill-probability model ─────────────────────────────────────

    def calc_fill_prob(
        self,
        depth: float,
        size: float,
        latency_ms: float,
        volatility: float,
        spread: float,
        correlation_id: str,
    ) -> FillProbResult:
        """Compute deterministic fill probability.

        Formula::
            depth_ratio    = min(depth / max(size, 1e-3), 10.0)
            latency_penalty = exp(−latency_ms × volatility × 0.01)
            spread_penalty  = exp(−spread × 10)
            fill_prob       = clamp(depth_ratio × latency_penalty × spread_penalty, 0, 1)

        Args:
            depth: Available market depth at current price (USD).
            size: Proposed order size (USD).
            latency_ms: Current round-trip latency in milliseconds.
            volatility: Realised volatility of recent returns (e.g., stdev of log-returns).
            spread: Absolute bid-ask spread at current price.
            correlation_id: Request ID for log tracing.

        Returns:
            FillProbResult with fill_prob ∈ [0.0, 1.0] and diagnostic breakdown.
        """
        # Guard all inputs against degenerate values
        safe_size = max(size, _MIN_DENOM)
        safe_depth = max(depth, 0.0)
        safe_latency = max(latency_ms, 0.0)
        safe_vol = max(volatility, 0.0)
        safe_spread = max(spread, 0.0)

        depth_ratio = min(safe_depth / safe_size, _DEPTH_RATIO_CAP)

        # Exponent: latency_ms * volatility * 0.01
        # Example: latency=100ms, vol=0.02 → exp(-0.02) ≈ 0.98 (small penalty)
        #          latency=500ms, vol=0.10 → exp(-0.50) ≈ 0.61 (significant penalty)
        lat_exp = safe_latency * safe_vol * 0.01
        latency_penalty = math.exp(-lat_exp)  # always ∈ (0, 1]

        # Exponent: spread * 10
        # Example: spread=0.02 → exp(-0.20) ≈ 0.82
        #          spread=0.10 → exp(-1.00) ≈ 0.37
        spread_exp = safe_spread * 10.0
        spread_penalty = math.exp(-spread_exp)  # always ∈ (0, 1]

        raw_fill_prob = depth_ratio * latency_penalty * spread_penalty
        fill_prob = round(_clamp(raw_fill_prob, 0.0, 1.0), 6)

        result = FillProbResult(
            fill_prob=fill_prob,
            depth_ratio=round(depth_ratio, 4),
            latency_penalty=round(latency_penalty, 6),
            spread_penalty=round(spread_penalty, 6),
            inputs={
                "depth": safe_depth,
                "size": safe_size,
                "latency_ms": safe_latency,
                "volatility": safe_vol,
                "spread": safe_spread,
            },
            correlation_id=correlation_id,
        )

        log.info(
            "fill_probability_calculated",
            correlation_id=correlation_id,
            fill_prob=fill_prob,
            depth_ratio=result.depth_ratio,
            latency_penalty=result.latency_penalty,
            spread_penalty=result.spread_penalty,
            depth=safe_depth,
            size=safe_size,
            latency_ms=safe_latency,
            volatility=round(safe_vol, 6),
            spread=round(safe_spread, 6),
        )

        return result

    # ── Supporting cost model (mirrors Phase 6 exactly) ──────────────────────

    def _calc_expected_cost(self, price: float, spread: float) -> float:
        """Compute expected cost fraction (identical to Phase 6 formula)."""
        slippage_frac = self._slippage_bps / 10_000
        vol_proxy = spread / max(price, _MIN_PRICE)
        raw_alpha = self._base_alpha + vol_proxy * self._vol_scale
        alpha_buffer = min(raw_alpha, self._max_alpha)
        return slippage_frac + self._taker_fee + alpha_buffer

    def _apply_liquidity_cap(self, size: float, volume: float) -> float:
        """Cap order size to liquidity_cap_pct of market volume."""
        cap = volume * self._liq_cap_pct
        if cap >= self._min_size:
            return min(size, cap)
        return size

    def _round_to_lot(self, size: float) -> float:
        """Round size DOWN to nearest lot_step using Decimal to avoid FP artifacts.

        Pre-rounds to 6 decimal places first to collapse values like 4.999999 → 5.0
        before applying ROUND_DOWN, preventing undershoot by one lot.
        """
        if self._lot_step <= 0:
            return size
        safe = round(size, 6)
        step = Decimal(str(self._lot_step))
        val = Decimal(str(safe))
        rounded = (val / step).to_integral_value(rounding=ROUND_DOWN) * step
        return float(rounded)

    def _adaptive_limit_price(
        self, outcome: str, bid: float, ask: float, spread: float
    ) -> float:
        """30%-inside-spread limit price (identical to Phase 6)."""
        offset = spread * 0.3
        price = (bid + offset) if outcome == "YES" else (ask - offset)
        return round(_clamp(price, 0.01, 0.99), 6)

    # ── Full routing (Phase 6.6 decision tree) ────────────────────────────────

    def decide_v2(
        self,
        signal_ev: float,
        signal_p_market: float,
        signal_outcome: str,
        signal_market_id: str,
        signal_strategy: str,
        size: float,
        market_ctx: dict,
        latency_ms: float,
        volatility: float,
        correlation_id: str,
    ) -> ExecutionDecisionV2:
        """Apply Phase 6 decision tree with Phase 6.6 fill-prob model.

        The decision tree logic is IDENTICAL to Phase 6 (no regression):
            1. EV ≤ 0                                         → REJECT
            2. EV < expected_cost                             → REJECT
            3. spread ≥ maker_threshold AND fill_prob ≥ thresh → MAKER
            4. EV > expected_cost × hybrid_multiplier         → TAKER
            5. else                                           → HYBRID

        The ONLY change is fill_prob is now computed by calc_fill_prob()
        instead of the Phase 6 spread_score × depth_score formula.

        Args:
            signal_ev: Adjusted EV from CorrelationEngine.
            signal_p_market: Market price from signal.
            signal_outcome: "YES" or "NO".
            signal_market_id: Market ID.
            signal_strategy: Source strategy name.
            size: Proposed size after CapitalAllocator.
            market_ctx: Dict with keys: bid, ask, volume, spread, depth (optional).
            latency_ms: Current round-trip latency.
            volatility: Realised volatility of recent returns.
            correlation_id: Request ID.

        Returns:
            ExecutionDecisionV2 (superset of Phase 6 ExecutionDecision).
        """
        ev = signal_ev
        p_market = signal_p_market
        outcome = signal_outcome
        market_id = signal_market_id

        bid: float = market_ctx.get("bid", p_market - 0.005)
        ask: float = market_ctx.get("ask", p_market + 0.005)
        spread = max(ask - bid, 1e-6)
        volume: float = market_ctx.get("volume", 100.0)
        depth: float = market_ctx.get("depth", volume * 0.5)  # fallback: 50% of volume

        # ── Sizing ────────────────────────────────────────────────────────────
        capped = self._apply_liquidity_cap(size, volume)
        adjusted_size = self._round_to_lot(capped)

        if adjusted_size < self._min_size:
            return ExecutionDecisionV2(
                mode="REJECT",
                limit_price=p_market,
                adjusted_size=0.0,
                expected_cost=0.0,
                fill_prob=0.0,
                reason="adjusted_size_below_min_order_size",
                correlation_id=correlation_id,
                market_id=market_id,
                outcome=outcome,
                latency_ms=latency_ms,
                volatility=volatility,
            )

        # ── Cost model ────────────────────────────────────────────────────────
        expected_cost = self._calc_expected_cost(p_market, spread)
        limit_price = self._adaptive_limit_price(outcome, bid, ask, spread)

        # ── Phase 6.6 fill probability ────────────────────────────────────────
        fp_result = self.calc_fill_prob(
            depth=depth,
            size=adjusted_size,
            latency_ms=latency_ms,
            volatility=volatility,
            spread=spread,
            correlation_id=correlation_id,
        )
        fill_prob = fp_result.fill_prob

        # ── Decision tree (identical logic to Phase 6) ────────────────────────
        if ev <= 0:
            mode = "REJECT"
            reason = f"ev={ev:.6f} <= 0"

        elif ev < expected_cost:
            mode = "REJECT"
            reason = f"ev={ev:.6f} < expected_cost={expected_cost:.6f}"

        elif spread >= self._maker_thresh and fill_prob >= self._fill_prob_thresh:
            mode = "MAKER"
            reason = (
                f"spread={spread:.4f} >= {self._maker_thresh}, "
                f"fill_prob={fill_prob:.3f} >= {self._fill_prob_thresh}"
            )

        elif ev > expected_cost * self._hybrid_mult:
            mode = "TAKER"
            reason = (
                f"ev={ev:.6f} > cost*{self._hybrid_mult}"
                f"={expected_cost * self._hybrid_mult:.6f}"
            )

        else:
            mode = "HYBRID"
            reason = (
                f"hybrid: ev={ev:.6f}, cost={expected_cost:.6f}, "
                f"fill_prob={fill_prob:.3f}, latency_ms={latency_ms:.0f}"
            )

        log.info(
            "execution_decision_v2",
            correlation_id=correlation_id,
            market_id=market_id,
            outcome=outcome,
            strategy=signal_strategy,
            mode=mode,
            reason=reason,
            ev=round(ev, 6),
            expected_cost=round(expected_cost, 6),
            fill_prob=fill_prob,
            spread=round(spread, 6),
            adjusted_size=adjusted_size,
            limit_price=limit_price,
            latency_ms=latency_ms,
            volatility=round(volatility, 6),
        )

        return ExecutionDecisionV2(
            mode=mode,
            limit_price=limit_price,
            adjusted_size=adjusted_size,
            expected_cost=round(expected_cost, 6),
            fill_prob=fill_prob,
            reason=reason,
            correlation_id=correlation_id,
            market_id=market_id,
            outcome=outcome,
            fill_prob_breakdown=fp_result,
            latency_ms=latency_ms,
            volatility=volatility,
        )

    # ── Factory ───────────────────────────────────────────────────────────────

    @classmethod
    def from_config(cls, cfg: dict) -> "ExecutionEnginePatch":
        """Build from top-level config dict (reads 'execution' block).

        Args:
            cfg: Top-level config dict loaded from config.yaml.
        """
        e = cfg.get("execution", {})
        return cls(
            slippage_bps=int(e.get("slippage_bps", 50)),
            taker_fee_pct=float(e.get("taker_fee_pct", 0.02)),
            maker_fee_pct=float(e.get("maker_fee_pct", 0.01)),
            base_alpha_buffer=float(e.get("base_alpha_buffer", 0.005)),
            max_alpha_buffer=float(e.get("max_alpha_buffer", 0.05)),
            volatility_scale=float(e.get("volatility_scale", 2.0)),
            maker_spread_threshold=float(e.get("maker_spread_threshold", 0.02)),
            fill_prob_threshold=float(e.get("fill_prob_threshold", 0.60)),
            hybrid_ev_multiplier=float(e.get("hybrid_ev_multiplier", 2.0)),
            min_order_size=float(e.get("min_order_size", 5.0)),
            lot_step=float(e.get("lot_step", 1.0)),
            liquidity_cap_pct=float(e.get("liquidity_cap_pct", 0.10)),
            max_slippage_pct=float(e.get("max_slippage_pct", 0.03)),
        )
