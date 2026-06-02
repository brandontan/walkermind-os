"""PLAYBOOK Market Quality Filter.

No sports strategy module may run before a market passes these checks. The
filter rejects markets that fail minimum liquidity, maximum spread, minimum
orderbook depth, resolution clarity, or event integrity. Pure functions — no
DB access, no async — mirroring the ``domain/execution/slippage.py`` guard
style so the filter is trivially unit-testable.

Thresholds are PLAYBOOK-local defaults (sports books are thinner and wider
than the crypto-candle books the core gate was tuned for). They never relax
the downstream risk gate, which re-enforces its own liquidity floor.
"""
from __future__ import annotations

from dataclasses import dataclass

# PLAYBOOK-local sports market-quality defaults. Conservative for thin sports
# books; the risk gate applies its own (independent) liquidity floor downstream.
MIN_LIQUIDITY_USDC: float = 5_000.0
MAX_SPREAD: float = 0.08
MIN_TOP_DEPTH_USDC: float = 250.0


@dataclass(frozen=True)
class MarketQualityResult:
    """Verdict from the Market Quality Filter.

    ``accepted`` is the gate; ``reason`` is a stable machine-readable code
    (``"ok"`` on pass). The numeric fields are populated best-effort for
    observability and may be ``None`` when the input was missing/invalid.
    """

    accepted: bool
    reason: str
    liquidity_usdc: float | None = None
    spread: float | None = None
    top_depth_usdc: float | None = None


def evaluate_market_quality(
    *,
    liquidity_usdc: float,
    best_bid: float,
    best_ask: float,
    top_depth_usdc: float,
    resolution_clear: bool,
    event_integrity_ok: bool,
    min_liquidity_usdc: float = MIN_LIQUIDITY_USDC,
    max_spread: float = MAX_SPREAD,
    min_top_depth_usdc: float = MIN_TOP_DEPTH_USDC,
) -> MarketQualityResult:
    """Return ``accepted=True`` only if every quality check passes.

    Checks, in order (first failure short-circuits with a stable reason):

      1. event integrity — the event/market is not flagged inconsistent.
      2. resolution clarity — resolution criteria are unambiguous.
      3. liquidity floor — ``liquidity_usdc >= min_liquidity_usdc``.
      4. price sanity — ``0 < best_bid <= best_ask < 1`` (binary bounds).
      5. spread cap — ``best_ask - best_bid <= max_spread``.
      6. depth floor — ``top_depth_usdc >= min_top_depth_usdc``.

    All inputs are caller-supplied snapshots; this function performs no IO.
    """
    if not event_integrity_ok:
        return MarketQualityResult(accepted=False, reason="event_integrity_failed")
    if not resolution_clear:
        return MarketQualityResult(accepted=False, reason="resolution_unclear")

    if liquidity_usdc < min_liquidity_usdc:
        return MarketQualityResult(
            accepted=False,
            reason=f"liquidity_{liquidity_usdc:.0f}_below_{min_liquidity_usdc:.0f}",
            liquidity_usdc=liquidity_usdc,
        )

    # Binary-market price sanity: bid/ask must be ordered and within (0, 1).
    if not (0.0 < best_bid <= best_ask < 1.0):
        return MarketQualityResult(
            accepted=False,
            reason=f"price_bounds_bid_{best_bid:.4f}_ask_{best_ask:.4f}",
            liquidity_usdc=liquidity_usdc,
        )

    spread = best_ask - best_bid
    if spread > max_spread:
        return MarketQualityResult(
            accepted=False,
            reason=f"spread_{spread:.4f}_exceeds_{max_spread:.4f}",
            liquidity_usdc=liquidity_usdc,
            spread=spread,
        )

    if top_depth_usdc < min_top_depth_usdc:
        return MarketQualityResult(
            accepted=False,
            reason=f"depth_{top_depth_usdc:.0f}_below_{min_top_depth_usdc:.0f}",
            liquidity_usdc=liquidity_usdc,
            spread=spread,
            top_depth_usdc=top_depth_usdc,
        )

    return MarketQualityResult(
        accepted=True,
        reason="ok",
        liquidity_usdc=liquidity_usdc,
        spread=spread,
        top_depth_usdc=top_depth_usdc,
    )


__all__ = [
    "MarketQualityResult",
    "evaluate_market_quality",
    "MIN_LIQUIDITY_USDC",
    "MAX_SPREAD",
    "MIN_TOP_DEPTH_USDC",
]
