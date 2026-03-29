"""Fractional Kelly risk manager — Phase 5.

Provides a standalone get_position_size() function.
All callers pass balance and params explicitly.
"""
from __future__ import annotations

import structlog

log = structlog.get_logger()

KELLY_FRACTION = 0.25  # CLAUDE.md: always alpha = 0.25


def get_position_size(
    balance: float,
    ev: float,
    p_model: float,
    p_market: float,
    max_position_pct: float = 0.10,
) -> float:
    """Return position size in dollars using fractional Kelly criterion.

    Returns 0.0 if Kelly fraction is non-positive or size < $1.
    """
    if p_market <= 0 or p_market >= 1:
        return 0.0
    b = (1.0 / p_market) - 1.0
    if b <= 0:
        return 0.0
    q = 1.0 - p_model
    kelly_f = (p_model * b - q) / b
    if kelly_f <= 0:
        return 0.0
    fractional_f = kelly_f * KELLY_FRACTION
    capped_f = min(fractional_f, max_position_pct)
    size = balance * capped_f
    if size < 1.0:
        return 0.0
    log.debug(
        "position_sized",
        kelly_f=round(kelly_f, 4),
        fractional_f=round(fractional_f, 4),
        capped_f=round(capped_f, 4),
        size=round(size, 4),
    )
    return size
