"""telegram.handlers.exposure — Exposure report UI handler for PolyQuantBot.

Displays aggregate and per-position exposure vs portfolio equity.
Dependencies are injected at bot startup.

Return type: tuple[str, list]  (text, InlineKeyboard)
"""
from __future__ import annotations

from typing import Optional, TYPE_CHECKING

import structlog

from ..ui.keyboard import build_status_menu

if TYPE_CHECKING:
    from ...core.exposure import ExposureCalculator
    from ...core.positions import PaperPositionManager
    from ...core.wallet_engine import WalletEngine

log = structlog.get_logger(__name__)

# Module-level injected dependencies
_exposure_calculator: Optional["ExposureCalculator"] = None
_position_manager: Optional["PaperPositionManager"] = None
_wallet_engine: Optional["WalletEngine"] = None


def set_exposure_calculator(calc: "ExposureCalculator") -> None:
    """Inject ExposureCalculator instance at bot startup."""
    global _exposure_calculator  # noqa: PLW0603
    _exposure_calculator = calc
    log.info("exposure_handler_calculator_injected")


def set_position_manager(pm: "PaperPositionManager") -> None:
    """Inject PaperPositionManager instance at bot startup."""
    global _position_manager  # noqa: PLW0603
    _position_manager = pm
    log.info("exposure_handler_position_manager_injected")


def set_wallet_engine(engine: "WalletEngine") -> None:
    """Inject WalletEngine instance at bot startup."""
    global _wallet_engine  # noqa: PLW0603
    _wallet_engine = engine
    log.info("exposure_handler_wallet_engine_injected")


async def handle_exposure() -> tuple[str, list]:
    """Return exposure report screen.

    Shows total exposure, exposure as % of equity, position count,
    and per-position breakdown.

    Returns:
        ``(text, keyboard)`` tuple.
    """
    if _exposure_calculator is None or _position_manager is None or _wallet_engine is None:
        log.warning(
            "exposure_handler_not_ready",
            has_calc=_exposure_calculator is not None,
            has_pm=_position_manager is not None,
            has_wallet=_wallet_engine is not None,
        )
        return (
            "⚠️ *Exposure Report*\n\n_Services not available._",
            build_status_menu(),
        )

    try:
        positions = _position_manager.get_all_open()
        wallet_state = _wallet_engine.get_state()
        report = _exposure_calculator.calculate(positions, wallet_state)
    except Exception as exc:
        log.error("exposure_handler_calculation_error", error=str(exc))
        return "❌ *Error calculating exposure*", build_status_menu()

    if report.position_count == 0:
        text = (
            "📉 *Exposure Report*\n\n"
            "_No open positions — zero exposure._\n\n"
            f"💰 Equity: ${wallet_state.equity:.2f}\n"
            f"💵 Cash: ${wallet_state.cash:.2f} | "
            f"🔒 Locked: ${wallet_state.locked:.2f}"
        )
        return text, build_status_menu()

    lines = [
        "📉 *Exposure Report*\n",
        f"💰 Equity: ${wallet_state.equity:.2f}",
        f"💵 Cash: ${wallet_state.cash:.2f} | 🔒 Locked: ${wallet_state.locked:.2f}",
        f"🔒 Total Exposure: ${report.total_exposure:.2f}",
        f"📊 Exposure %: {report.exposure_pct_of_equity:.1f} %",
        f"📌 Positions: {report.position_count}",
        f"⚠️ Max Single: ${report.max_single_exposure:.2f}\n",
    ]

    if report.positions:
        lines.append("*Per-position:*")
        for p in report.positions:
            pnl_sign = "+" if p["unrealized_pnl"] >= 0 else ""
            lines.append(
                f"• `{_truncate(p['market_id'], 18)}` {p['side']} "
                f"${p['size']:.2f} ({p['exposure_pct']:.1f}%) "
                f"PnL: {pnl_sign}{p['unrealized_pnl']:.4f}"
            )

    text = "\n".join(lines)
    log.info(
        "exposure_handler_report_displayed",
        position_count=report.position_count,
        total_exposure=report.total_exposure,
        exposure_pct=report.exposure_pct_of_equity,
    )
    return text, build_status_menu()


# ── Internal helpers ──────────────────────────────────────────────────────────


def _truncate(s: str, max_len: int) -> str:
    """Truncate a string with ellipsis if it exceeds *max_len*."""
    return s if len(s) <= max_len else s[: max_len - 1] + "…"
