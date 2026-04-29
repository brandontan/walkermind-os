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
        if state.exposure >= self.MAX_EXPOSURE:
            return RiskDecision(False, "exposure_cap")
        if state.mode != "paper":
            return RiskDecision(False, "mode_not_paper_default")
        return RiskDecision(True, "allowed")

    def status(self, state: PublicBetaState) -> dict[str, object]:
        """Return current risk gate state snapshot for operator visibility.

        Args:
            state: Live PublicBetaState.

        Returns:
            Dict with current thresholds and live state values.
        """
        state.reset_daily_pnl_if_needed()
        drawdown_pct = round(state.drawdown * 100, 2)
        exposure_pct = round(state.exposure * 100, 2)
        daily_pnl = state.daily_realized_pnl
        return {
            "kill_switch": state.kill_switch,
            "mode": state.mode,
            "drawdown_pct": drawdown_pct,
            "drawdown_limit_pct": round(self.MAX_DRAWDOWN * 100, 1),
            "drawdown_ok": state.drawdown <= self.MAX_DRAWDOWN,
            "exposure_pct": exposure_pct,
            "exposure_limit_pct": round(self.MAX_EXPOSURE * 100, 1),
            "exposure_ok": state.exposure < self.MAX_EXPOSURE,
            "min_edge": self.MIN_EDGE,
            "liquidity_floor_usd": self.LIQUIDITY_FLOOR,
            "daily_pnl_usd": round(daily_pnl, 2),
            "daily_loss_limit_usd": self.DAILY_LOSS_LIMIT,
            "daily_pnl_ok": daily_pnl >= self.DAILY_LOSS_LIMIT,
            "last_risk_reason": state.last_risk_reason,
            "wallet_cash": state.wallet_cash,
            "wallet_equity": state.wallet_equity,
            "open_positions": len(state.positions),
        }
