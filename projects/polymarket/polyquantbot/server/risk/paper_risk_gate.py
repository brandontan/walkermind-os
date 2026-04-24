"""Risk gate enforcement for paper beta execution path."""
from __future__ import annotations

from dataclasses import dataclass

from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal


@dataclass(frozen=True)
class RiskDecision:
    allowed: bool
    reason: str = ""


class PaperRiskGate:
    MIN_EDGE = 0.02
    LIQUIDITY_FLOOR = 10000.0
    MAX_EXPOSURE = 0.10
    MAX_DRAWDOWN = 0.08
    MAX_POSITION_NOTIONAL_FRACTION = 0.10
    DAILY_LOSS_LIMIT = -2000.0

    def evaluate(self, signal: CandidateSignal, state: PublicBetaState) -> RiskDecision:
        if state.kill_switch:
            return RiskDecision(False, "kill_switch_enabled")
        if signal.signal_id in state.processed_signals:
            return RiskDecision(False, "idempotency_duplicate")
        if signal.edge <= 0:
            return RiskDecision(False, "non_positive_ev")
        if signal.edge < self.MIN_EDGE:
            return RiskDecision(False, "edge_below_threshold")
        if signal.liquidity < self.LIQUIDITY_FLOOR:
            return RiskDecision(False, "liquidity_below_floor")
        if state.drawdown > self.MAX_DRAWDOWN:
            return RiskDecision(False, "drawdown_stop")
        if state.paper_account.realized_pnl <= self.DAILY_LOSS_LIMIT:
            return RiskDecision(False, "daily_loss_limit_stop")
        position_notional = 100.0 * signal.price
        if position_notional > (state.paper_account.equity * self.MAX_POSITION_NOTIONAL_FRACTION):
            return RiskDecision(False, "position_notional_cap")
        if state.exposure >= self.MAX_EXPOSURE:
            return RiskDecision(False, "exposure_cap")
        if state.mode != "paper":
            return RiskDecision(False, "mode_not_paper_default")
        return RiskDecision(True, "allowed")
