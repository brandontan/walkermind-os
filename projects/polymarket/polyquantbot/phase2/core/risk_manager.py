"""
Position sizing: fractional Kelly capped at max_position_pct.
"""

import structlog

log = structlog.get_logger()

KELLY_FRACTION = 0.25


def get_position_size(
    balance: float,
    ev: float,
    p_model: float,
    p_market: float,
    max_position_pct: float,
) -> float:
    """
    Kelly f = (p*b - q) / b, scaled by KELLY_FRACTION.
    Final size = min(kelly_size, max_position_pct * balance).
    Returns 0.0 if Kelly is non-positive or balance is zero.
    """
    if p_market <= 0 or p_market >= 1 or balance <= 0:
        return 0.0

    b = (1.0 / p_market) - 1.0
    q = 1.0 - p_model
    kelly_f = (p_model * b - q) / b if b > 0 else 0.0

    if kelly_f <= 0:
        return 0.0

    fractional_f = kelly_f * KELLY_FRACTION
    kelly_size = balance * fractional_f
    max_size = balance * max_position_pct
    size = min(kelly_size, max_size)

    if size < 1.0:
        return 0.0

    log.info(
        "position_sized",
        kelly_f=round(kelly_f, 4),
        fractional_f=round(fractional_f, 4),
        size=round(size, 2),
        max_size=round(max_size, 2),
    )
    return round(size, 2)
