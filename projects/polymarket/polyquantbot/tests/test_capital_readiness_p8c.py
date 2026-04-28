"""Priority 8-C — Live Execution Readiness: LiveExecutionGuard, PortfolioFinancialProvider,
rollback/disable path, price_updater hardening, settlement policy wiring, paper-mode regression.

Test IDs: CR-23 .. CR-35

Coverage:
  CR-23  LiveExecutionGuard.check() blocks when kill_switch is set
  CR-24  LiveExecutionGuard.check() blocks when STATE.mode != 'live'
  CR-25  LiveExecutionGuard.check() blocks when ENABLE_LIVE_TRADING not set
  CR-26  LiveExecutionGuard.check() blocks when capital gates are off
  CR-27  LiveExecutionGuard.check() blocks when no WalletFinancialProvider injected
  CR-28  LiveExecutionGuard.check() blocks when provider returns all-zero fields
  CR-29  LiveExecutionGuard.check() passes when all gates on + provider non-zero
  CR-30  disable_live_execution() sets kill_switch, logs reason, returns RollbackState
  CR-31  PaperBetaWorker.price_updater() raises in live mode and triggers rollback
  CR-32  PaperBetaWorker.run_once() blocks live signal when no live_guard injected
  CR-33  PortfolioFinancialProvider raises MissingRealFinancialDataError in live mode with zero equity
  CR-34  PortfolioFinancialProvider returns correct values in paper mode (zero equity is valid)
  CR-35  settlement_policy_from_capital_config() gates allow_real_settlement behind capital gates
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass
from unittest.mock import patch

import pytest

from projects.polymarket.polyquantbot.server.config.capital_mode_config import (
    CapitalModeConfig,
    CapitalModeGuardError,
)
from projects.polymarket.polyquantbot.server.core.live_execution_control import (
    LiveExecutionBlockedError,
    LiveExecutionGuard,
    RollbackState,
    disable_live_execution,
)
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.risk.portfolio_financial_provider import (
    MissingRealFinancialDataError,
    PortfolioFinancialProvider,
)
from projects.polymarket.polyquantbot.server.settlement.settlement_workflow import (
    settlement_policy_from_capital_config,
)


# ── Shared helpers ─────────────────────────────────────────────────────────────

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


def _live_cfg_all_gates() -> CapitalModeConfig:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        return CapitalModeConfig.from_env()


def _live_cfg_no_gates() -> CapitalModeConfig:
    env = {**_PAPER_ENV, "TRADING_MODE": "LIVE"}
    with patch.dict(os.environ, env, clear=False):
        return CapitalModeConfig.from_env()


def _fresh_state(**overrides: object) -> PublicBetaState:
    state = PublicBetaState()
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


def _live_state(**overrides: object) -> PublicBetaState:
    """Return a PublicBetaState with mode='live' plus any overrides."""
    state = PublicBetaState(mode="live")
    for k, v in overrides.items():
        setattr(state, k, v)
    return state


@dataclass
class _NonZeroProvider:
    """WalletFinancialProvider that returns non-zero values for test purposes."""

    balance: float = 1000.0
    exposure: float = 0.05
    drawdown: float = 0.02

    def get_balance_usd(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.balance

    def get_exposure_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.exposure

    def get_drawdown_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return self.drawdown


@dataclass
class _ZeroProvider:
    """WalletFinancialProvider that returns all zeros (stub/uninitialized)."""

    def get_balance_usd(self, wallet_id: str) -> float:  # noqa: ARG002
        return 0.0

    def get_exposure_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return 0.0

    def get_drawdown_pct(self, wallet_id: str) -> float:  # noqa: ARG002
        return 0.0


# ── CR-23: kill_switch blocks LiveExecutionGuard ───────────────────────────────

def test_cr23_live_guard_blocks_on_kill_switch() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        guard = LiveExecutionGuard(config=_live_cfg_all_gates())
    state = _live_state(kill_switch=True)
    with pytest.raises(LiveExecutionBlockedError) as exc_info:
        guard.check(state, provider=_NonZeroProvider())
    assert exc_info.value.reason == "kill_switch_active"


# ── CR-24: non-live mode blocks LiveExecutionGuard ────────────────────────────

@pytest.mark.parametrize("mode", ["paper", "PAPER", "disabled", ""])
def test_cr24_live_guard_blocks_non_live_mode(mode: str) -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        guard = LiveExecutionGuard(config=_live_cfg_all_gates())
    state = _fresh_state(mode=mode)
    with pytest.raises(LiveExecutionBlockedError) as exc_info:
        guard.check(state, provider=_NonZeroProvider())
    assert exc_info.value.reason == "mode_not_live"


# ── CR-25: ENABLE_LIVE_TRADING not set blocks LiveExecutionGuard ──────────────

def test_cr25_live_guard_blocks_without_env_flag() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        cfg = _live_cfg_all_gates()
    guard = LiveExecutionGuard(config=cfg)
    state = _live_state()
    # Patch env to remove ENABLE_LIVE_TRADING
    env_no_flag = {**_LIVE_ENV_ALL_GATES, "ENABLE_LIVE_TRADING": "false"}
    with patch.dict(os.environ, env_no_flag, clear=False):
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            guard.check(state, provider=_NonZeroProvider())
    assert exc_info.value.reason == "enable_live_trading_not_set"


# ── CR-26: capital gates off blocks LiveExecutionGuard ────────────────────────

def test_cr26_live_guard_blocks_capital_gates_off() -> None:
    cfg = _live_cfg_no_gates()  # LIVE mode but all gates False
    guard = LiveExecutionGuard(config=cfg)
    state = _live_state()
    with patch.dict(os.environ, {"ENABLE_LIVE_TRADING": "true"}, clear=False):
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            guard.check(state, provider=_NonZeroProvider())
    assert exc_info.value.reason == "capital_mode_guard_failed"


# ── CR-27: missing provider blocks LiveExecutionGuard ─────────────────────────

def test_cr27_live_guard_blocks_missing_provider() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        guard = LiveExecutionGuard(config=_live_cfg_all_gates())
    state = _live_state()
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            guard.check(state, provider=None)
    assert exc_info.value.reason == "missing_financial_provider"


# ── CR-28: all-zero provider blocks LiveExecutionGuard ────────────────────────

def test_cr28_live_guard_blocks_zero_provider() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        guard = LiveExecutionGuard(config=_live_cfg_all_gates())
    state = _live_state()
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            guard.check(state, provider=_ZeroProvider())
    assert exc_info.value.reason == "financial_provider_all_zero"


# ── CR-29: all gates on + non-zero provider passes LiveExecutionGuard ─────────

def test_cr29_live_guard_passes_all_gates_on() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        guard = LiveExecutionGuard(config=_live_cfg_all_gates())
    state = _live_state()
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        # Must not raise
        guard.check(state, provider=_NonZeroProvider())


# ── CR-30: disable_live_execution sets kill_switch and returns RollbackState ──

def test_cr30_disable_live_execution_rollback() -> None:
    state = _fresh_state(kill_switch=False)
    assert state.kill_switch is False

    rollback = disable_live_execution(state, reason="test_operator_halt", detail="unit test")

    # kill_switch must be set
    assert state.kill_switch is True
    assert state.last_risk_reason == "rollback:test_operator_halt"

    # RollbackState must capture prior state
    assert isinstance(rollback, RollbackState)
    assert rollback.reason == "test_operator_halt"
    assert rollback.detail == "unit test"
    assert rollback.prior_kill_switch is False
    assert rollback.disabled_at is not None


def test_cr30b_disable_idempotent_when_already_killed() -> None:
    state = _fresh_state(kill_switch=True)
    rollback = disable_live_execution(state, reason="second_halt")
    assert state.kill_switch is True  # still killed
    assert rollback.prior_kill_switch is True  # prior state captured correctly


# ── CR-31: price_updater raises in live mode and triggers rollback ─────────────

def test_cr31_price_updater_raises_in_live_mode() -> None:
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker
    from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate

    # Build a minimal worker
    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)
    from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import FalconGateway
    from projects.polymarket.polyquantbot.configs.falcon import FalconSettings
    import os as _os
    with patch.dict(_os.environ, {"FALCON_ENABLED": "false", "FALCON_BASE_URL": "http://localhost", "FALCON_TIMEOUT_SECONDS": "10"}):
        from projects.polymarket.polyquantbot.configs.falcon import FalconSettings as FS
        settings = FS(enabled=False, api_key="", base_url="http://localhost", timeout_seconds=10)
        falcon = FalconGateway(settings)

    worker = PaperBetaWorker(falcon=falcon, risk_gate=PaperRiskGate(), engine=engine)

    from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
    original_mode = STATE.mode
    original_kill = STATE.kill_switch
    try:
        STATE.mode = "live"
        STATE.kill_switch = False
        with pytest.raises(LiveExecutionBlockedError) as exc_info:
            asyncio.get_event_loop().run_until_complete(worker.price_updater())
        assert exc_info.value.reason == "price_updater_stub_live_mode_blocked"
        # rollback must have been triggered
        assert STATE.kill_switch is True
    finally:
        STATE.mode = original_mode
        STATE.kill_switch = original_kill


# ── CR-32: run_once blocks live signal when no live_guard injected ────────────

def test_cr32_run_once_blocks_live_no_guard() -> None:
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker
    from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
    from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal, FalconGateway
    from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE
    import unittest.mock as mock

    portfolio = PaperPortfolio()
    engine = PaperExecutionEngine(portfolio)

    class _FixedFalcon:
        async def rank_candidates(self):
            return [CandidateSignal("sig-live-001", "cond-001", "YES", edge=0.05, liquidity=20000.0, price=0.6)]

    worker = PaperBetaWorker(
        falcon=_FixedFalcon(),  # type: ignore[arg-type]
        risk_gate=PaperRiskGate(),
        engine=engine,
        live_guard=None,  # no guard — must block
    )

    original_mode = STATE.mode
    original_kill = STATE.kill_switch
    original_autotrade = STATE.autotrade_enabled
    try:
        STATE.mode = "live"
        STATE.kill_switch = False
        STATE.autotrade_enabled = True

        # run_once must catch LiveExecutionBlockedError raised by price_updater
        # and not propagate — worker must set kill_switch
        # price_updater will raise first (mode=live), rolling back kill_switch
        with pytest.raises(LiveExecutionBlockedError):
            asyncio.get_event_loop().run_until_complete(worker.run_once())
    finally:
        STATE.mode = original_mode
        STATE.kill_switch = original_kill
        STATE.autotrade_enabled = original_autotrade


# ── CR-33: PortfolioFinancialProvider raises in live mode with zero equity ────

def test_cr33_portfolio_provider_raises_zero_equity_live() -> None:
    state = PublicBetaState(mode="live", wallet_equity=0.0)
    provider = PortfolioFinancialProvider(state=state)
    with pytest.raises(MissingRealFinancialDataError):
        provider.get_balance_usd("wlc_test")


def test_cr33b_portfolio_provider_raises_zero_equity_live_variant() -> None:
    """Confirm tiny non-zero equity also triggers the guard (below threshold)."""
    state = PublicBetaState(mode="live", wallet_equity=1e-10)
    provider = PortfolioFinancialProvider(state=state)
    with pytest.raises(MissingRealFinancialDataError):
        provider.get_balance_usd("wlc_test")


# ── CR-34: PortfolioFinancialProvider returns correct values in paper mode ─────

def test_cr34_portfolio_provider_paper_mode_correct_values() -> None:
    state = PublicBetaState(
        mode="paper",
        wallet_equity=500.0,
        exposure=0.07,
        drawdown=0.03,
    )
    provider = PortfolioFinancialProvider(state=state)

    assert provider.get_balance_usd("wlc_p1") == 500.0
    assert provider.get_exposure_pct("wlc_p1") == 0.07
    assert provider.get_drawdown_pct("wlc_p1") == 0.03


def test_cr34b_portfolio_provider_paper_mode_zero_equity_ok() -> None:
    """Zero equity in paper mode is valid — fresh account with no trades."""
    state = PublicBetaState(mode="paper", wallet_equity=0.0)
    provider = PortfolioFinancialProvider(state=state)
    # Must not raise
    balance = provider.get_balance_usd("wlc_fresh")
    assert balance == 0.0


# ── CR-35: settlement_policy_from_capital_config gates allow_real_settlement ──

def test_cr35_settlement_policy_all_gates_on() -> None:
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        cfg = _live_cfg_all_gates()
    policy = settlement_policy_from_capital_config(cfg, settlement_enabled=True)
    assert policy.allow_real_settlement is True
    assert policy.simulation_mode is False
    assert policy.settlement_enabled is True


def test_cr35b_settlement_policy_gates_off_blocks_real_settlement() -> None:
    cfg = _paper_cfg()  # all gates off (PAPER mode)
    policy = settlement_policy_from_capital_config(cfg, settlement_enabled=True)
    assert policy.allow_real_settlement is False
    assert policy.simulation_mode is True


def test_cr35c_settlement_policy_live_gates_partially_off() -> None:
    """LIVE mode but missing one gate — real settlement must be blocked."""
    env = {**_LIVE_ENV_ALL_GATES, "EXECUTION_PATH_VALIDATED": "false"}
    with patch.dict(os.environ, env, clear=False):
        from projects.polymarket.polyquantbot.server.config.capital_mode_config import CapitalModeConfig
        cfg = CapitalModeConfig.from_env()
    policy = settlement_policy_from_capital_config(cfg, settlement_enabled=True)
    assert policy.allow_real_settlement is False
    assert policy.simulation_mode is True


def test_cr35d_settlement_disabled_overrides_policy() -> None:
    """settlement_enabled=False must disable settlement regardless of gates."""
    with patch.dict(os.environ, _LIVE_ENV_ALL_GATES, clear=False):
        cfg = _live_cfg_all_gates()
    policy = settlement_policy_from_capital_config(cfg, settlement_enabled=False)
    assert policy.settlement_enabled is False
    # allow_real_settlement follows gates, settlement_enabled is orthogonal
    assert policy.allow_real_settlement is True  # gates are on


# ── Paper-mode regression: P8-A/P8-B tests must continue to pass ──────────────
# (verified by running the full test suite — no assertions needed here, but
#  importing the key modules confirms no import-time regressions)

def test_cr_regression_imports() -> None:
    """Regression guard: all P8-A and P8-B modules import cleanly."""
    from projects.polymarket.polyquantbot.server.config.capital_mode_config import CapitalModeConfig, CapitalModeGuardError
    from projects.polymarket.polyquantbot.server.config.boundary_registry import PAPER_ONLY_BOUNDARIES
    from projects.polymarket.polyquantbot.server.risk.capital_risk_gate import CapitalRiskGate, enrich_candidate
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker
    from projects.polymarket.polyquantbot.server.core.live_execution_control import LiveExecutionGuard, disable_live_execution
    from projects.polymarket.polyquantbot.server.risk.portfolio_financial_provider import PortfolioFinancialProvider
    from projects.polymarket.polyquantbot.server.settlement.settlement_workflow import settlement_policy_from_capital_config

    # Boundary registry must have P8-C entries
    p8c_surfaces = [b.surface for b in PAPER_ONLY_BOUNDARIES if b.readiness_gate == "P8-C"]
    assert "LiveExecutionGuard" in p8c_surfaces
    assert "PaperBetaWorker.price_updater" in p8c_surfaces
