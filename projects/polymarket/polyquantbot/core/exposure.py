"""core.exposure — Exposure calculator for PolyQuantBot paper trading.

Computes per-position and aggregate exposure metrics relative to portfolio
equity.  Used for risk monitoring and Telegram reporting.

Interfaces::

    ExposureReport(total_exposure, position_count, positions,
                   max_single_exposure, exposure_pct_of_equity)
    ExposureCalculator.calculate(positions, wallet_state) → ExposureReport

Design:
  - Exposure per position = USD size locked in the position.
  - exposure_pct_of_equity = total_exposure / equity (0-div safe).
  - Structured JSON logging on every calculation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, List

import structlog

if TYPE_CHECKING:
    from .positions import PaperPosition
    from .wallet_engine import WalletState

log = structlog.get_logger(__name__)


# ── Data model ────────────────────────────────────────────────────────────────


@dataclass
class ExposureReport:
    """Aggregate exposure snapshot across all open positions.

    Attributes:
        total_exposure:        Total USD locked across all open positions.
        position_count:        Number of open positions.
        positions:             Per-position breakdown dicts.
        max_single_exposure:   Largest single position exposure in USD.
        exposure_pct_of_equity: total_exposure / equity (0.0 if equity == 0).
    """

    total_exposure: float
    position_count: int
    positions: List[dict]
    max_single_exposure: float
    exposure_pct_of_equity: float


# ── Calculator ────────────────────────────────────────────────────────────────


class ExposureCalculator:
    """Computes portfolio exposure from open positions and wallet state."""

    def calculate(
        self,
        positions: list[PaperPosition],
        wallet_state: WalletState,
    ) -> ExposureReport:
        """Compute an :class:`ExposureReport` for the given positions.

        Args:
            positions:    List of open :class:`~core.positions.PaperPosition`.
            wallet_state: Current :class:`~core.wallet_engine.WalletState`.

        Returns:
            Populated :class:`ExposureReport`.
        """
        if not positions:
            report = ExposureReport(
                total_exposure=0.0,
                position_count=0,
                positions=[],
                max_single_exposure=0.0,
                exposure_pct_of_equity=0.0,
            )
            log.info(
                "exposure_calculated",
                total_exposure=0.0,
                position_count=0,
                exposure_pct_of_equity=0.0,
            )
            return report

        position_details: List[dict] = []
        total_exposure: float = 0.0
        max_single: float = 0.0

        for pos in positions:
            exposure = round(pos.size, 4)
            total_exposure = round(total_exposure + exposure, 4)
            if exposure > max_single:
                max_single = exposure

            pct = (
                round(exposure / wallet_state.equity * 100, 2)
                if wallet_state.equity > 0
                else 0.0
            )

            position_details.append(
                {
                    "market_id": pos.market_id,
                    "side": pos.side,
                    "size": pos.size,
                    "entry_price": pos.entry_price,
                    "current_price": pos.current_price,
                    "unrealized_pnl": pos.unrealized_pnl,
                    "exposure_usd": exposure,
                    "exposure_pct": pct,
                }
            )

        equity = wallet_state.equity
        exposure_pct = (
            round(total_exposure / equity * 100, 2) if equity > 0 else 0.0
        )

        report = ExposureReport(
            total_exposure=total_exposure,
            position_count=len(positions),
            positions=position_details,
            max_single_exposure=round(max_single, 4),
            exposure_pct_of_equity=exposure_pct,
        )

        log.info(
            "exposure_calculated",
            total_exposure=total_exposure,
            position_count=len(positions),
            max_single_exposure=max_single,
            exposure_pct_of_equity=exposure_pct,
            equity=equity,
        )
        return report
