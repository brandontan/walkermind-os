"""Priority 8-B — Capital Risk Controls Hardening: CapitalRiskGate + WalletFinancialProvider.

Test IDs: CR-13 .. CR-22

Coverage:
  CR-13  CapitalRiskGate.evaluate() rejects when kill_switch=True
  CR-14  CapitalRiskGate.evaluate() rejects idempotency duplicate
  CR-15  CapitalRiskGate.evaluate() rejects non-positive edge
  CR-16  CapitalRiskGate.evaluate() rejects drawdown > config.drawdown_limit_pct
  CR-17  CapitalRiskGate.evaluate() rejects exposure >= config.max_position_fraction
  CR-18  CapitalRiskGate.evaluate() rejects realized_pnl <= config.daily_loss_limit_usd
  CR-19  CapitalRiskGate.evaluate() allows signal when all conditions clear (PAPER mode)
  CR-20  CapitalRiskGate.evaluate() raises CapitalModeGuardError in LIVE mode with gates off
  CR-21  enrich_candidate() populates financial fields from WalletFinancialProvider
  CR-22  Enriched candidate with high drawdown fails WalletSelectionPolicy risk gate
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
    CapitalModeGuardError,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.orchestration.schemas import (
    RoutingRequest,
    WalletCandidate,
)
from projects.polymarket.polyquantbot.server.orchestration.wallet_selector import (
    WalletSelectionPolicy,
)
from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import (
    CapitalRiskGate,
    WalletFinancialProvider,
    enrich_candidate,
)

# ── Shared fixtures ────────────────────────────────────────────────────────────

_PAPER_ENV = {
    "TRADING_MODE": "PAPER",
    "ENABLE_LIVE_TRADING": "false",
    "CAPITAL_MODE_CONFIRMED": "false",
    "RISK_CONTROLS_VALIDATED": "false",
    "EXECUTION_PATH_VALIDATED": "false",
    "SECURITY_HARDENING_VALIDATED": "false",
}

_LIVE_ENV_ALL_GATES = {
    "TRADING_MODE": "LIVE",
    "ENABLE_LIVE_TRADING": "true",
    "CAPITAL_MODE_CONFIRMED": "true",
    "RISK_CONTROLS_VALIDATED": "true",
    "EXECUTION_PATH_VALIDATED": "true",
    "SECURITY_HARDENING_VALIDATED": "true",
}


def _paper_cfg() -> CapitalModeConfig:
    with patch.dict(os.environ, _PAPER_ENV, clear=False):
        return CapitalModeConfig.from_env()


def _live_cfg_no_gates() -> CapitalModeConfig:
    live_no_gates = {**_PAPER_ENV, "TRADING_MODE": "LIVE"}
    with patch.dict(os.environ, live_no_gates, clear=False):
        return CapitalModeConfig.from_env()


def _good_signal(signal_id: str = "sig-001") -> CandidateSignal:
    return CandidateSignal(
        signal_id=signal_id,
        condition_id="cond-001",
        side="YES",
        edge=0.05,
        liquidity=20_000.0,
        price=0.60,
    )


def _clean_state(**overrides: object) -> PublicBetaState:
    state = PublicBetaState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _active_candidate(
    wallet_id: str = "wlc_test",
    balance_usd: float = 500.0,
    exposure_pct: float = 0.05,
    drawdown_pct: float = 0.02,
) -> WalletCandidate:
    return WalletCandidate(
        wallet_id=wallet_id,
        tenant_id="t1",
        user_id="u1",
        lifecycle_status="active",
        balance_usd=balance_usd,
        exposure_pct=exposure_pct,
        drawdown_pct=drawdown_pct,
    )


# ── CR-13: kill_switch → rejected ─────────────────────────────────────────────

def test_cr13_kill_switch_rejects() -> None:
    gate = CapitalRiskGate(config=_paper_cfg())
    state = _clean_state(kill_switch=True)
    decision = gate.evaluate(_good_signal(), state)
    assert decision.allowed is False
    assert decision.reason == "kill_switch_enabled"


# ── CR-14: idempotency duplicate → rejected ───────────────────────────────────

def test_cr14_idempotency_duplicate_rejects() -> None:
    gate = CapitalRiskGate(config=_paper_cfg())
    state = _clean_state(processed_signals={"sig-001"})
    decision = gate.evaluate(_good_signal(signal_id="sig-001"), state)
    assert decision.allowed is False
    assert decision.reason == "idempotency_duplicate"


# ── CR-15: non-positive edge → rejected ───────────────────────────────────────

@pytest.mark.parametrize("edge", [0.0, -0.01, -1.0])
def test_cr15_non_positive_edge_rejects(edge: float) -> None:
    gate = CapitalRiskGate(config=_paper_cfg())
    sig = CandidateSignal("sig-002", "cond-002", "YES", edge=edge, liquidity=20_000.0, price=0.5)
    decision = gate.evaluate(sig, _clean_state())
    assert decision.allowed is False
    assert decision.reason == "non_positive_ev"


# ── CR-16: drawdown > limit → rejected ───────────────────────────────────────

def test_cr16_drawdown_stop_rejects() -> None:
    cfg = _paper_cfg()
    gate = CapitalRiskGate(config=cfg)
    # drawdown exactly at limit passes; one tick above rejects
    at_limit = _clean_state(drawdown=cfg.drawdown_limit_pct)
    assert gate.evaluate(_good_signal(), at_limit).allowed is True

    over_limit = _clean_state(drawdown=cfg.drawdown_limit_pct + 0.001)
    decision = gate.evaluate(_good_signal(), over_limit)
    assert decision.allowed is False
    assert decision.reason == "drawdown_stop"


# ── CR-17: exposure >= limit → rejected ───────────────────────────────────────

def test_cr17_exposure_cap_rejects() -> None:
    cfg = _paper_cfg()
    gate = CapitalRiskGate(config=cfg)
    just_under = _clean_state(exposure=cfg.max_position_fraction - 0.001)
    assert gate.evaluate(_good_signal(), just_under).allowed is True

    at_cap = _clean_state(exposure=cfg.max_position_fraction)
    decision = gate.evaluate(_good_signal(), at_cap)
    assert decision.allowed is False
    assert decision.reason == "exposure_cap"


# ── CR-18: daily loss limit breached → rejected ───────────────────────────────

def test_cr18_daily_loss_limit_rejects() -> None:
    cfg = _paper_cfg()
    gate = CapitalRiskGate(config=cfg)
    # one dollar above limit passes
    above_limit = _clean_state(realized_pnl=cfg.daily_loss_limit_usd + 1.0)
    assert gate.evaluate(_good_signal(), above_limit).allowed is True

    # exactly at limit → rejected (state.realized_pnl <= limit triggers rejection)
    at_limit = _clean_state(realized_pnl=cfg.daily_loss_limit_usd)
    decision = gate.evaluate(_good_signal(), at_limit)
    assert decision.allowed is False
    assert decision.reason == "daily_loss_limit"

    below_limit = _clean_state(realized_pnl=cfg.daily_loss_limit_usd - 100.0)
    decision2 = gate.evaluate(_good_signal(), below_limit)
    assert decision2.allowed is False
    assert decision2.reason == "daily_loss_limit"


# ── CR-19: all clear in PAPER mode → allowed ─────────────────────────────────

def test_cr19_all_clear_paper_mode_allowed() -> None:
    gate = CapitalRiskGate(config=_paper_cfg())
    # max_position_fraction defaults to 0.02; use exposure well below it
    state = _clean_state(
        drawdown=0.01,
        exposure=0.01,
        realized_pnl=0.0,
    )
    decision = gate.evaluate(_good_signal(), state)
    assert decision.allowed is True
    assert decision.reason == "allowed"


# ── CR-20: LIVE mode with gates off → CapitalModeGuardError ──────────────────

def test_cr20_live_mode_gates_off_raises() -> None:
    gate = CapitalRiskGate(config=_live_cfg_no_gates())
    state = _clean_state()
    with pytest.raises(CapitalModeGuardError):
        gate.evaluate(_good_signal(), state)


# ── CR-21: enrich_candidate populates financial fields from provider ──────────

@dataclass
class _StubProvider:
    """Fixed-value WalletFinancialProvider for testing."""

    balance: float = 1000.0
    exposure: float = 0.07
    drawdown: float = 0.03

    def get_balance_usd(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.balance

    def get_exposure_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.exposure

    def get_drawdown_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.drawdown


def test_cr21_enrich_candidate_populates_fields() -> None:
    zeroed = WalletCandidate(
        wallet_id="wlc_zero",
        tenant_id="t1",
        user_id="u1",
        lifecycle_status="active",
        balance_usd=0.0,
        exposure_pct=0.0,
        drawdown_pct=0.0,
    )
    provider = _StubProvider(balance=2500.0, exposure=0.06, drawdown=0.04)
    enriched = enrich_candidate(zeroed, provider)

    assert enriched.wallet_id == "wlc_zero"
    assert enriched.balance_usd == 2500.0
    assert enriched.exposure_pct == 0.06
    assert enriched.drawdown_pct == 0.04
    # original is unchanged (frozen dataclass)
    assert zeroed.balance_usd == 0.0


# ── CR-22: enriched candidate with excessive drawdown fails selection policy ──

def test_cr22_enriched_candidate_rejected_by_risk_gate() -> None:
    policy = WalletSelectionPolicy()
    request = RoutingRequest(
        tenant_id="t1",
        user_id="u1",
        required_usd=100.0,
        mode="paper",
    )
    # Candidate with drawdown above the 8% ceiling after enrichment
    zeroed = WalletCandidate(
        wallet_id="wlc_risky",
        tenant_id="t1",
        user_id="u1",
        lifecycle_status="active",
        balance_usd=0.0,
        exposure_pct=0.0,
        drawdown_pct=0.0,
    )
    # Enrich with drawdown above 0.08 ceiling
    provider = _StubProvider(balance=5000.0, exposure=0.05, drawdown=0.09)
    enriched = enrich_candidate(zeroed, provider)

    result = policy.select(request=request, candidates=[enriched])
    assert result.outcome == "risk_blocked"
    assert result.selected_wallet_id is None
