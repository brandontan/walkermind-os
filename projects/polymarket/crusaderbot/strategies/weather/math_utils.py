"""Statistical utilities for weather edge detection."""
from __future__ import annotations

import math


def norm_cdf(x: float) -> float:
    """Standard normal CDF via complementary error function."""
    return 0.5 * math.erfc(-x / math.sqrt(2.0))


def bucket_prob(mean: float, sigma: float, low: float, high: float) -> float:
    """Probability that a normally-distributed variable falls in [low, high).

    Returns exact mass when sigma > 0, discrete indicator when sigma == 0.
    """
    if sigma <= 0.0:
        return 1.0 if low <= mean < high else 0.0
    return norm_cdf((high - mean) / sigma) - norm_cdf((low - mean) / sigma)


def expected_value(p_true: float, price: float) -> float:
    """Expected return per dollar invested for a YES position.

    EV = p * (1/price - 1) - (1 - p)  =  (p_true - price) / price
    Returns 0.0 for degenerate prices.
    """
    if price <= 0.0:
        return 0.0
    return (p_true - price) / price


def kelly_size(
    ev: float,
    p_true: float,
    price: float,
    bankroll: float,
    alpha: float = 0.25,
    max_bet: float = 20.0,
) -> float:
    """Fractional Kelly position size in USDC.

    Full Kelly (YES) = (p_true - price) / (1 - price)
    Size = alpha * full_kelly * bankroll, capped at max_bet.
    alpha=0.25 is LOCKED — full Kelly (alpha=1.0) is forbidden.
    Returns 0.0 when EV <= 0 or price is degenerate.
    """
    if ev <= 0.0 or price <= 0.0 or price >= 1.0:
        return 0.0
    denom = 1.0 - price
    if denom <= 0.0:
        return 0.0
    full_kelly = ev / denom
    size = alpha * full_kelly * bankroll
    return round(min(max(size, 0.0), max_bet), 2)
