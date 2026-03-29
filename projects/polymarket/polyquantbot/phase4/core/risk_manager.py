"""Fractional Kelly risk manager — unchanged from Phase 2."""
from __future__ import annotations

from typing import Any

import structlog

log = structlog.get_logger()

KELLY_FRACTION = 0.25  # CLAUDE.md: always alpha = 0.25


class RiskManager:
    """Sizes positions using fractional Kelly criterion."""

    def __init__(self, cfg: dict[str, Any]) -> None:
        """Initialise with config."""
        self._max_position_pct = cfg.get("trading", {}).get("max_position_pct", 0.10)

    def get_position_size(
        self,
        ev: float,
        p_model: float,
        p_market: float,
        balance: float,
    ) -> float:
        """Return position size in dollars using fractional Kelly.

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
        capped_f = min(fractional_f, self._max_position_pct)
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
