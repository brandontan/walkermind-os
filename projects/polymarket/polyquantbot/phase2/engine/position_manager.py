"""
Position lifecycle manager — Phase 2.
Evaluates exit conditions for all open positions each tick.
Returns list of ExitDecision for positions that should close.
"""

import random
import time
import structlog
from dataclasses import dataclass
from engine.state_manager import OpenTrade

log = structlog.get_logger()


@dataclass
class ExitDecision:
    trade: OpenTrade
    exit_price: float
    reason: str   # "TP" | "SL" | "TIMEOUT"
    pnl: float


def evaluate_exits(
    positions: list[OpenTrade],
    tp_pct: float,
    sl_pct: float,
    timeout_minutes: float,
) -> list[ExitDecision]:
    """
    For each open position, simulate a price tick and evaluate exit conditions.
    PnL = (exit_price - entry_price) * size - fee.
    Returns list of ExitDecision for all positions that hit TP, SL, or timeout.
    """
    decisions: list[ExitDecision] = []
    now = time.time()

    for pos in positions:
        drift = random.uniform(-0.04, 0.06)
        current_price = max(0.01, min(0.99, pos.entry_price + drift))
        gain_pct = (current_price - pos.entry_price) / pos.entry_price
        elapsed_min = (now - pos.opened_at) / 60.0

        reason: str | None = None
        if gain_pct >= tp_pct:
            reason = "TP"
        elif gain_pct <= -sl_pct:
            reason = "SL"
        elif elapsed_min >= timeout_minutes:
            reason = "TIMEOUT"

        if reason:
            pnl = round((current_price - pos.entry_price) * pos.size - pos.fee, 4)
            decisions.append(ExitDecision(
                trade=pos,
                exit_price=current_price,
                reason=reason,
                pnl=pnl,
            ))
            log.info(
                "exit_triggered",
                trade_id=pos.trade_id,
                market_id=pos.market_id,
                reason=reason,
                gain_pct=round(gain_pct * 100, 2),
                elapsed_min=round(elapsed_min, 1),
                pnl=pnl,
            )

    return decisions
