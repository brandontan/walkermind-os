"""Slippage guardrail — market-impact and price-deviation checks.

Enforces two independent limits:

  1. Market-impact guard: rejects orders where
       size_usdc / market_liquidity > MAX_MARKET_IMPACT_PCT
     This prevents a single order from consuming a disproportionate share
     of available depth and incurring excessive slippage on entry.

  2. Price-deviation guard (for live orders): rejects when the proposed
     entry price deviates from the reference mid by more than MAX_SLIPPAGE_PCT.
     Not called in paper mode; wired by the readiness validator for live-path
     pre-flight checks.

Both checks are pure functions — no DB access, no async.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from ..risk import constants as K


@dataclass(frozen=True)
class SlippageResult:
    accepted: bool
    reason: str
    impact_pct: float | None = None
    price_deviation_pct: float | None = None


def check_market_impact(
    size_usdc: Decimal,
    market_liquidity: float,
    *,
    threshold_pct: float = K.MAX_MARKET_IMPACT_PCT,
) -> SlippageResult:
    """Return rejected if size would consume > threshold_pct of market liquidity.

    ``market_liquidity=0`` is treated as insufficient depth (rejected) to
    prevent division-by-zero and to block orders into illiquid markets.
    """
    if market_liquidity <= 0:
        return SlippageResult(
            accepted=False,
            reason="market_liquidity_zero",
            impact_pct=None,
        )
    impact = float(size_usdc) / market_liquidity
    if impact > threshold_pct:
        return SlippageResult(
            accepted=False,
            reason=f"market_impact_{impact:.4f}_exceeds_{threshold_pct:.4f}",
            impact_pct=impact,
        )
    return SlippageResult(accepted=True, reason="ok", impact_pct=impact)


def check_price_deviation(
    proposed_price: float,
    reference_price: float,
    *,
    threshold_pct: float = K.MAX_SLIPPAGE_PCT,
) -> SlippageResult:
    """Return rejected if proposed_price deviates from reference by > threshold.

    Used for live pre-submission checks; paper orders do not call this.
    ``reference_price=0`` is treated as invalid (rejected).
    """
    if reference_price <= 0:
        return SlippageResult(
            accepted=False,
            reason="reference_price_invalid",
            price_deviation_pct=None,
        )
    deviation = abs(proposed_price - reference_price) / reference_price
    if deviation > threshold_pct:
        return SlippageResult(
            accepted=False,
            reason=f"price_deviation_{deviation:.4f}_exceeds_{threshold_pct:.4f}",
            price_deviation_pct=deviation,
        )
    return SlippageResult(accepted=True, reason="ok", price_deviation_pct=deviation)
