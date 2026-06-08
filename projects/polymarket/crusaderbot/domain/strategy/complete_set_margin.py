"""Adaptive complete-set arbitrage margin — heuristic, pure, IO-free.

The static path requires a fixed per-pair net margin (``MIN_COMPLETE_SET_EDGE``,
clamped to the 2% hard floor). This module makes that requirement *adaptive to
live market conditions*: it measures the execution-slippage risk of the current
order books and RAISES the required margin when a fill would walk into a thin /
steep book. It can only ever ADD a premium on top of the floor — never relax
below it — so the AGENTS.md arbitrage invariant (locked net edge >= 2%) holds
regardless of what conditions the heuristic sees.

Edge thesis for the premium: a complete-set arb is "riskless" only at the prices
displayed *now*. The real risk is that, by fill time, the price has moved — and a
thin/steep book is exactly where a displayed arb is most fragile (top-of-book is
stale, depth evaporates, your own take walks the price up). So we measure how
much the average fill price rises versus top-of-book when buying the intended
size on each leg, sum both legs (same $/pair units as the margin), and require
that much extra edge. A deep, tight book => premium ~ 0 => behaves like the
static base. This is the substrate a future calibrated/ML model replaces: it
emits a feature vector per evaluation for shadow logging.

SCOPE: pure synchronous math. No DB, no network, no async, no risk-gate. The
caller (services/signal_scan/complete_set_scan) resolves the base floor + the
enable flag and passes the parsed books in.
"""
from __future__ import annotations

from dataclasses import dataclass

from .complete_set_arb import _asks_ascending  # ascending, cleaned (price,size)

# Cap the adaptive premium so a pathological / near-empty book can never demand
# an absurd edge (which would silently disable the arb instead of pricing it).
ADAPTIVE_PREMIUM_CAP_USDC: float = 0.10  # $/pair on top of the base floor
# Floor on the reference size used to probe the book when the caller passes a
# non-positive intended size (keeps the impact measure well-defined).
_MIN_REF_SHARES: float = 1.0


@dataclass(frozen=True)
class AdaptiveMarginDecision:
    """Result of pricing the per-pair required margin for one market."""

    required_margin: float            # base_floor + premium (>= base_floor)
    base_floor: float                 # max(operator base, 2% hard floor) — passed in
    premium: float                    # adaptive add-on, in USDC/pair, >= 0, <= cap
    features: dict[str, float]        # shadow-log substrate for a future ML model


def _avg_fill_price(asks_ascending: list[tuple[float, float]], ref_shares: float) -> tuple[float, float, float]:
    """Walk ``asks`` cheapest-first to buy up to ``ref_shares``.

    Returns ``(best_ask, avg_fill_price, filled_shares)``. ``avg_fill_price``
    equals ``best_ask`` for a book deep enough to fill ``ref_shares`` at the top
    level; it rises as the take walks into worse levels. Empty book => NaNs/0.
    """
    if not asks_ascending:
        return (float("nan"), float("nan"), 0.0)
    best = asks_ascending[0][0]
    filled = 0.0
    cost = 0.0
    for price, size in asks_ascending:
        take = min(size, ref_shares - filled)
        if take <= 0.0:
            break
        filled += take
        cost += take * price
        if filled >= ref_shares:
            break
    if filled <= 0.0:
        return (best, best, 0.0)
    return (best, cost / filled, filled)


def adaptive_required_margin(
    *,
    base_floor: float,
    yes_book: dict | None,
    no_book: dict | None,
    intended_shares: float,
    seconds_to_resolution: float | None = None,
    premium_cap: float = ADAPTIVE_PREMIUM_CAP_USDC,
) -> AdaptiveMarginDecision:
    """Price the per-pair required margin from live book conditions.

    ``base_floor`` MUST already be the max(operator base, 2% hard floor); this
    function only adds a non-negative premium on top, so the returned
    ``required_margin`` is always >= base_floor >= the hard floor. Never raises:
    a malformed/empty book yields a zero-premium decision (falls back to the
    static base) so a bad book can never *lower* the bar or crash the scan.
    """
    ref = intended_shares if intended_shares and intended_shares > 0.0 else _MIN_REF_SHARES
    ya = _asks_ascending(yes_book)
    na = _asks_ascending(no_book)
    yes_best, yes_avg, yes_filled = _avg_fill_price(ya, ref)
    no_best, no_avg, no_filled = _avg_fill_price(na, ref)

    # Per-leg slippage = avg fill - best ask (>= 0). Sum both legs => $/pair the
    # take is expected to cost above top-of-book at the intended size. NaN-safe:
    # an empty book contributes 0 (handled by the >0 guards below).
    yes_slip = yes_avg - yes_best if (yes_avg == yes_avg and yes_best == yes_best) else 0.0
    no_slip = no_avg - no_best if (no_avg == no_avg and no_best == no_best) else 0.0
    impact = max(0.0, yes_slip) + max(0.0, no_slip)

    premium = min(max(0.0, impact), premium_cap)
    required = base_floor + premium

    features = {
        "intended_shares": round(ref, 6),
        "yes_impact_usdc": round(max(0.0, yes_slip), 6),
        "no_impact_usdc": round(max(0.0, no_slip), 6),
        "impact_usdc_per_pair": round(impact, 6),
        "yes_filled_shares": round(yes_filled, 6),
        "no_filled_shares": round(no_filled, 6),
        "premium_usdc": round(premium, 6),
        "base_floor": round(base_floor, 6),
        "required_margin": round(required, 6),
        # Logged for a future calibrated model; not yet priced into the premium.
        "seconds_to_resolution": (
            float(seconds_to_resolution) if seconds_to_resolution is not None else -1.0
        ),
    }
    return AdaptiveMarginDecision(
        required_margin=required,
        base_floor=base_floor,
        premium=round(premium, 6),
        features=features,
    )


__all__ = ["AdaptiveMarginDecision", "adaptive_required_margin", "ADAPTIVE_PREMIUM_CAP_USDC"]
