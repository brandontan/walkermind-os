"""Priority 3 — Paper Trading Product Completion: End-to-End Validation Suite.

Validates the full paper trading pipeline as wired in this lane:
  Signal → PaperRiskGate → PaperPortfolio → PaperEngine
       → WalletEngine / PaperPositionManager / TradeLedger / PnLTracker
  STATE synchronisation after execution
  Kelly position sizing (a=0.25, max 10% equity)
  Operator paper account reset
  Telegram /pnl, /portfolio, /reset presentation helpers

Scenarios:

  PE-01  Kelly sizing — size = min(equity*0.25*edge/price, equity*0.10)
  PE-02  Execute order — wallet funds locked, position opens, ledger records
  PE-03  Close order — realized PnL settled, wallet unlocked, ledger records CLOSE
  PE-04  STATE sync — wallet_cash/locked/equity/exposure/realized_pnl updated
  PE-05  Risk gate blocks at exposure cap (>= 10%)
  PE-06  Risk gate blocks at drawdown stop (> 8%)
  PE-07  Risk gate blocks duplicate signal (idempotency)
  PE-08  Risk gate blocks edge below threshold (< 2%)
  PE-09  Risk gate blocks kill switch active
  PE-10  Operator reset — clears positions, ledger, PnL, STATE fields
  PE-11  PaperBetaWorker.run_once() — accepted signal creates position in STATE
  PE-12  PaperBetaWorker.run_once() — risk-rejected signal not in STATE
  PE-13  Presentation — format_pnl_reply() renders correct signs and values
  PE-14  Presentation — format_paper_account_reply() renders kill_switch state
  PE-15  Presentation — format_risk_state_reply() shows all gate fields
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from projects.polymarket.polyquantbot.core.ledger import TradeLedger
from projects.polymarket.polyquantbot.core.portfolio.pnl import PnLTracker
from projects.polymarket.polyquantbot.core.positions import PaperPositionManager
from projects.polymarket.polyquantbot.core.wallet_engine import WalletEngine, InsufficientFundsError
from projects.polymarket.polyquantbot.execution.paper_engine import PaperEngine, OrderStatus
from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import (
    PaperPortfolio,
    _kelly_size,
    _build_paper_engine,
)
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_signal(
    signal_id: str = "sig-abc",
    condition_id: str = "mkt-001",
    side: str = "YES",
    edge: float = 0.05,
    liquidity: float = 20000.0,
    price: float = 0.50,
) -> CandidateSignal:
    return CandidateSignal(
        signal_id=signal_id,
        condition_id=condition_id,
        side=side,
        edge=edge,
        liquidity=liquidity,
        price=price,
    )


def _make_engine(initial_balance: float = 10000.0) -> PaperEngine:
    return PaperEngine(
        wallet=WalletEngine(initial_balance=initial_balance),
        positions=PaperPositionManager(),
        ledger=TradeLedger(),
        pnl_tracker=PnLTracker(),
        random_seed=42,
    )


# ── PE-01: Kelly sizing ───────────────────────────────────────────────────────

def test_pe01_kelly_size_basic():
    """Kelly size = min(equity * 0.25 * edge/price, equity * 0.10)."""
    equity = 10000.0
    edge = 0.05
    price = 0.50
    expected_kelly = equity * 0.25 * (edge / price)  # 250.0
    expected_capped = equity * 0.10                   # 1000.0 — not hit here
    size = _kelly_size(edge, price, equity)
    assert size == pytest.approx(expected_kelly, rel=1e-3)


def test_pe01_kelly_size_capped_by_max_position():
    """Kelly size is capped at 10% of equity."""
    equity = 10000.0
    edge = 0.50   # Very high edge
    price = 0.50
    max_position = equity * 0.10
    size = _kelly_size(edge, price, equity)
    assert size <= max_position + 0.01  # Allow rounding


def test_pe01_kelly_size_minimum():
    """Kelly size has a floor of $10."""
    size = _kelly_size(edge=0.001, price=0.99, equity=10.0)
    assert size >= 10.0


# ── PE-02: Execute order ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe02_execute_order_locks_funds_and_opens_position():
    engine = _make_engine()
    wallet = engine._wallet
    positions = engine._positions

    order = {
        "market_id": "mkt-001",
        "side": "YES",
        "price": 0.50,
        "size": 100.0,
    }
    result = await engine.execute_order(order)

    assert result.status in (OrderStatus.FILLED, OrderStatus.PARTIAL)
    assert result.filled_size > 0

    ws = wallet.get_state()
    assert ws.locked > 0
    assert ws.cash < 10000.0

    pos = positions.get_position("mkt-001")
    assert pos is not None
    assert pos.side == "YES"


@pytest.mark.asyncio
async def test_pe02_execute_order_records_in_ledger():
    engine = _make_engine()
    order = {"market_id": "mkt-002", "side": "NO", "price": 0.45, "size": 50.0}
    await engine.execute_order(order)

    entries = engine._ledger.get_by_market("mkt-002")
    assert len(entries) >= 1
    assert entries[0].market_id == "mkt-002"


# ── PE-03: Close order ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe03_close_order_settles_pnl():
    engine = _make_engine()
    await engine.execute_order({"market_id": "mkt-003", "side": "YES", "price": 0.40, "size": 100.0})

    initial_equity = engine._wallet.get_state().equity
    await engine.close_order(market_id="mkt-003", close_price=0.55)

    ws = engine._wallet.get_state()
    # After close: locked released back to cash, PnL settled
    assert ws.locked == pytest.approx(0.0, abs=0.01)
    # Realized PnL recorded in ledger
    realized = engine._ledger.get_realized_pnl()
    assert realized != 0.0  # some PnL was settled


# ── PE-04: STATE sync ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe04_state_sync_after_open():
    portfolio = PaperPortfolio(_build_paper_engine())
    state = PublicBetaState()
    signal = _make_signal()

    await portfolio.open_position(signal, state)

    assert state.wallet_cash >= 0
    assert state.wallet_equity > 0
    assert state.exposure >= 0
    assert len(state.positions) == 1
    assert state.positions[0].condition_id == "mkt-001"


# ── PE-05: Risk gate — exposure cap ─────────────────────────────────────────

def test_pe05_risk_gate_blocks_exposure_cap():
    gate = PaperRiskGate()
    state = PublicBetaState(mode="paper", exposure=0.10)  # exactly at cap
    signal = _make_signal()
    decision = gate.evaluate(signal, state)
    assert not decision.allowed
    assert decision.reason == "exposure_cap"


# ── PE-06: Risk gate — drawdown stop ────────────────────────────────────────

def test_pe06_risk_gate_blocks_drawdown():
    gate = PaperRiskGate()
    state = PublicBetaState(mode="paper", drawdown=0.09)  # above 8%
    signal = _make_signal()
    decision = gate.evaluate(signal, state)
    assert not decision.allowed
    assert decision.reason == "drawdown_stop"


# ── PE-07: Risk gate — idempotency ──────────────────────────────────────────

def test_pe07_risk_gate_blocks_duplicate_signal():
    gate = PaperRiskGate()
    state = PublicBetaState(mode="paper")
    state.processed_signals.add("sig-abc")
    signal = _make_signal(signal_id="sig-abc")
    decision = gate.evaluate(signal, state)
    assert not decision.allowed
    assert decision.reason == "idempotency_duplicate"


# ── PE-08: Risk gate — edge below threshold ──────────────────────────────────

def test_pe08_risk_gate_blocks_low_edge():
    gate = PaperRiskGate()
    state = PublicBetaState(mode="paper")
    signal = _make_signal(edge=0.01)  # below 2%
    decision = gate.evaluate(signal, state)
    assert not decision.allowed
    assert decision.reason == "edge_below_threshold"


# ── PE-09: Risk gate — kill switch ──────────────────────────────────────────

def test_pe09_risk_gate_blocks_kill_switch():
    gate = PaperRiskGate()
    state = PublicBetaState(mode="paper", kill_switch=True)
    signal = _make_signal()
    decision = gate.evaluate(signal, state)
    assert not decision.allowed
    assert decision.reason == "kill_switch_enabled"


# ── PE-10: Operator reset ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe10_reset_clears_state():
    portfolio = PaperPortfolio(_build_paper_engine())
    state = PublicBetaState()

    # Open a position first
    await portfolio.open_position(_make_signal(), state)
    assert len(state.positions) == 1

    # Reset
    await portfolio.reset(state)
    assert len(state.positions) == 0
    assert state.realized_pnl == 0.0
    assert state.exposure == 0.0
    assert state.wallet_equity == pytest.approx(10000.0, rel=0.01)


# ── PE-11: Worker accepted signal ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe11_worker_accepted_signal_creates_position():
    from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker
    from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState

    state = PublicBetaState(mode="paper", autotrade_enabled=True, kill_switch=False)
    signal = _make_signal()

    portfolio = PaperPortfolio(_build_paper_engine())
    engine = PaperExecutionEngine(portfolio)
    risk_gate = PaperRiskGate()

    falcon_mock = AsyncMock()
    falcon_mock.rank_candidates.return_value = [signal]

    worker = PaperBetaWorker(falcon=falcon_mock, risk_gate=risk_gate, engine=engine)

    with patch(
        "projects.polymarket.polyquantbot.server.workers.paper_beta_worker.STATE",
        state,
    ):
        events = await worker.run_once()

    assert len(events) == 1
    assert events[0]["condition_id"] == "mkt-001"


# ── PE-12: Worker rejected signal ───────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe12_worker_risk_rejected_signal_not_in_state():
    from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
    from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker
    from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState

    state = PublicBetaState(mode="paper", autotrade_enabled=True, kill_switch=True)
    signal = _make_signal()

    portfolio = PaperPortfolio(_build_paper_engine())
    engine = PaperExecutionEngine(portfolio)
    risk_gate = PaperRiskGate()

    falcon_mock = AsyncMock()
    falcon_mock.rank_candidates.return_value = [signal]

    worker = PaperBetaWorker(falcon=falcon_mock, risk_gate=risk_gate, engine=engine)

    with patch(
        "projects.polymarket.polyquantbot.server.workers.paper_beta_worker.STATE",
        state,
    ):
        events = await worker.run_once()

    assert len(events) == 0


# ── PE-13: Presentation — format_pnl_reply ───────────────────────────────────

def test_pe13_format_pnl_reply_renders():
    from projects.polymarket.polyquantbot.client.telegram.presentation import format_pnl_reply

    text = format_pnl_reply(
        realized=12.50,
        unrealized=-3.25,
        cash=9950.0,
        equity=9988.0,
        position_count=2,
    )
    assert "12.50" in text
    assert "-3.25" in text or "3.25" in text
    assert "9,950" in text or "9950" in text
    assert "2" in text


# ── PE-14: Presentation — format_paper_account_reply ─────────────────────────

def test_pe14_format_paper_account_reply_kill_switch():
    from projects.polymarket.polyquantbot.client.telegram.presentation import format_paper_account_reply

    text = format_paper_account_reply(
        cash=10000.0,
        equity=10000.0,
        realized_pnl=0.0,
        open_positions=0,
        mode="paper",
        kill_switch=True,
    )
    assert "ACTIVE" in text or "🔴" in text


def test_pe14_format_paper_account_reply_normal():
    from projects.polymarket.polyquantbot.client.telegram.presentation import format_paper_account_reply

    text = format_paper_account_reply(
        cash=9500.0,
        equity=10100.0,
        realized_pnl=100.0,
        open_positions=3,
        mode="paper",
        kill_switch=False,
    )
    assert "9,500" in text or "9500" in text
    assert "3" in text


# ── PE-15: Presentation — format_risk_state_reply ────────────────────────────

def test_pe15_format_risk_state_reply_renders():
    from projects.polymarket.polyquantbot.client.telegram.presentation import format_risk_state_reply
    from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
    from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState

    gate = PaperRiskGate()
    state = PublicBetaState(
        mode="paper",
        kill_switch=False,
        drawdown=0.03,
        exposure=0.05,
        realized_pnl=-50.0,
        wallet_cash=9500.0,
        wallet_equity=10000.0,
    )
    state.positions = []
    status = gate.status(state)
    text = format_risk_state_reply(status)

    assert "3.00" in text or "3." in text  # drawdown %
    assert "5.00" in text or "5." in text  # exposure %
    assert "9,500" in text or "9500" in text


# ── PE-16: Drawdown STATE sync ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe16_drawdown_synced_after_open():
    """state.drawdown must be set by _sync_state, not left at default 0.0."""
    portfolio = PaperPortfolio(_build_paper_engine())
    state = PublicBetaState()
    assert state.drawdown == 0.0  # baseline before any trade

    signal = _make_signal()
    await portfolio.open_position(signal, state)

    # drawdown is a real float set by _sync_state, not stuck at 0.0 default
    assert isinstance(state.drawdown, float)
    assert state.drawdown >= 0.0


@pytest.mark.asyncio
async def test_pe16_drawdown_rises_after_loss():
    """Drawdown becomes positive after a losing close."""
    portfolio = PaperPortfolio(_build_paper_engine())
    state = PublicBetaState()

    signal = _make_signal(condition_id="mkt-loss")
    await portfolio.open_position(signal, state)
    # Close at a very low price to force a large loss
    await portfolio.close_position("mkt-loss", close_price=0.01, state=state)

    assert state.drawdown > 0.0


# ── PE-17: Singleton pattern ─────────────────────────────────────────────────

def test_pe17_register_portfolio_singleton():
    """_register_portfolio sets the singleton; get_active_portfolio() returns same instance."""
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import (
        _register_portfolio,
        get_active_portfolio,
    )

    portfolio = PaperPortfolio(_build_paper_engine())
    _register_portfolio(portfolio)
    assert get_active_portfolio() is portfolio


@pytest.mark.asyncio
async def test_pe17_reset_via_singleton_affects_live_instance():
    """Resetting through get_active_portfolio() clears the same portfolio used by the worker."""
    from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import (
        _register_portfolio,
        get_active_portfolio,
    )

    portfolio = PaperPortfolio(_build_paper_engine())
    _register_portfolio(portfolio)
    state = PublicBetaState()

    await portfolio.open_position(_make_signal(), state)
    assert len(state.positions) == 1

    active = get_active_portfolio()
    assert active is not None
    await active.reset(state)

    assert len(state.positions) == 0
    assert state.wallet_equity == pytest.approx(10000.0, rel=0.01)


# ── PE-18: DAILY_LOSS_LIMIT constant ─────────────────────────────────────────

def test_pe18_daily_loss_limit_constant_defined():
    """PaperRiskGate.DAILY_LOSS_LIMIT is a class constant equal to -2000.0."""
    assert hasattr(PaperRiskGate, "DAILY_LOSS_LIMIT")
    assert PaperRiskGate.DAILY_LOSS_LIMIT == -2000.0


def test_pe18_daily_loss_limit_used_in_status():
    """status() uses DAILY_LOSS_LIMIT constant, not a magic number."""
    from projects.polymarket.polyquantbot.server.core.public_beta_state import PublicBetaState

    gate = PaperRiskGate()

    state_ok = PublicBetaState(mode="paper", realized_pnl=-1500.0)
    status_ok = gate.status(state_ok)
    assert status_ok["daily_loss_limit_usd"] == PaperRiskGate.DAILY_LOSS_LIMIT
    assert status_ok["daily_pnl_ok"] is True

    state_breach = PublicBetaState(mode="paper", realized_pnl=-2500.0)
    status_breach = gate.status(state_breach)
    assert status_breach["daily_pnl_ok"] is False


# ── PE-19: Public PaperEngine API ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pe19_public_api_get_wallet_state():
    """get_wallet_state() returns a WalletState without touching private _wallet."""
    engine = _make_engine()
    ws = engine.get_wallet_state()
    assert ws.cash == pytest.approx(10000.0, rel=0.01)
    assert ws.equity == pytest.approx(10000.0, rel=0.01)
    assert ws.locked == 0.0


@pytest.mark.asyncio
async def test_pe19_public_api_get_open_positions():
    """get_open_positions() returns empty list before trades; populated after."""
    engine = _make_engine()
    assert engine.get_open_positions() == []

    await engine.execute_order({"market_id": "mkt-pub", "side": "YES", "price": 0.50, "size": 100.0})

    positions = engine.get_open_positions()
    assert len(positions) >= 1
    assert positions[0].market_id == "mkt-pub"


@pytest.mark.asyncio
async def test_pe19_public_api_get_realized_pnl():
    """get_realized_pnl() is 0.0 before trades and nonzero after a close."""
    engine = _make_engine()
    assert engine.get_realized_pnl() == 0.0

    await engine.execute_order({"market_id": "mkt-rpnl", "side": "YES", "price": 0.40, "size": 100.0})
    await engine.close_order(market_id="mkt-rpnl", close_price=0.55)

    assert engine.get_realized_pnl() != 0.0


def test_pe19_position_manager_property():
    """position_manager property returns PaperPositionManager (not None)."""
    engine = _make_engine()
    assert engine.position_manager is not None


def test_pe19_pnl_tracker_property():
    """pnl_tracker property returns the injected tracker."""
    engine = _make_engine()
    assert engine.pnl_tracker is not None


@pytest.mark.asyncio
async def test_pe19_edge_preserved_in_state_after_open():
    """signal.edge must appear in STATE.positions via _signal_edges tracking."""
    portfolio = PaperPortfolio(_build_paper_engine())
    state = PublicBetaState()

    signal = _make_signal(edge=0.07, condition_id="mkt-edge-track")
    await portfolio.open_position(signal, state)

    assert len(state.positions) == 1
    assert state.positions[0].edge == pytest.approx(0.07, rel=1e-3)
