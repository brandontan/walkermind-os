"""Capital-mode risk gate for CrusaderBot server layer.

CapitalRiskGate is the capital-mode counterpart to PaperRiskGate.
All limits are read from a CapitalModeConfig instance instead of
hardcoded constants. In LIVE mode the full 5-gate guard is enforced
before any signal evaluation; in PAPER mode only risk bounds apply.

WalletFinancialProvider is the protocol that callers must implement
to supply live balance/exposure/drawdown values for WalletCandidate
enrichment.  In P8-B the interface is established; a live-data
implementation is a P8-C deliverable.

Usage::

    cfg = CapitalModeConfig.from_env()
    gate = CapitalRiskGate(config=cfg)
    decision = gate.evaluate(signal, state)

    # Wallet candidate enrichment (P8-B wiring contract):
    provider = MyFinancialProvider(portfolio_service)
    enriched = enrich_candidate(candidate, provider)
"""
from __future__ import annotations

from dataclasses import replace
from typing import Protocol, runtime_checkable

import structlog

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.orchestration.schemas import WalletCandidate
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import RiskDecision

log = structlog.get_logger(__name__)

_MIN_EDGE: float = 0.02


# ── WalletFinancialProvider protocol ─────────────────────────────────────────


@runtime_checkable
class WalletFinancialProvider(Protocol):
    """Protocol for supplying live financial data for a wallet candidate.

    Implementors read from the appropriate data source (portfolio store,
    market data feed, etc.) and return current values.  All three fields
    must be provided — 0.0 is only valid when the wallet has no activity.

    Attributes returned by each method:
        balance_usd:  Available liquid balance in USD.
        exposure_pct: Current exposure as fraction of equity (0.0–1.0).
        drawdown_pct: Current drawdown as fraction of peak equity (0.0–1.0).
    """

    def get_balance_usd(self, wallet_id: str) -> float:
        """Return the wallet's current liquid USD balance."""
        ...

    def get_exposure_pct(self, wallet_id: str) -> float:
        """Return the wallet's current exposure fraction (0.0–1.0)."""
        ...

    def get_drawdown_pct(self, wallet_id: str) -> float:
        """Return the wallet's current drawdown fraction (0.0–1.0)."""
        ...


def enrich_candidate(
    candidate: WalletCandidate,
    provider: WalletFinancialProvider,
) -> WalletCandidate:
    """Return a new WalletCandidate with financial fields populated from provider.

    The original candidate is frozen — a new instance is returned with
    balance_usd, exposure_pct, and drawdown_pct replaced.

    Args:
        candidate: Source WalletCandidate (financial fields may be 0.0).
        provider:  WalletFinancialProvider supplying live values.

    Returns:
        New WalletCandidate with financial fields set from provider.
    """
    balance = provider.get_balance_usd(candidate.wallet_id)
    exposure = provider.get_exposure_pct(candidate.wallet_id)
    drawdown = provider.get_drawdown_pct(candidate.wallet_id)
    enriched = replace(
        candidate,
        balance_usd=balance,
        exposure_pct=exposure,
        drawdown_pct=drawdown,
    )
    log.debug(
        "wallet_candidate_enriched",
        wallet_id=candidate.wallet_id,
        balance_usd=balance,
        exposure_pct=exposure,
        drawdown_pct=drawdown,
    )
    return enriched


# ── CapitalRiskGate ───────────────────────────────────────────────────────────


class CapitalRiskGate:
    """Risk gate that enforces capital-mode limits from CapitalModeConfig.

    Evaluation order:
      1. kill_switch check (always first — no gate check required)
      2. idempotency dedup
      3. LIVE mode: all 5 capital gates must be set (raises CapitalModeGuardError)
      4. edge validity (non-positive / below MIN_EDGE)
      5. liquidity floor (from config.min_liquidity_usd)
      6. drawdown ceiling (from config.drawdown_limit_pct)
      7. exposure cap (from config.max_position_fraction)
      8. daily loss limit (from config.daily_loss_limit_usd)

    Args:
        config: CapitalModeConfig instance — supplies all limits and gate state.
    """

    def __init__(self, config: CapitalModeConfig) -> None:
        self._config = config

    def evaluate(self, signal: CandidateSignal, state: PublicBetaState) -> RiskDecision:
        """Evaluate a candidate signal against capital-mode risk limits.

        Args:
            signal: CandidateSignal with edge, liquidity, signal_id.
            state:  Live PublicBetaState (kill_switch, drawdown, exposure, realized_pnl).

        Returns:
            RiskDecision(allowed=True, reason="allowed") when all checks pass.
            RiskDecision(allowed=False, reason=...) when any check fails.

        Raises:
            CapitalModeGuardError: LIVE mode requested but a capital gate is off.
        """
        # 1. kill_switch — immediate halt, no gate verification needed
        if state.kill_switch:
            return RiskDecision(False, "kill_switch_enabled")

        # 2. idempotency — prevent double-processing the same signal
        if signal.signal_id in state.processed_signals:
            return RiskDecision(False, "idempotency_duplicate")

        # 3. LIVE mode gate enforcement — all 5 gates must be on
        if self._config.trading_mode == "LIVE":
            self._config.validate()

        # 4. edge validity
        if signal.edge <= 0:
            return RiskDecision(False, "non_positive_ev")
        if signal.edge < _MIN_EDGE:
            return RiskDecision(False, "edge_below_threshold")

        # 5. liquidity floor (from config, not hardcoded)
        if signal.liquidity < self._config.min_liquidity_usd:
            return RiskDecision(False, "liquidity_below_floor")

        # 6. drawdown ceiling (from config — enforces <= drawdown_limit_pct)
        if state.drawdown > self._config.drawdown_limit_pct:
            return RiskDecision(False, "drawdown_stop")

        # 7. exposure cap (from config — enforces < max_position_fraction)
        if state.exposure >= self._config.max_position_fraction:
            return RiskDecision(False, "exposure_cap")

        # 8. daily loss limit (from config — must be negative; breached when pnl <= limit)
        if state.realized_pnl <= self._config.daily_loss_limit_usd:
            return RiskDecision(False, "daily_loss_limit")

        return RiskDecision(True, "allowed")

    def status(self, state: PublicBetaState) -> dict[str, object]:
        """Return current gate state snapshot for operator/Telegram visibility.

        Args:
            state: Live PublicBetaState.

        Returns:
            Dict with all limit values and current state metrics.
        """
        return {
            "kill_switch": state.kill_switch,
            "mode": self._config.trading_mode,
            "gates": self._config.open_gates_report(),
            "capital_mode_allowed": self._config.is_capital_mode_allowed(),
            "kelly_fraction": self._config.kelly_fraction,
            "drawdown_pct": round(state.drawdown * 100, 2),
            "drawdown_limit_pct": round(self._config.drawdown_limit_pct * 100, 1),
            "drawdown_ok": state.drawdown <= self._config.drawdown_limit_pct,
            "exposure_pct": round(state.exposure * 100, 2),
            "exposure_limit_pct": round(self._config.max_position_fraction * 100, 1),
            "exposure_ok": state.exposure < self._config.max_position_fraction,
            "min_edge": _MIN_EDGE,
            "liquidity_floor_usd": self._config.min_liquidity_usd,
            "daily_pnl_usd": round(state.realized_pnl, 2),
            "daily_loss_limit_usd": self._config.daily_loss_limit_usd,
            "daily_pnl_ok": state.realized_pnl > self._config.daily_loss_limit_usd,
            "last_risk_reason": state.last_risk_reason,
            "wallet_cash": state.wallet_cash,
            "wallet_equity": state.wallet_equity,
            "open_positions": len(state.positions),
        }
