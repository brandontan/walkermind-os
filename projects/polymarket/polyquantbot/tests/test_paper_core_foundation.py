from __future__ import annotations

import asyncio

from projects.polymarket.polyquantbot.server.core.public_beta_state import STATE, PaperAccount
from projects.polymarket.polyquantbot.server.execution.paper_execution import PaperExecutionEngine
from projects.polymarket.polyquantbot.server.integrations.falcon_gateway import CandidateSignal
from projects.polymarket.polyquantbot.server.portfolio.paper_portfolio import PaperPortfolio
from projects.polymarket.polyquantbot.server.risk.paper_risk_gate import PaperRiskGate
from projects.polymarket.polyquantbot.server.storage.paper_account_store import PersistentPaperAccountStore
from projects.polymarket.polyquantbot.server.workers.paper_beta_worker import PaperBetaWorker


class _SingleCandidateFalcon:
    async def rank_candidates(self) -> list[CandidateSignal]:
        return [
            CandidateSignal(
                signal_id="sig-paper-1",
                condition_id="cond-paper-1",
                side="YES",
                edge=0.05,
                liquidity=30000.0,
                price=0.5,
            )
        ]


def _reset_state() -> None:
    STATE.mode = "paper"
    STATE.autotrade_enabled = True
    STATE.kill_switch = False
    STATE.drawdown = 0.0
    STATE.exposure = 0.0
    STATE.last_risk_reason = ""
    STATE.paper_account = PaperAccount()
    STATE.positions = []
    STATE.orders = []
    STATE.processed_signals = set()
    STATE.pnl = 0.0


def test_paper_account_persistence_create_and_load(tmp_path) -> None:
    _reset_state()
    store = PersistentPaperAccountStore(tmp_path / "paper_account.json")
    store.save(account=STATE.paper_account, positions=STATE.positions, orders=STATE.orders)
    loaded_account, loaded_positions, loaded_orders = store.load()
    assert loaded_account.account_id == "paper-default"
    assert loaded_account.cash_balance == 10000.0
    assert loaded_positions == []
    assert loaded_orders == []


def test_paper_execution_lifecycle_is_deterministic() -> None:
    _reset_state()
    signal = CandidateSignal(
        signal_id="sig-life-1",
        condition_id="cond-life-1",
        side="YES",
        edge=0.04,
        liquidity=25000.0,
        price=0.6,
    )
    engine = PaperExecutionEngine(PaperPortfolio())
    event = engine.execute(signal=signal, state=STATE)
    assert event["order_status"] == "filled"
    assert event["lifecycle"] == ["created", "accepted", "filled"]
    assert event["order_id"] == "paper-ord-1"
    assert STATE.orders[0].filled_size == 64.0


def test_paper_risk_guard_enforces_notional_cap() -> None:
    _reset_state()
    signal = CandidateSignal(
        signal_id="sig-risk-1",
        condition_id="cond-risk-1",
        side="YES",
        edge=0.05,
        liquidity=30000.0,
        price=20.0,
    )
    decision = PaperRiskGate().evaluate(signal=signal, state=STATE)
    assert decision.allowed is False
    assert decision.reason == "position_notional_cap"


def test_portfolio_surface_reflects_narrow_worker_path(tmp_path, monkeypatch) -> None:
    _reset_state()
    monkeypatch.setenv("CRUSADER_PAPER_ACCOUNT_STORAGE_PATH", str(tmp_path / "paper_account.json"))
    worker = PaperBetaWorker(
        _SingleCandidateFalcon(),
        PaperRiskGate(),
        PaperExecutionEngine(PaperPortfolio()),
        PersistentPaperAccountStore(tmp_path / "paper_account.json"),
    )
    events = asyncio.run(worker.run_once())
    assert len(events) == 1
    assert len(STATE.positions) == 1
    assert len(STATE.orders) == 1
    assert STATE.paper_account.order_count == 1
    assert STATE.paper_account.equity <= 10000.0
